#!/usr/bin/env python3
"""
Controlled experiment for the DuckDB-WASM full-read finding.

Transparent reverse proxy to data.isamples.org that changes EXACTLY ONE THING:
a HEAD request carrying a Range header gets 206 + Content-Range instead of 200.

Everything else (GET, ranged GET, bodies, caching headers) is forwarded verbatim.
So if pointing the Explorer at this proxy makes the "falling back to full HTTP
read" behaviour disappear, the HEAD+Range response is the cause. If it does not,
the hypothesis is wrong and something else is triggering the fallback.

Run:   python range_fix_proxy.py [PORT] [--passthrough]
Use:   https://isamples.org/explorer.html?data_base=http://localhost:PORT
       (--passthrough disables the fix, giving the A-side control run)
"""
import sys, threading, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://data.isamples.org"
PASSTHROUGH = "--passthrough" in sys.argv
PORT = next((int(a) for a in sys.argv[1:] if a.isdigit()), 8099)

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Range",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges, ETag",
}

stats = {"HEAD": 0, "HEAD_ranged": 0, "HEAD_upgraded": 0, "GET": 0, "GET_ranged": 0}
lock = threading.Lock()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _upstream(self, method):
        url = UPSTREAM + self.path
        req = urllib.request.Request(url, method=method)
        # The data.isamples.org Worker 403s the default urllib User-Agent
        # (documented gotcha, 2026-07). Identify honestly as a proxy rather than
        # spoofing a browser.
        req.add_header("User-Agent",
                       "isamples-range-experiment/1.0 (local proxy; contact @rdhyee)")
        req.add_header("Accept", "*/*")
        rng = self.headers.get("Range")
        if rng:
            req.add_header("Range", rng)
        try:
            return urllib.request.urlopen(req, timeout=60), rng
        except urllib.error.HTTPError as e:
            return e, rng

    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in CORS.items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        resp, rng = self._upstream("HEAD")
        total = resp.headers.get("Content-Length")
        with lock:
            stats["HEAD"] += 1
            if rng:
                stats["HEAD_ranged"] += 1

        status = resp.status
        extra = {}
        # THE ONE CHANGE UNDER TEST.
        if rng and not PASSTHROUGH and status == 200 and total:
            try:
                spec = rng.split("=", 1)[1]
                start_s, _, end_s = spec.partition("-")
                start = int(start_s or 0)
                end = int(end_s) if end_s else int(total) - 1
                status = 206
                extra["Content-Range"] = f"bytes {start}-{end}/{total}"
                extra["Content-Length"] = str(end - start + 1)
                with lock:
                    stats["HEAD_upgraded"] += 1
            except Exception:
                status = resp.status

        self.send_response(status)
        for k, v in resp.headers.items():
            if k.lower() in ("content-length", "content-range", "transfer-encoding",
                             "connection", "access-control-allow-origin",
                             "access-control-expose-headers"):
                continue
            self.send_header(k, v)
        for k, v in extra.items():
            self.send_header(k, v)
        if "Content-Length" not in extra and total:
            self.send_header("Content-Length", total)
        for k, v in CORS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        resp, rng = self._upstream("GET")
        with lock:
            stats["GET"] += 1
            if rng:
                stats["GET_ranged"] += 1
        body = resp.read()
        self.send_response(resp.status)
        for k, v in resp.headers.items():
            if k.lower() in ("content-length", "transfer-encoding", "connection",
                             "access-control-allow-origin", "access-control-expose-headers"):
                continue
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        for k, v in CORS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    mode = "PASSTHROUGH (control)" if PASSTHROUGH else "HEAD+Range -> 206 (treatment)"
    print(f"proxy on :{PORT} -> {UPSTREAM}   mode={mode}", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print(f"stats: {stats}", flush=True)
