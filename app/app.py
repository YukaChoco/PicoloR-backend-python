import json
import falcon
from PIL import Image
import io
import base64

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

            # 画像の色を判定する処理（簡単な例として、画像の色をチェックする）
            is_color_match = self.check_image_color(image, color)

            # 成功レスポンス
            resp.media = {
                "is_success": "true" if is_color_match else "false",
                "rank": 1 if is_color_match else 0
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

    def check_image_color(self, image, color):
        # 簡単な色判定例（画像の中央ピクセルを判定）
        width, height = image.size
        central_pixel = image.getpixel((width // 2, height // 2))

        # 色の判定（単純な例: RGB の一致）
        if color == "red" and central_pixel[0] > central_pixel[1] and central_pixel[0] > central_pixel[2]:
            return True
        return False

app = falcon.App()
app.add_route("/", AppResource())

if __name__ == "__main__":
    from wsgiref import simple_server
    httpd = simple_server.make_server("0.0.0.0", 8000, app)
    httpd.serve_forever()