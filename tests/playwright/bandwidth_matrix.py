#!/usr/bin/env python3
"""
#313-lite — measure the Interactive Explorer across network profiles and viewports.

Answers two open questions at once:

  #313 (Andrea, open since 2026-06-26, never done): what browser / OS / bandwidth
        combinations does the Explorer actually work in?

  The "falling back to full HTTP read" finding (2026-08-05): DuckDB-WASM logs that
        it is NOT using HTTP range requests for eight files, including the 63 MB
        map-lite parquet — which contradicts the architecture's central claim that
        only the bytes you need are transferred. The server was already ruled out
        (HEAD 200 + accept-ranges, ranged GET 206, CORS preflight allows Range), so
        this measures what the CLIENT actually does.

Design notes:
  * Byte accounting uses CDP Network.loadingFinished `encodedDataLength`, which is
    real bytes on the wire (post-compression), not decoded size.
  * Every run gets a fresh browser context => cold HTTP cache. This is the honest
    first-visit case and the one a reviewer or a new user experiences.
  * Runs are budgeted. A run that does not reach a milestone inside the budget is
    recorded as NOT REACHED rather than being retried or waited out — "the globe
    never appeared within 3 minutes on slow 3G" is a finding, not a failure.

Usage:
    python bandwidth_matrix.py [BASE_URL] [--budget SECONDS] [--profiles a,b]
"""
import argparse, json, statistics, sys, time
from playwright.sync_api import sync_playwright

# Chrome DevTools-style presets. Values are bytes/sec and milliseconds.
PROFILES = {
    "unthrottled": dict(download=-1, upload=-1, latency=0),
    "4g":          dict(download=4_000_000 / 8, upload=3_000_000 / 8, latency=20),
    "3g-fast":     dict(download=1_600_000 / 8, upload=750_000 / 8,   latency=300),
    "3g-slow":     dict(download=400_000 / 8,   upload=400_000 / 8,   latency=2000),
}

VIEWPORTS = {
    "desktop": dict(width=1440, height=900),
    "mobile":  dict(width=390,  height=844),   # iPhone 14-ish
}

MILESTONES = ("cesium_canvas", "globe_drawn", "facet_trees", "table_rows")


def probe(page):
    """Return which milestones have been reached. Cheap; polled."""
    return page.evaluate("""() => {
        const c = document.querySelector('.cesium-viewer .cesium-widget canvas');
        const box = c ? c.getBoundingClientRect() : null;
        return {
            cesium_canvas: !!c,
            globe_drawn:   !!(box && box.width > 0 && box.height > 0),
            facet_trees:   document.querySelectorAll('.facet-treenode').length > 0,
            table_rows:    document.querySelectorAll('#samplesTable tbody tr, table tbody tr').length > 0,
        };
    }""")


def run_one(pw, base_url, profile_name, viewport_name, budget_s, query="", browser_name="chromium"):
    prof = PROFILES[profile_name]
    vp = VIEWPORTS[viewport_name]

    engine = {'chromium': pw.chromium, 'firefox': pw.firefox, 'webkit': pw.webkit}[browser_name]
    browser = engine.launch()
    ctx = browser.new_context(viewport=vp)          # fresh context => cold cache
    page = ctx.new_page()

    # CDP (and therefore network throttling) is chromium-only. Firefox/WebKit runs
    # are unthrottled by construction; the harness records that rather than
    # pretending the profile was applied.
    cdp = None
    throttled = False
    if browser_name == "chromium":
        cdp = ctx.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", {
            "offline": False,
            "downloadThroughput": prof["download"],
            "uploadThroughput": prof["upload"],
            "latency": prof["latency"],
        })
        throttled = profile_name != "unthrottled"

    # --- wire-level accounting -------------------------------------------------
    # CRITICAL: DuckDB-WASM runs in a Web Worker, and a page-level CDP session does
    # NOT see worker network traffic. Measuring only the page session reports ~568 KB
    # and 3 requests (just the main-frame <link rel=preload> hits) — which looks like
    # a textbook "only the bytes you need" result and is completely wrong. We must
    # auto-attach to workers and enable Network on each of their sessions too.
    req_url, status_by_id, bytes_by_id = {}, {}, {}
    console_errors, page_errors, fallback_logs = [], [], []
    worker_sessions = []

    def on_req(p):
        req_url[p["requestId"]] = p["request"]["url"]

    def on_resp(p):
        req_url[p["requestId"]] = p["response"]["url"]
        status_by_id[p["requestId"]] = p["response"]["status"]

    def on_done(p):
        bytes_by_id[p["requestId"]] = p.get("encodedDataLength", 0)

    def wire(sess):
        sess.on("Network.requestWillBeSent", on_req)
        sess.on("Network.responseReceived", on_resp)
        sess.on("Network.loadingFinished", on_done)

    if cdp: wire(cdp)

    def on_attached(params):
        """Attach to each worker target and mirror the Network domain onto it."""
        try:
            sid = params["sessionId"]
            ws = cdp.session(sid) if hasattr(cdp, "session") else None
            if ws is None:
                return
            worker_sessions.append(ws)
            wire(ws)
            ws.send("Network.enable")
            # Throttling is per-session; workers need their own emulation or they
            # would download at full speed while the page is throttled.
            ws.send("Network.emulateNetworkConditions", {
                "offline": False,
                "downloadThroughput": prof["download"],
                "uploadThroughput": prof["upload"],
                "latency": prof["latency"],
            })
            ws.send("Runtime.runIfWaitingForDebugger")
        except Exception as e:
            fallback_logs.append(f"[worker-attach-failed] {e}")

    if cdp: cdp.on("Target.attachedToTarget", on_attached)
    try:
        if not cdp: raise RuntimeError("no cdp (non-chromium)")
        # waitForDebuggerOnStart MUST be False. With True, workers are paused at
        # start and — unless every one is explicitly resumed — DuckDB-WASM never
        # boots, so the globe and facets never render. That is the instrument
        # changing the measurement: an earlier run reported globe=None purely
        # because of this flag.
        cdp.send("Target.setAutoAttach", {
            "autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True,
        })
    except Exception as e:
        fallback_logs.append(f"[autoattach-failed] {e}")

    # Real accounting happens here, via PASSIVE context-level request events, which
    # (unlike a page-scoped CDP Network domain) do observe dedicated-worker traffic.
    #
    # Deliberately passive: an earlier version used ctx.route(...)+continue_() and
    # the interception round-trip inflated time-to-globe from 2.5s to 7.3s. The
    # instrument must not distort the timings it is reporting.
    route_hits = {}

    def on_finished(request):
        u = request.url
        # Match the real data host OR a local proxy standing in for it (used by the
        # range-request A/B experiment), so both arms are measured identically.
        if not (("data.isamples.org" in u) or ("localhost" in u and ".parquet" in u)
                or ("127.0.0.1" in u and ".parquet" in u)):
            return
        name = u.rsplit("/", 1)[-1].split("?")[0]
        e = route_hits.setdefault(
            name, {"requests": 0, "with_range_header": 0, "response_bytes": 0, "statuses": {}})
        e["requests"] += 1
        if "range" in {k.lower() for k in request.headers}:
            e["with_range_header"] += 1
        # sizes() returns -1 when Playwright cannot determine a body size (small /
        # cached / redirected responses). Clamp to 0 and count the occurrences
        # rather than letting negatives silently offset real totals — an earlier
        # version reported -885 bytes for a file, which is obviously not a size.
        try:
            n = request.sizes().get("responseBodySize", 0)
            if n is None or n < 0:
                e["unknown_size_responses"] = e.get("unknown_size_responses", 0) + 1
            else:
                e["response_bytes"] += n
        except Exception:
            e["unknown_size_responses"] = e.get("unknown_size_responses", 0) + 1
        try:
            r = request.response()
            if r:
                e["statuses"][str(r.status)] = e["statuses"].get(str(r.status), 0) + 1
        except Exception:
            pass

    ctx.on("requestfinished", on_finished)

    page.on("console", lambda m: (
        console_errors.append(m.text[:200]) if m.type == "error" else
        fallback_logs.append(m.text[:200]) if "full HTTP read" in (m.text or "") else None))
    page.on("pageerror", lambda e: page_errors.append(str(e)[:200]))

    # --- run -------------------------------------------------------------------
    reached, t0 = {}, time.time()
    try:
        page.goto(f"{base_url}/explorer.html{query}", wait_until="commit", timeout=budget_s * 1000)
    except Exception as e:
        reached["_goto_error"] = str(e)[:160]

    while time.time() - t0 < budget_s:
        try:
            st = probe(page)
        except Exception:
            time.sleep(1); continue
        for k in MILESTONES:
            if st.get(k) and k not in reached:
                reached[k] = round(time.time() - t0, 1)
        if all(k in reached for k in MILESTONES):
            break
        time.sleep(1)

    elapsed = round(time.time() - t0, 1)

    # --- aggregate -------------------------------------------------------------
    per_file, total = {}, 0
    ranged = partial = full = 0
    for rid, url in req_url.items():
        n = bytes_by_id.get(rid, 0)
        total += n
        st = status_by_id.get(rid)
        if "data.isamples.org" in url:
            name = url.rsplit("/", 1)[-1].split("?")[0]
            e = per_file.setdefault(name, {"requests": 0, "bytes": 0, "statuses": {}})
            e["requests"] += 1
            e["bytes"] += n
            e["statuses"][str(st)] = e["statuses"].get(str(st), 0) + 1
            if st == 206: ranged += 1
            elif st == 200: full += 1
            else: partial += 1

    ctx.close(); browser.close()

    return {
        "browser": browser_name,
        "throttling_applied": throttled,
        "profile": profile_name,
        "viewport": viewport_name,
        "budget_s": budget_s,
        "elapsed_s": elapsed,
        "milestones": {k: reached.get(k, None) for k in MILESTONES},
        "all_milestones_reached": all(k in reached for k in MILESTONES),
        "goto_error": reached.get("_goto_error"),
        "total_bytes_all_hosts": total,
        "data_host_bytes": sum(v["bytes"] for v in per_file.values()),
        "data_host_requests": {"status_206_ranged": ranged, "status_200_full": full, "other": partial},
        "per_file": dict(sorted(per_file.items(), key=lambda kv: -kv[1]["bytes"])),
        "worker_sessions_attached": len(worker_sessions),
        "worker_aware_total_bytes": sum(v["response_bytes"] for v in route_hits.values()),
        "worker_aware_per_file": dict(
            sorted(route_hits.items(), key=lambda kv: -kv[1]["response_bytes"])),
        "full_read_log_lines": len(fallback_logs),
        "diagnostics": fallback_logs[:10],
        "console_errors": console_errors[:10],
        "page_errors": page_errors[:10],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url", nargs="?", default="https://isamples.org")
    ap.add_argument("--budget", type=int, default=180)
    ap.add_argument("--profiles", default="unthrottled,4g,3g-fast,3g-slow")
    ap.add_argument("--viewports", default="desktop")
    ap.add_argument("--browsers", default="chromium")
    ap.add_argument("--out", default="/tmp/bandwidth_matrix.json")
    ap.add_argument("--query", default="", help="extra query string, e.g. ?data_base=http://localhost:8099")
    a = ap.parse_args()

    results = []
    with sync_playwright() as pw:
      for bname in a.browsers.split(","):
        for vname in a.viewports.split(","):
            for pname in a.profiles.split(","):
                print(f"--- {bname} / {pname} / {vname} (budget {a.budget}s) ...", flush=True)
                r = run_one(pw, a.base_url.rstrip("/"), pname, vname, a.budget, a.query, bname)
                results.append(r)
                m = r["milestones"]
                print(f"    globe={m['globe_drawn']}s facets={m['facet_trees']}s "
                      f"table={m['table_rows']}s  bytes={r['data_host_bytes']:,} "
                      f"206/200={r['data_host_requests']['status_206_ranged']}/"
                      f"{r['data_host_requests']['status_200_full']}", flush=True)

    payload = {"base_url": a.base_url, "query": a.query, "results": results}
    with open(a.out, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
