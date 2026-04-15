from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = BASE_DIR / "index.html"
HOST = "127.0.0.1"
PORT = 8000


def render_success_page(name: str) -> str:
    customer_name = name.strip() or "Ваше имя"
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Заявка получена</title>
    <link rel="stylesheet" href="/static/styles.css">
</head>
<body class="success-body">
    <main class="success-shell">
        <section class="success-card">
            <p class="eyebrow">Заявка отправлена</p>
            <h1>{customer_name}, спасибо за интерес к коллекции</h1>
            <p>
                Мы получили вашу заявку и свяжемся с вами по указанным контактам.
                Пока можно вернуться на главную и продолжить знакомство с ассортиментом.
            </p>
            <a class="button button-primary" href="/">Вернуться на сайт</a>
        </section>
    </main>
</body>
</html>"""


class LandingHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send_html(INDEX_FILE.read_text(encoding="utf-8"))
            return

        if self.path == "/static/styles.css":
            css_file = STATIC_DIR / "styles.css"
            self._send_file(css_file, "text/css; charset=utf-8")
            return

        self.send_error(404, "Page not found")

    def do_POST(self) -> None:
        if self.path != "/order":
            self.send_error(404, "Page not found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        form_data = self.rfile.read(content_length).decode("utf-8")
        fields = parse_qs(form_data)
        name = fields.get("name", [""])[0]
        phone = fields.get("phone", [""])[0]
        email = fields.get("email", [""])[0]
        comment = fields.get("comment", [""])[0]

        print(
            "New order request:",
            {
                "name": name,
                "phone": phone,
                "email": email,
                "comment": comment,
            },
        )

        self._send_html(render_success_page(name))

    def _send_html(self, html: str) -> None:
        payload = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, file_path: Path, content_type: str) -> None:
        if not file_path.exists():
            self.send_error(404, "File not found")
            return

        payload = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    server = HTTPServer((HOST, PORT), LandingHandler)
    print(f"Server started at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
