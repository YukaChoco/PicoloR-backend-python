import json
import falcon

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

            # 欠けているフィールドがある場合はエラーを返す
            if not user_id or not color or not photo:
                raise ValueError("Missing required fields")

            msg = {
                "userID": user_id,
                "color": color,
                "photo": photo
            }
            resp.text = json.dumps(msg)
            resp.status = falcon.HTTP_200
        except json.JSONDecodeError:
            resp.text = json.dumps({"error": "Invalid JSON"})
            resp.status = falcon.HTTP_400
        except Exception as e:
            resp.text = json.dumps({"error": str(e)})
            resp.status = falcon.HTTP_400

app = falcon.App()
app.add_route("/", AppResource())

if __name__ == "__main__":
    from wsgiref import simple_server
    httpd = simple_server.make_server("0.0.0.0", 8000, app)
    httpd.serve_forever()