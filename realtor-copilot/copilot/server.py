"""표준 라이브러리 HTTP API 서버.

POST /api/score   JSON 요청 → 순위·점수·진단 JSON
POST /api/report  JSON 요청 → 리포트 HTML
GET  /api/weights/keywords → 선택 가능한 키워드 목록
GET  /demo/<n>    샘플 고객 n(0부터)의 리포트 HTML
GET  /healthz
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import weights as W
from .service import CopilotService, build_preference


def make_handler(svc: CopilotService):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body, ctype="application/json; charset=utf-8"):
            data = body.encode() if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            if self.path == "/healthz":
                return self._send(200, {"ok": True})
            if self.path == "/api/weights/keywords":
                return self._send(200, {"keywords": list(W.KEYWORD_BOOSTS)})
            if self.path.startswith("/demo/"):
                try:
                    c = svc.store.preferences()[int(self.path.split("/")[2])]
                except (ValueError, IndexError):
                    return self._send(404, {"error": "not found"})
                pref = build_preference(c["customer_name"], c["work_address"], c.get("weights"), c.get("keywords"))
                return self._send(200, svc.html(pref), "text/html; charset=utf-8")
            self._send(404, {"error": "not found"})

        def do_POST(self):
            try:
                req = self._body()
                if self.path == "/api/score":
                    return self._send(200, svc.score_json(req))
                if self.path == "/api/report":
                    pref = build_preference(req["customer_name"], req["work_address"],
                                            req.get("weights"), req.get("keywords"))
                    return self._send(200, svc.html(pref, property_ids=req.get("property_ids")),
                                      "text/html; charset=utf-8")
                self._send(404, {"error": "not found"})
            except (KeyError, ValueError, LookupError, json.JSONDecodeError) as e:
                self._send(400, {"error": f"{type(e).__name__}: {e}"})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8000, use_claude: bool = False):
    svc = CopilotService(use_claude=use_claude)
    httpd = ThreadingHTTPServer((host, port), make_handler(svc))
    print(f"Realtor Co-Pilot API on http://{host}:{port}  (demo: /demo/0)")
    httpd.serve_forever()
