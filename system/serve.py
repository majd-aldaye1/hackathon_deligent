#!/usr/bin/env python3
"""Serve the analyst console:

    python3 system/run.py dev output/dev.jsonl --trace out/trace.json
    python3 system/serve.py [--port 8000] [--trace out/trace.json]   then open http://localhost:8000
"""
import argparse
import http.server
import os
import socketserver

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
ROUTES = {"/": os.path.join(ROOT, "ui/index.html"), "/index.html": os.path.join(ROOT, "ui/index.html")}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def translate_path(self, path):
        p = path.split("?", 1)[0].split("#", 1)[0]
        if p in ROUTES:
            return ROUTES[p]
        return super().translate_path(path)

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--trace", default=os.path.join(REPO, "out", "trace.json"))
    args = ap.parse_args()
    ROUTES["/trace.json"] = os.path.abspath(args.trace)
    if not os.path.exists(args.trace):
        print(f"{args.trace} not found — run: python3 system/run.py <data folder> output/dev.jsonl --trace out/trace.json")
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), Handler) as httpd:
        print(f"Namesake analyst console → http://localhost:{args.port}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
