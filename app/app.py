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
            average_hue = self.get_average_hue(image)

            # 引数のカラーコードのHueと平均Hueを比較
            is_success = abs(input_hue - average_hue) <= 20

            # 成功レスポンス
            resp.media = {
                "is_success": "true" if is_success else "false",
                "input_hue": input_hue,
                "average_hue": average_hue
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

    def get_average_hue(self, image):
        # 画像をRGBからHSVに変換
        image = image.convert('RGB')
        np_image = np.array(image)
        hsv_image = np.apply_along_axis(lambda x: colorsys.rgb_to_hsv(x[0]/255.0, x[1]/255.0, x[2]/255.0), 2, np_image)
        
        # S >= 0.6 かつ V >= 0.7 のピクセルを抽出
        mask = (hsv_image[:,:,1] >= 0.6) & (hsv_image[:,:,2] >= 0.7)
        filtered_hues = hsv_image[:,:,0][mask] * 360  # Hueを0-360の範囲に変換

        if len(filtered_hues) == 0:
            raise ValueError("No pixels meet the criteria")

        # Hueの平均値を計算
        average_hue = np.mean(filtered_hues)
        return average_hue

app = falcon.App()
app.add_route("/", AppResource())

if __name__ == "__main__":
    from wsgiref import simple_server
    httpd = simple_server.make_server("0.0.0.0", 8000, app)
    httpd.serve_forever()