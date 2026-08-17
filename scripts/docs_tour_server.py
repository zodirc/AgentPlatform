#!/usr/bin/env python3
"""Serve docs/ with long-cache headers for PNG diagrams."""
from __future__ import annotations

import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        path = self.path.split("?", 1)[0].split("#", 1)[0].lower()
        if path.endswith(".png"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        elif path.endswith("sw.js"):
            self.send_header("Cache-Control", "no-cache")
        elif path.endswith((".html", ".css", ".js", ".md")):
            self.send_header("Cache-Control", "public, max-age=120")
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
