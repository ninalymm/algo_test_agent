"""零依赖 Web Chat：stdlib http.server + 原生 JS。

启动：
    python3 -m web.server            # http://127.0.0.1:8000
    python3 -m web.server --port 9000
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
sys.path.insert(0, str(ROOT))

from observe import tracing  # noqa: E402
from skills import router  # noqa: E402
from store.db import connect  # noqa: E402
from store.seed import seed  # noqa: E402
from store import repo  # noqa: E402

CONN = None
SESSIONS: dict = {}


class Server(ThreadingHTTPServer):
    """跳过 HTTPServer.server_bind 里的 getfqdn 反查。

    默认实现会在绑定端口时做一次反向 DNS，网络不通时会卡住几十秒。
    """

    def server_bind(self):
        import socketserver
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默

    # ---------- helpers ----------
    def _session(self, payload: dict) -> dict:
        sid = payload.get("session_id") or "default"
        return SESSIONS.setdefault(sid, {})

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, ctype: str):
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------- routes ----------
    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/":
            return self._file(STATIC / "index.html", "text/html; charset=utf-8")
        if p.startswith("/static/"):
            f = STATIC / p[len("/static/"):]
            ctype = "text/css" if f.suffix == ".css" else "application/javascript"
            return self._file(f, ctype + "; charset=utf-8")
        if p == "/api/tasks":
            rows = [{"id": r["id"], "scene": r["scene_id"], "ts": r["ts"],
                     "change": r["change_id"]} for r in repo.list_tasks(CONN, 20)]
            return self._json({"tasks": rows})
        if p.startswith("/api/trace/"):
            tid = p.rsplit("/", 1)[-1]
            spans = repo.spans_of_trace(CONN, tid)
            return self._json({"trace_id": tid, "spans": spans})
        self.send_error(404)

    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/api/chat":
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
            msg = (payload.get("message") or "").strip()
            if not msg:
                return self._json({"reply": "说点什么吧。", "card": None})
            try:
                result = router.route(CONN, msg, self._session(payload),
                                      payload.get('session_id') or 'default')
            except Exception as e:  # 不让异常打断会话
                return self._json({"reply": f"处理出错：{e}", "card": None, "intent": "error"})
            return self._json(result)
        if p == "/api/execute":
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
            from skills import run as run_skill, selftest
            plan = payload.get("plan") or {}
            try:
                if "change" in plan:
                    return self._json(selftest.execute(CONN, plan))
                return self._json(run_skill.execute(CONN, plan))
            except Exception as e:
                return self._json({"reply": f"执行出错：{e}", "card": None}, 500)
        self.send_error(404)


def main():
    global CONN
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--init-db", action="store_true", help="重建样例数据")
    args = ap.parse_args()

    if args.init_db:
        seed()
    CONN = connect()
    if not repo.list_tasks(CONN, 1):
        seed()
        CONN = connect()

    st = tracing.setup()
    srv = Server(("127.0.0.1", args.port), Handler)
    print(f"chat ui  →  http://127.0.0.1:{args.port}")
    if st["enabled"]:
        print(f"langsmith →  已启用（project={st['project']}）")
    else:
        reason = "未设置 key" if not st["key_present"] else "开关关闭（LANGSMITH_ENABLED=false）"
        print(f"langsmith →  未启用（{reason}）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
