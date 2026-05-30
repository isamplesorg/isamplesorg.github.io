#!/usr/bin/env python3
"""Range-capable static dev server for the explorer verify loop.

Stock `python3 -m http.server` (3.13) answers Range requests with 200 + the
full body, which makes DuckDB-WASM fall back to whole-file reads — the slow
path this repo has hit before. This server returns proper 206 Partial Content
so DuckDB-WASM can do real partial reads against a LOCAL parquet mirror, making
the cold verify loop seconds instead of 40-90s.

Usage:
    python3 dev_server.py                 # serves ./docs on :8099
    python3 dev_server.py --dir docs --port 8099

Then load the explorer against the local mirror under docs/data:
    http://localhost:8099/explorer.html?data_base=/data&debug=a1#v=1&lat=...

Verify Range actually works (must be 206, not 200):
    curl -r 0-99 -i http://localhost:8099/data/isamples_202601_samples_map_lite.parquet
"""
import argparse
import http.server
import os
import re


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    # DuckDB-WASM's httpfs range reader expects HTTP/1.1 (keep-alive +
    # persistent connections for its many small footer/row-group range GETs).
    # Python's http.server defaults to HTTP/1.0, under which DuckDB falls back
    # to whole-file GET 200s — so the local mirror never exercises the 206
    # range path that production (Cloudflare R2, HTTP/2) uses. Pin 1.1.
    protocol_version = "HTTP/1.1"

    def end_headers(self):
        # CORS + always-Accept-Ranges so a cross-origin data_base also works.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Range")
        self.send_header("Access-Control-Expose-Headers",
                         "Content-Length, Content-Range, Accept-Ranges, ETag")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if rng and os.path.isfile(path):
            m = re.match(r"bytes=(\d*)-(\d*)\s*$", rng)
            if m:
                size = os.path.getsize(path)
                start = int(m.group(1)) if m.group(1) else 0
                end = int(m.group(2)) if m.group(2) else size - 1
                end = min(end, size - 1)
                if start > end:
                    self.send_error(416, "Requested Range Not Satisfiable")
                    return
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", self.guess_type(path))
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(length))
                self.end_headers()
                with open(path, "rb") as f:
                    f.seek(start)
                    self.wfile.write(f.read(length))
                return
        super().do_GET()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="docs")
    ap.add_argument("--port", type=int, default=8099)
    args = ap.parse_args()
    os.chdir(args.dir)
    httpd = http.server.ThreadingHTTPServer(("", args.port), RangeHandler)
    print(f"Range-capable dev server: http://localhost:{args.port} (serving ./{args.dir})")
    print("  Range check: curl -r 0-99 -i "
          f"http://localhost:{args.port}/data/isamples_202601_samples_map_lite.parquet")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
