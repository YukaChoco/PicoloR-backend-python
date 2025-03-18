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
import cv2
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
                room_id = data.get("roomID")
                image_base64 = data.get("image")

                if user_id is None or color_id is None or room_id is None or image_base64 is None:
                    raise ValueError("Missing required fields")

                # 日本時間の現在時間を取得(日本時間)
                posted_at = datetime.datetime.now()
                start_at = self.get_start_at(color_id)

                # 結果をテキストとしてフォーマット
                posted_time = self.get_posted_time(start_at, posted_at)

                # Base64エンコードされた画像データをデコードしてPillowで読み込む
                image_data = io.BytesIO(base64.b64decode(image_base64))
                image = Image.open(image_data)

                # テスト用のカラーコード
                color = self.get_theme_color(color_id)

                # 入力カラーコードをHSV空間に変換し、Hueを取り出す
                input_hue = self.hex_to_hue(color)

                print("input_hue", input_hue)

                # 画像をHSV空間に変換し、条件を満たすピクセルのHueの平均値を計算
                is_success = self.check_image_hue(image, input_hue)

                # DBにPostgresqlでデータを追加
                if is_success:
                    can_insert_to_db = self.can_insert_to_db(color_id)
                    if can_insert_to_db:
                        rank = self.get_rank_for_color_id(color_id)  # rankを取得
                        self.insert_to_db(user_id, color_id, image_base64, posted_time, rank, room_id)
                        resp.media = {
                            "is_success": True,
                            "rank": rank
                        }
                    else:
                        resp.media = {
                            "is_success": False,
                            "error": "この色は既に投稿されています！"
                        }
                else:
                    resp.media = {
                        "is_success": False,
                        "error": "画像の色がテーマカラーと一致していません！"
                    }

                # 成功レスポンス
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

    def get_start_at(self, room_id):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT start_at FROM rooms WHERE id = %s",
                (room_id,)
            )
            result = cursor.fetchall()
            if len(result) == 0:
                raise ValueError("Room not found")
            if result[0][0] is None:
                raise ValueError("Room has not started yet")
            return result[0][0]
        except Exception as e:
            raise e
        finally:
            cursor.close()


    def get_posted_time(self, start_at, posted_at):
        if start_at.tzinfo is not None:
            start_at = start_at.replace(tzinfo=None)
        elapsed_time = posted_at - start_at
        minutes, seconds = divmod(int(elapsed_time.total_seconds()), 60)
        return f"{minutes}:{seconds:02d}"

    def get_theme_color(self, color_id):
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT color FROM room_colors WHERE id = %s",
                (color_id,)
            )
            result = cursor.fetchall()
            if len(result) == 0:
                raise ValueError("Color not found")
            return result[0][0]
        except Exception as e:
            raise e
        finally:
            cursor.close()


    def hex_to_hue(self, hex_color):
        # 16進数カラーコードをHSVに変換
        hex_color = hex_color.lstrip('#')
        hsv = colorsys.rgb_to_hsv(int(hex_color[:2], 16) / 255, int(hex_color[2:4], 16) / 255, int(hex_color[4:], 16) / 255)
        return hsv[0] * 360  # Hueを0-360の範囲に変換

    def check_image_hue(self, image, input_hue):
        # 画像をRGBからHSVに変換
        print("check_image_hue start")
        image = image.convert('RGB')
        np_image = np.array(image)
        hsv_image = cv2.cvtColor(np_image, cv2.COLOR_RGB2HSV)


        print("check_image_hue hsv get")
        # S >= 0.3 かつ V >= 0.3 のピクセルを抽出
        mask = (hsv_image[:,:,1] >= 0.3 * 255) & (hsv_image[:,:,2] >= 0.3 * 255)
        filtered_hues = hsv_image[:,:,0][mask]  # Hueを0-360の範囲に変換

        print("check_image_hue mask get")

        # 条件2: ピックアップした画素が全体の15%以上を占めているか
        total_pixels = np_image.shape[0] * np_image.shape[1]
        print("[pixel ratio]", len(filtered_hues) / total_pixels)
        if len(filtered_hues) < 0.3 * total_pixels:
            return False

        print("input fue", input_hue)
        half_input_hue = np.int32(input_hue / 2)
        filtered_hues = filtered_hues.astype(np.int32)
        # print("half_input_hue", half_input_hue)
        # print("filtered_hues", filtered_hues)

        hue_range_mask = ((filtered_hues >= half_input_hue - 30) & (filtered_hues <= half_input_hue + 30)) | \
                        ((filtered_hues + 180 >= half_input_hue - 30) & (filtered_hues + 180 <= half_input_hue + 30)) | \
                        ((filtered_hues - 180 >= half_input_hue - 30) & (filtered_hues - 180 <= half_input_hue + 30))
        print("all pixels:", total_pixels,", hue_range_mask:", np.sum(hue_range_mask), "filtered_hues:", len(filtered_hues))
        print("[hue ratio]", np.sum(hue_range_mask) / len(filtered_hues))
        if np.sum(hue_range_mask) < 0.3 * len(filtered_hues):
            return False

        return True

    def get_rank_for_color_id(self, color_id):
        cursor = self.connection.cursor()
        try:
            cursor.execute("""
                WITH color_count AS (
                    SELECT COUNT(*) AS count
                    FROM posts
                    WHERE color_id = %s
                )
                SELECT COALESCE(color_count.count, 0) + 1 AS rank
                FROM color_count
            """, (color_id,))

            # rankを取得
            current_winner_count = cursor.fetchone()
            print("current_winner_count",current_winner_count)
            if current_winner_count is None:
                raise ValueError("Failed to fetch the current winner count from the database")
            next_rank = current_winner_count[0] + 1
            print("next_rank",next_rank)
            return next_rank
        except Exception as e:
            raise e
        finally:
            cursor.close()



    def can_insert_to_db(self, color_id):
        cursor = self.connection.cursor()
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM posts WHERE color_id = %s
            """, (color_id,))
            result = cursor.fetchone()
            if result is None:
                raise ValueError("Failed to fetch the count from the database")

            can_post = result[0] == 0
            if not can_post:
                return False

            return True
        except Exception as e:
            raise e
        finally:
            cursor.close()


    def insert_to_db(self, user_id, color_id, image_base64, posted_time, rank, room_id):
        cursor = self.connection.cursor()
        try:
            cursor.execute("""
                INSERT INTO posts (user_id, color_id, image, posted_time, rank, room_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_id, color_id, image_base64, posted_time, rank, room_id,))
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise e
        finally:
            cursor.close()


class ThemeColorResource(object):
    def __init__(self,db_config:DbConfig) ->None:
        self.connection = psycopg2.connect(
            dbname=db_config.dbname,
            user=db_config.user,
            password=db_config.password,
            host=db_config.host,
            port=db_config.port
        )

    def on_get(self, req, resp):
        try:
            room_id = req.get_param("roomID")
            room_id_int = int(room_id)

            if room_id_int is None:
                raise ValueError("Missing required fields")

            res = self.get_user_count(room_id_int)

            if res["is_success"]:
                user_count = res["user_count"]

                theme_colors = self.get_theme_colors(user_count)

                self.insert_to_db(room_id_int, theme_colors)

                # 成功レスポンス
                resp.media = {
                    "themeColors": theme_colors
                }
                resp.status = falcon.HTTP_200
            else:
                resp.media = {
                    "error": res["error"]
                }
                resp.status = falcon.HTTP_400

        except json.JSONDecodeError:
            resp.text = json.dumps({"error": "Invalid JSON"})
            resp.status = falcon.HTTP_400
        except Exception as e:
            # 詳細なエラーメッセージをログに出力
            print(f"Error: {str(e)}")
            resp.text = json.dumps({"error": str(e)})
            resp.status = falcon.HTTP_500

    def get_user_count(self, room_id):
        cursor = self.connection.cursor()
        try:
            # room_idが存在するか確認
            cursor.execute(
                "SELECT id FROM rooms WHERE id = %s",
                (room_id,)
            )
            result = cursor.fetchall()
            if len(result) == 0:
                return {
                    "is_success": False,
                    "error": "Room not found"
                }

            cursor.execute(
                "SELECT COUNT(*) FROM room_members WHERE room_id = %s",
                (room_id,)
            )
            result = cursor.fetchall()
            if len(result) == 0 or result[0][0] is None:
                return {
                    "is_success": False,
                    "error": "Room has not enough members"
                }
            user_count = result[0][0]
            if user_count < 2:
                return {
                    "is_success": False,
                    "error": "Room has not enough members"
                    }
            return {
                "is_success": True,
                "user_count": user_count
            }
        except Exception as e:
            raise e
        finally:
            cursor.close()


    def get_theme_colors(self, user_count):
        # ランダムでテーマカラーを生成
        theme_colors = []
        theme_hues = []
        first_color_hue = np.random.rand()
        theme_hues.append(first_color_hue)
        if user_count == 3:
            theme_hues.append((first_color_hue - 0.4) % 1)
        elif user_count >= 4:
            theme_hues.append((first_color_hue - 0.4) % 1)
            theme_hues.append((first_color_hue + 0.3) % 1)
        for hue in theme_hues:
            rgb = colorsys.hsv_to_rgb(hue, 1, 1)
            hex_color = '#%02x%02x%02x' % tuple(int(x * 255) for x in rgb)
            theme_colors.append(hex_color)
        return theme_colors

    def insert_to_db(self, room_id_int, colors):
        cursor = self.connection.cursor()
        try:
            insertData = []
            for color in colors:
                insertData.append((room_id_int, color))


            values_str = ", ".join([f"({room_id}, '{color}')" for room_id, color in insertData])
            print("insertData",insertData)
            print("values_str",values_str)

            sql = f"INSERT INTO room_colors (room_id, color) VALUES {values_str};"

            try:
                cursor.execute(sql)
                self.connection.commit()
            except Exception as e:
                self.connection.rollback()
                raise e
        except Exception as e:
            raise e
        finally:
            cursor.close()

app = falcon.App(
    cors_enable=True
)
app.add_route("/controller/image", AppResource(db_config))
app.add_route("/host/theme_color", ThemeColorResource(db_config))

if __name__ == "__main__":
    from wsgiref import simple_server
    httpd = simple_server.make_server("0.0.0.0", 8000, app)
    httpd.serve_forever()