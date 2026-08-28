#!/usr/bin/env python3
"""Measure the explorer's parquet traffic over a cold boot (and optionally a warm reload).

Counts EVERY .parquet GET the page makes — including DuckDB-WASM's fetches, which
run in a Web Worker and are invisible to page-level `performance` entries — and
reports, per file: number of ranged (206) GETs, bytes transferred, unique byte
coverage (Content-Range intervals merged), overlap (re-fetched bytes), and
whole-file (200) GETs with their Cache-Control. Also polls the samples table's
pager so "time to table" can be compared across builds.

Written for #345 (range requests) and #351 (samples_map_lite read twice); the
numbers in those issues came from this method.

Usage:
    python3 tests/playwright/measure_parquet_ranges.py URL [SECONDS] [--warm]

    URL      explorer page, e.g. http://localhost:5860/explorer.html or
             https://isamples.org/explorer.html (append ?data_base=... to point
             at a canary data host)
    SECONDS  how long to keep listening after `load` (default 60; a full cold
             boot needs 150-240 on a slow link)
    --warm   after the cold run, reload in the SAME browser context and report
             again — shows what the HTTP cache absorbs

If the page was built with the `?sqllog=1` diagnostic (not in production), SQL
statements are attributed per file too.

Requires: playwright (python) with chromium installed.
"""
import collections
import re
import sys
import time

from playwright.sync_api import sync_playwright


def summarise(label, ranges, whole, whole_hdr, fallbacks, sql, perf, table_at):
    print(f"===== {label}")
    print(f"  fallbacks ('falling back to full HTTP read'): {fallbacks}")
    print(f"  time to samples table ('Page 1 of'): {table_at:.1f}s" if table_at else "  time to samples table: not seen")
    if perf:
        print(f"  page hooks: {perf}")
    for f, rs in sorted(ranges.items(), key=lambda kv: -sum(e - s + 1 for s, e, _, _ in kv[1])):
        size = rs[0][2]
        tx = sum(e - s + 1 for s, e, _, _ in rs)
        merged = []
        for s, e in sorted((s, e) for s, e, _, _ in rs):
            if merged and s <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        uniq = sum(e - s + 1 for s, e in merged)
        if tx < 2e5:
            continue  # metadata-sized files: noise
        print(f"  {f}: file {size/1e6:.1f} MB | {len(rs)} ranged GETs, transferred {tx/1e6:.1f} MB, "
              f"unique {uniq/1e6:.1f} MB ({100*uniq/size:.0f}%), overlap {100*(tx-uniq)/max(tx,1):.0f}% | "
              f"first {rs[0][3]:.1f}s last {rs[-1][3]:.1f}s")
    for f, n in whole.most_common():
        if n >= 2e5:
            print(f"  {f}: whole-file GET {n/1e6:.1f} MB  (status, cache-control, at): {whole_hdr[f]}")
    tot_r = sum(e - s + 1 for rs in ranges.values() for s, e, _, _ in rs)
    print(f"  TOTAL parquet bytes: ranged {tot_r/1e6:.1f} MB + whole {sum(whole.values())/1e6:.1f} MB "
          f"= {(tot_r + sum(whole.values()))/1e6:.1f} MB")
    if sql:
        byfile = collections.Counter()
        first = {}
        for t, q in sql:
            for f in re.findall(r"read_parquet\('([^']+)'\)", q):
                f = f.split('/')[-1]
                byfile[f] += 1
                first.setdefault(f, t)
        print("  SQL statements by file (count@first):",
              ", ".join(f"{f}={n}@{first[f]:.0f}s" for f, n in byfile.most_common()))


def run(page, url, wait, label):
    ranges = collections.defaultdict(list)
    whole = collections.Counter()
    whole_hdr = {}
    fallbacks = [0]
    sql = []
    t0 = time.time()

    def on_resp(r):
        if '.parquet' not in r.url or r.request.method != 'GET':
            return
        f = r.url.split('/')[-1].split('?')[0]
        m = re.match(r'bytes (\d+)-(\d+)/(\d+)', r.headers.get('content-range') or '')
        if r.status == 206 and m:
            ranges[f].append((int(m.group(1)), int(m.group(2)), int(m.group(3)), time.time() - t0))
        else:
            cl = r.headers.get('content-length')
            whole[f] += int(cl) if cl else 0
            h = r.headers
            whole_hdr[f] = {'status': r.status, 'at_s': round(time.time() - t0, 1),
                            **{k: h.get(k) for k in ('cache-control', 'vary', 'content-encoding', 'cf-cache-status', 'age') if h.get(k)}}

    def on_console(m):
        if 'falling back to full HTTP read' in m.text:
            fallbacks[0] += 1
        if m.text.startswith('[sql]'):
            sql.append((time.time() - t0, m.text[6:]))

    page.on('response', on_resp)
    page.on('console', on_console)
    page.goto(url, wait_until='load')
    table_at = None
    marks = {}   # first time each boot milestone was observed
    deadline = time.time() + wait
    while time.time() < deadline:
        page.wait_for_timeout(1000)
        if table_at is None:
            try:
                txt = page.locator('#tablePageInfo').text_content(timeout=200) or ''
                if 'Page 1 of' in txt:
                    table_at = time.time() - t0
            except Exception:
                pass
        try:
            st = page.evaluate("() => ({facet: window.__facetIndexStatus, ready: window.__filteredClustersReady, lite: !!window.__liteFile})")
            if st.get('facet') in ('ready', 'failed'): marks.setdefault('facetIndex_' + st['facet'], round(time.time() - t0, 1))
            if st.get('ready') is True: marks.setdefault('filteredClustersReady', round(time.time() - t0, 1))
            if st.get('lite'): marks.setdefault('liteFile_settled', round(time.time() - t0, 1))
        except Exception:
            pass
    page.remove_listener('response', on_resp)
    page.remove_listener('console', on_console)
    perf = page.evaluate("""() => {
        const lf = performance.getEntriesByName('lite_fetch')[0];
        // Resource timing for the page-initiated whole-file fetch: transferSize 0 == served from the HTTP cache.
        const rt = performance.getEntriesByType('resource').filter(e => e.name.includes('samples_map_lite')).map(e =>
            ({ transferSize: e.transferSize, encodedBodySize: e.encodedBodySize, dur_s: +(e.duration/1000).toFixed(1) }));
        return { lite_fetch: lf ? {start_s: +(lf.startTime/1000).toFixed(1), dur_s: +(lf.duration/1000).toFixed(1)} : null,
                 lite_resource_timing: rt, liteFile: window.__liteFile || null, facetIndexStatus: window.__facetIndexStatus || null };
    }""")
    perf['milestones_s'] = marks
    summarise(label, ranges, whole, whole_hdr, fallbacks[0], sql, perf, table_at)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        sys.exit(2)
    url = args[0]
    wait = int(args[1]) if len(args) > 1 else 60
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
        page = ctx.new_page()
        run(page, url, wait, f"COLD  {url}  ({wait}s)")
        if '--warm' in sys.argv:
            run(page, url, wait, f"WARM reload, same context  {url}  ({wait}s)")
        b.close()


if __name__ == '__main__':
    main()
