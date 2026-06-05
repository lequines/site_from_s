from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
import re
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = BASE_DIR / "index.html"
MAX_REQUEST_SIZE = 64 * 1024


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (key not in os.environ or not os.environ[key].strip()):
            os.environ[key] = value


load_dotenv(BASE_DIR / ".env")

HOST = os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1"
PORT = int(os.getenv("PORT", "8000"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
MAIL_FROM = os.getenv("MAIL_FROM", SMTP_USER).strip()
MAIL_TO = os.getenv("MAIL_TO", "").strip()
SMTP_USE_STARTTLS = os.getenv("SMTP_USE_STARTTLS", "0").strip() == "1"


def clean_line(value: str, limit: int = 200) -> str:
    return re.sub(r"\s+", " ", value.strip())[:limit]


def clean_comment(value: str, limit: int = 1200) -> str:
    return value.strip()[:limit]


def is_valid_phone(phone: str) -> bool:
    digits = re.sub(r"\D", "", phone)
    return 10 <= len(digits) <= 15 and not re.search(r"[^\d\s()+.-]", phone)


def parse_order_payload(headers, body: bytes) -> dict:
    content_type = headers.get("Content-Type", "")
    if "application/json" in content_type:
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Некорректный формат заявки.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Некорректный формат заявки.")
        return payload

    fields = parse_qs(body.decode("utf-8"))
    return {key: values[0] if values else "" for key, values in fields.items()}


def validate_order(payload: dict) -> dict:
    phone = clean_line(str(payload.get("phone", "")))
    email = clean_line(str(payload.get("email", "")))
    comment = clean_comment(str(payload.get("comment", "")))
    source = clean_line(str(payload.get("source", ""))) or "Форма заявки"

    if not phone and not email and not comment:
        raise ValueError("Заполните телефон, чтобы отправить заявку.")

    if not is_valid_phone(phone):
        raise ValueError("Укажите корректный телефон.")

    if email and ("@" not in email or "." not in email.rsplit("@", 1)[-1]):
        raise ValueError("Укажите корректный e-mail или оставьте поле пустым.")

    return {
        "phone": phone,
        "email": email,
        "comment": comment,
        "source": source,
    }


def format_order_message(order: dict) -> str:
    return "\n".join(
        [
            "Новая заявка с сайта",
            "",
            f"Телефон: {order['phone']}",
            "",
            f"E-mail: {order['email'] or '-'}",
            "",
            "Комментарий:",
            order["comment"] or "-",
            "",
            "Источник:",
            order["source"] or "Форма заявки",
        ]
    )


_LAST_WORKING_PROXY = None


def send_order_to_telegram(order: dict) -> None:
    global _LAST_WORKING_PROXY
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": format_order_message(order),
        },
        ensure_ascii=False,
    ).encode("utf-8")

    def try_send(proxy_url=None, timeout=5) -> bool:
        if proxy_url:
            proxy_handler = urllib.request.ProxyHandler({'https': f"http://{proxy_url}"})
        else:
            proxy_handler = urllib.request.ProxyHandler({})

        import ssl
        context = ssl._create_unverified_context()
        https_handler = urllib.request.HTTPSHandler(context=context)
        opener = urllib.request.build_opener(proxy_handler, https_handler)

        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with opener.open(req, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
                if result.get("ok"):
                    return True
        except Exception:
            pass
        return False

    # 1. Try direct connection first (short timeout)
    if try_send(timeout=3):
        return

    # 2. Try the last working proxy if cached
    if _LAST_WORKING_PROXY and try_send(_LAST_WORKING_PROXY, timeout=5):
        return

    # 3. Fetch fresh proxies from Proxyscrape
    proxies = []
    try:
        import ssl
        ctx = ssl._create_unverified_context()
        proxy_list_url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=1500&country=all&ssl=yes&anonymity=anonymous"
        req = urllib.request.Request(proxy_list_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
            proxies = r.read().decode('utf-8', errors='ignore').strip().split()
    except Exception:
        pass

    # 4. Try the fetched proxies
    for proxy in proxies:
        proxy = proxy.strip()
        if not proxy:
            continue
        if try_send(proxy, timeout=5):
            _LAST_WORKING_PROXY = proxy
            return

    raise RuntimeError("Failed to send order to Telegram.")


def send_optional_order_email(order: dict) -> None:
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD or not MAIL_TO:
        return

    message = EmailMessage()
    message["Subject"] = "Новая заявка с сайта"
    message["From"] = MAIL_FROM or SMTP_USER
    message["To"] = MAIL_TO
    if order["email"]:
        message["Reply-To"] = order["email"]
    message.set_content(format_order_message(order))

    context = ssl.create_default_context()
    if SMTP_USE_STARTTLS:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
        return

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=20) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(message)


def render_success_page() -> str:
    return """<!DOCTYPE html>
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
            <h1>Спасибо за интерес к оснащению объектов</h1>
            <p>Мы получили вашу заявку и свяжемся с вами по указанным контактам.</p>
            <a class="button button-primary" href="/">Вернуться на сайт</a>
        </section>
    </main>
</body>
</html>"""


class LandingHandler(BaseHTTPRequestHandler):
    timeout = 10.0

    def do_GET(self) -> None:
        request_path = urlparse(self.path).path

        if request_path in ("/", "/index.html"):
            self._send_html(INDEX_FILE.read_text(encoding="utf-8"))
            return

        if request_path.startswith("/static/"):
            self._send_static_file(request_path)
            return

        self.send_error(404, "Page not found")

    def do_POST(self) -> None:
        request_path = urlparse(self.path).path
        if request_path != "/order":
            self.send_error(404, "Page not found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > MAX_REQUEST_SIZE:
            self._send_json({"ok": False, "error": "Некорректный размер заявки."}, status=400)
            return

        try:
            raw_body = self.rfile.read(content_length)
            payload = parse_order_payload(self.headers, raw_body)
            order = validate_order(payload)
            email_sent = False
            try:
                send_optional_order_email(order)
                email_sent = True
            except Exception:
                pass

            try:
                send_order_to_telegram(order)
            except Exception as tg_exc:
                if not email_sent:
                    raise tg_exc
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        if "application/json" in self.headers.get("Accept", "") or "application/json" in self.headers.get("Content-Type", ""):
            self._send_json({"ok": True})
            return

        self._send_html(render_success_page())

    def _send_html(self, html: str) -> None:
        payload = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, data: dict, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_static_file(self, request_path: str) -> None:
        relative_path = unquote(request_path.removeprefix("/static/")).replace("/", os.sep)
        file_path = (STATIC_DIR / relative_path).resolve()
        static_root = STATIC_DIR.resolve()

        try:
            file_path.relative_to(static_root)
        except ValueError:
            self.send_error(403, "Forbidden")
            return

        content_type, _ = mimetypes.guess_type(file_path.name)
        self._send_file(file_path, content_type or "application/octet-stream")

    def _send_file(self, file_path: Path, content_type: str) -> None:
        if not file_path.is_file():
            self.send_error(404, "File not found")
            return

        payload = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), LandingHandler)
    print(f"Server started at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
