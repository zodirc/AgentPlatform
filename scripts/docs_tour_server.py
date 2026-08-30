#!/usr/bin/env python3
"""Serve docs/ for make docs-tour (local preview).

Prefer fresh HTML/JS so chapter edits show up on reload. PNGs use short
revalidation — Service Worker (docs/sw.js) must not cache-first forever.
"""
from __future__ import annotations

import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        path = self.path.split("?", 1)[0].split("#", 1)[0].lower()
        if path.endswith("sw.js"):
            # Always revalidate SW so cache strategy bumps take effect.
            self.send_header("Cache-Control", "no-cache")
        elif path.endswith(".png"):
            # Allow brief reuse, but force revalidate (ETag/Last-Modified).
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        elif path.endswith((".html", ".css", ".js", ".md", ".json")):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> None:
    root = os.path.dirname(os.path.abspath(__file__))
    docs = os.path.normpath(os.path.join(root, "..", "docs"))
    os.chdir(docs)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
