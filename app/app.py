import json
import falcon
from PIL import Image
import io
import base64
import colorsys
import numpy as np

class AppResource(object):

    def on_get(self, req, resp):
        msg = {
            "message": "Welcome to the Falcon!!"
        }
        resp.text = json.dumps(msg)
        resp.status = falcon.HTTP_200

    def on_post(self, req, resp):
        try:
            raw_json = req.bounded_stream.read()
            if not raw_json:
                raise ValueError("Empty request body")

            data = json.loads(raw_json)
            user_id = data.get("userID")
            color = data.get("color")
            photo = data.get("photo")

            if user_id is None or color is None or photo is None:
                raise ValueError("Missing required fields")

            # Base64エンコードされた画像データをデコードしてPillowで読み込む
            image_data = io.BytesIO(base64.b64decode(photo))
            image = Image.open(image_data)

            # 入力カラーコードをHSV空間に変換し、Hueを取り出す
            input_hue = self.hex_to_hue(color)

            # 画像をHSV空間に変換し、条件を満たすピクセルのHueの平均値を計算
            is_success = self.check_image_hue(image, input_hue)

            # 成功レスポンス
            resp.media = {
                "is_success": "true" if is_success else "false"
            }
            resp.status = falcon.HTTP_200
        except json.JSONDecodeError:
            resp.text = json.dumps({"error": "Invalid JSON"})
            resp.status = falcon.HTTP_400
        except Exception as e:
            # 詳細なエラーメッセージをログに出力
            print(f"Error: {str(e)}")
            resp.text = json.dumps({"error": str(e)})
            resp.status = falcon.HTTP_500

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
        print(len(filtered_hues)/total_pixels)
        if len(filtered_hues) < 0.15 * total_pixels:
            return False

        # 条件1: ピックアップした画素のうちHueが前後20の範囲にあるものの占有率を調べ、70%以上であること
        hue_range_mask = ((filtered_hues >= input_hue - 20) & (filtered_hues <= input_hue + 20)) | \
                         ((filtered_hues + 360 >= input_hue - 20) & (filtered_hues + 360 <= input_hue + 20)) | \
                         ((filtered_hues - 360 >= input_hue - 20) & (filtered_hues - 360 <= input_hue + 20))
        print(np.sum(hue_range_mask)/len(filtered_hues))
        if np.sum(hue_range_mask) < 0.7 * len(filtered_hues):
            return False

        return True

app = falcon.App()
app.add_route("/", AppResource())

if __name__ == "__main__":
    from wsgiref import simple_server
    httpd = simple_server.make_server("0.0.0.0", 8000, app)
    httpd.serve_forever()