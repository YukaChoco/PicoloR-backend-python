import json
import falcon

class AppResource(object):

    def on_get(self, req, resp):
        msg = {
            "message": "Welcome to the Falcon!!"
        }
        resp.text = json.dumps(msg)

app = falcon.App()
app.add_route("/", AppResource())

if __name__ == "__main__":
    from wsgiref import simple_server
    httpd = simple_server.make_server("0.0.0.0", 8000, app)
    httpd.serve_forever()