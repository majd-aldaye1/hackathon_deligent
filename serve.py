#!/usr/bin/env python3
"""Serve the analyst console:  python3 serve.py [--port 8000]  then open http://localhost:8000"""
import argparse
import http.server
import os
import socketserver

ROOT = os.path.dirname(os.path.abspath(__file__))
ROUTES = {"/": "ui/index.html", "/index.html": "ui/index.html", "/trace.json": "out/trace.json"}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def translate_path(self, path):
        p = path.split("?", 1)[0].split("#", 1)[0]
        if p in ROUTES:
            return os.path.join(ROOT, ROUTES[p])
        return super().translate_path(path)

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    if not os.path.exists(os.path.join(ROOT, "out/trace.json")):
        print("out/trace.json not found — run: python3 run.py --data dataset")
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), Handler) as httpd:
        print(f"Namesake analyst console → http://localhost:{args.port}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
