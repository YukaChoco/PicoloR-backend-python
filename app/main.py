import datetime
import json
import falcon
from PIL import Image
import io
import base64
import colorsys
import numpy as np
import psycopg2
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from sqlalchemy import create_engine, text


load_dotenv()

class DbConfig():
    def __init__(self, dbname, user, password, host, port):
        self.dbname = dbname
        self.user = user
        self.password = password
        self.host = host
        self.port = port

# 環境変数から取得し、Noneの場合はエラーを出力
dbname = os.getenv('DB_NAME')
user = os.getenv('DB_USER')
password = os.getenv('DB_PASSWORD')
host = os.getenv('DB_HOST')
port = os.getenv('DB_PORT')

if not all([dbname, user, password, host, port]):
    raise ValueError("One or more required environment variables are missing")

db_config = DbConfig(dbname=dbname, user=user, password=password, host=host, port=port)

class AppResource(object):
    def __init__(self,db_config:DbConfig) ->None:
        self.connection = psycopg2.connect(
            dbname=db_config.dbname,
            user=db_config.user,
            password=db_config.password,
            host=db_config.host,
            port=db_config.port
        )

    def on_post(self, req, resp):
        try:
            raw_json = req.bounded_stream.read()
            if raw_json is not None and raw_json:
                # raw_jsonがNoneでなく、かつ空でない場合の処理
                data = json.loads(raw_json)
                user_id = data.get("userID")
                color_id = data.get("colorID")
                image_base64 = data.get("image")

                if user_id is None or color_id is None or image_base64 is None:
                    raise ValueError("Missing required fields")

                color = "0AC74F"
                # 日本時間の現在時間を取得(日本時間)
                posted_at = datetime.datetime.now()
                start_at = self.get_start_at(color_id)

                # 結果をテキストとしてフォーマット
                posted_time = self.get_posted_time(start_at, posted_at)

                # Base64エンコードされた画像データをデコードしてPillowで読み込む
                image_data = io.BytesIO(base64.b64decode(image_base64))
                image = Image.open(image_data)

                # 入力カラーコードをHSV空間に変換し、Hueを取り出す
                input_hue = self.hex_to_hue(color)

                # 画像をHSV空間に変換し、条件を満たすピクセルのHueの平均値を計算
                is_success = self.check_image_hue(image, input_hue)

                # DBにPostgresqlでデータを追加
                self.insert_to_db(user_id, color_id, image_base64, posted_time)

                # 成功レスポンス
                resp.media = {
                    "is_success": True if is_success else False
                }
                resp.status = falcon.HTTP_200
            else:
                # raw_jsonがNoneまたは空の場合の処理
                raise ValueError("Empty request body")
        except json.JSONDecodeError:
            resp.text = json.dumps({"error": "Invalid JSON"})
            resp.status = falcon.HTTP_400
        except Exception as e:
            # 詳細なエラーメッセージをログに出力
            print(f"Error: {str(e)}")
            resp.text = json.dumps({"error": str(e)})
            resp.status = falcon.HTTP_500

    def get_start_at(self, color_id):
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT start_at FROM room_colors INNER JOIN rooms ON room_colors.room_id = rooms.id WHERE room_colors.id = %s",
                (color_id,)
            )
            result = cursor.fetchall()
            if len(result) == 0:
                raise ValueError("Room not found")
            if result[0][0] is None:
                raise ValueError("Room has not started yet")
            return result[0][0]

    def get_posted_time(self, start_at, posted_at):
        if start_at.tzinfo is not None:
            start_at = start_at.replace(tzinfo=None)
        elapsed_time = posted_at - start_at
        minutes, seconds = divmod(int(elapsed_time.total_seconds()), 60)
        return f"{minutes}:{seconds:02d}"

    def hex_to_hue(self, hex_color):
        # 16進数カラーコードをRGBに変換
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        # RGBをHSVに変換
        hsv = colorsys.rgb_to_hsv(rgb[0]/255.0, rgb[1]/255.0, rgb[2]/255.0)
        return hsv[0] * 360  # Hueを0-360の範囲に変換

    def check_image_hue(self, image, input_hue):
        # 画像をRGBからHSVに変換
        image = image.convert('RGB')
        np_image = np.array(image)
        hsv_image = np.apply_along_axis(lambda x: colorsys.rgb_to_hsv(x[0]/255.0, x[1]/255.0, x[2]/255.0), 2, np_image)
        
        # S >= 0.3 かつ V >= 0.3 のピクセルを抽出
        mask = (hsv_image[:,:,1] >= 0.3) & (hsv_image[:,:,2] >= 0.3)
        filtered_hues = hsv_image[:,:,0][mask] * 360  # Hueを0-360の範囲に変換

        # 条件2: ピックアップした画素が全体の15%以上を占めているか
        total_pixels = np_image.shape[0] * np_image.shape[1]
        print("pixel ratio",len(filtered_hues)/total_pixels)
        if len(filtered_hues) < 0.15 * total_pixels:
            return False

        # 条件1: ピックアップした画素のうちHueが前後20の範囲にあるものの占有率を調べ、70%以上であること
        hue_range_mask = ((filtered_hues >= input_hue - 20) & (filtered_hues <= input_hue + 20)) | \
                         ((filtered_hues + 360 >= input_hue - 20) & (filtered_hues + 360 <= input_hue + 20)) | \
                         ((filtered_hues - 360 >= input_hue - 20) & (filtered_hues - 360 <= input_hue + 20))
        print("hue ratio", np.sum(hue_range_mask)/len(filtered_hues))
        if np.sum(hue_range_mask) < 0.7 * len(filtered_hues):
            return False

        return True

    def insert_to_db(self, user_id, color_id, image_base64, posted_time):
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO posts (user_id, color_id, image, posted_time, rank) VALUES (%s, %s, %s, %s, 4)",
                (user_id, color_id, image_base64, posted_time)
            )
            self.connection.commit()

app = falcon.App()
app.add_route("/", AppResource(db_config))

if __name__ == "__main__":
    from wsgiref import simple_server
    httpd = simple_server.make_server("0.0.0.0", 8000, app)
    httpd.serve_forever()