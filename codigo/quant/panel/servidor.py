import argparse
import hmac
import secrets
import sqlite3
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from quant import rutas
from quant.panel import paginas

PORT = 20135
STATIC = Path(__file__).parent / "static"
TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}
PAGES = {"/propias": paginas.propias_page, "/": paginas.hoy, "/demo": paginas.demo, "/ranking": paginas.ranking, "/glosario": paginas.glosario}
CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self'"


def _connect(raiz):
    ruta = Path(raiz) / "catalogo.db"
    if not ruta.exists():
        con = sqlite3.connect(":memory:")
    else:
        con = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def make_server(raiz, port=PORT, sistema=None):
    raiz = Path(raiz)
    key = secrets.token_urlsafe(32)
    (raiz / "registro").mkdir(parents=True, exist_ok=True)
    (raiz / "registro" / "panel_clave").write_text(key, encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status, body=b"", ctype="text/html; charset=utf-8", cookie=None):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self._write_method()

        def do_DELETE(self):
            self._write_method()

        def _write_method(self):
            url, _, cookie = self._auth()
            if url is None:
                return self._send(403, "Acceso denegado", "text/plain; charset=utf-8")
            # Drain the body first: answering with it unread makes Windows reset the connection.
            self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 1 << 20))
            return self._send(405, "Método no permitido", "text/plain; charset=utf-8")

        def _auth(self):
            url = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            given = query.pop("key", None)
            jar = SimpleCookie(self.headers.get("Cookie", ""))
            cookie_key = jar["panel"].value if "panel" in jar else None
            via_query = given is not None and hmac.compare_digest(given.encode(), key.encode())
            via_cookie = cookie_key is not None and hmac.compare_digest(cookie_key.encode(), key.encode())
            host_ok = self.headers.get("Host", "").rsplit(":", 1)[0] in ("127.0.0.1", "localhost")
            if not host_ok or not (via_query or via_cookie):
                return None, None, None
            cookie = f"panel={key}; HttpOnly; SameSite=Strict; Path=/" if via_query else None
            return url, query, cookie

        def do_GET(self):
            url, query, cookie = self._auth()
            if url is None:
                return self._send(403, "Acceso denegado", "text/plain; charset=utf-8")
            path = url.path
            if path.startswith("/static/"):
                name = path[len("/static/"):]
                target = (STATIC / name).resolve()
                if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
                    return self._send(404, "No encontrado", "text/plain; charset=utf-8")
                return self._send(200, target.read_bytes(), TYPES.get(target.suffix, "application/octet-stream"), cookie)
            if path == "/sistema":
                self.send_response(302)
                self.send_header("Location", "/#sistema")
                self.send_header("Content-Length", "0")
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                self.end_headers()
                return
            query["_sistema"] = sistema
            con = _connect(raiz)
            try:
                if path in PAGES:
                    return self._send(200, PAGES[path](con, raiz, query), cookie=cookie)
                if path.startswith("/propias/") and path[len("/propias/"):].isdigit():
                    query["id"] = path[len("/propias/"):]
                    page = paginas.experimento(con, raiz, query)
                    if page is not None:
                        return self._send(200, page, cookie=cookie)
                if path.startswith("/estrategia/") and path[len("/estrategia/"):].isdigit():
                    query["id"] = path[len("/estrategia/"):]
                    page = paginas.estrategia(con, raiz, query)
                    if page is not None:
                        return self._send(200, page, cookie=cookie)
                return self._send(404, "No encontrado", "text/plain; charset=utf-8")
            except Exception as e:
                return self._send(500, f"Error interno: {type(e).__name__}", "text/plain; charset=utf-8")
            finally:
                con.close()

    return ThreadingHTTPServer(("127.0.0.1", port), Handler), key


def main(argv=None):
    p = argparse.ArgumentParser(description="Panel web de Quant (solo 127.0.0.1)")
    p.add_argument("--raiz", default=str(rutas.RAIZ))
    p.add_argument("--port", type=int, default=PORT)
    a = p.parse_args(argv)
    httpd, _ = make_server(Path(a.raiz), a.port)
    print(f"Panel en http://127.0.0.1:{httpd.server_address[1]}/ (clave en registro/panel_clave)", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
