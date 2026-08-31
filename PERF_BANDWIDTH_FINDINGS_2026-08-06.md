# The Explorer downloads 74 MB to show you a globe — and why

**Date:** 2026-08-06 · **Status:** root-caused and proven by controlled experiment; fix not yet applied
**Harness:** `tests/playwright/bandwidth_matrix.py` (reproducible, committed alongside this doc)

---

## Plain English

Opening the Interactive Explorer with an empty cache transfers **about 74 MB** before the
facet panel appears. The site's own documentation says *"only the data you need is
downloaded — typically less than 1 MB for initial exploration."* That claim is wrong by
roughly two orders of magnitude.

The cause is **one HTTP status code**. DuckDB-WASM checks whether a server supports partial
downloads by sending a `HEAD` request with a `Range` header. Our data host answers `200`
instead of `206`, so DuckDB concludes "this server can't do partial reads" and downloads
**every file whole** — including a 63 MB one it only needs about 1.5 MB of.

Changing that single response to `206` cuts the cold load from **74 MB to 3.3 MB** and makes
the facet panel appear **4.7× sooner on a 3G connection**. The fix is server-side, in the
Cloudflare Worker in front of the bucket. No application code changes.

---

## The measurements

### Time to a usable Explorer, by connection (production, cold cache, desktop)

| Connection | Globe drawn | **Facet panel** | Table rows |
|---|---:|---:|---:|
| Unthrottled | 2.2 s | 10.8 s | 1.2 s |
| 4G (4 Mbps) | 15.4 s | **168.7 s** | 7.3 s |
| 3G fast (1.6 Mbps) | 38.7 s | **423.1 s** | 17.6 s |
| 3G slow (400 kbps) | 156.6 s | **never — not reached in 600 s** | 67.7 s |

On a slow connection the facet panel — the Explorer's main filtering affordance — **never
appears at all** within ten minutes.

### Cross-browser and viewport (unthrottled)

| Browser | Viewport | Globe | Facets | Bytes | Page errors |
|---|---|---:|---:|---:|---:|
| Chromium | desktop | 2.4 s | 7.6 s | 73.7 MB | 0 |
| Chromium | mobile | 2.3 s | 7.5 s | 73.7 MB | 0 |
| Firefox | desktop | 2.2 s | 6.3 s | 73.6 MB | 0 |
| Firefox | mobile | 2.2 s | 5.3 s | 73.6 MB | 0 |
| WebKit (Safari) | desktop | 2.4 s | 7.5 s | 73.7 MB | 0 |
| WebKit (Safari) | mobile | 2.3 s | 7.4 s | 73.6 MB | 0 |

**Good news for [#313](https://github.com/isamplesorg/isamplesorg.github.io/issues/313):** the
Explorer works in all three engines, desktop and mobile, with no uncaught errors and
comparable timings. That had been an open unknown since 2026-06-26.

**Bad news:** the 74 MB is identical in all three, so this is not a browser quirk.

---

## Root cause, and the experiment that proved it

DuckDB-WASM's per-file handshake, observed on production:

```
HEAD  range=None            -> 200
HEAD  range=bytes=0-        -> 200      <-- a range-capable server answers 206
GET   range=None            -> 200      <-- full 62,924,115 bytes
```

followed by `falling back to full HTTP read for: …` in the console, for eight files.

**A caution about how this was diagnosed.** The server was cleared *three times* on the basis
of `curl` tests before the real problem was found, because those tests used `GET`:

| Probe | Result |
|---|---|
| `GET` + `Range` | **206** + `Content-Range` ✅ |
| `HEAD` + `Range` | **200**, no `Content-Range` ❌ ← what DuckDB actually sends |
| `OPTIONS` preflight | 204, `Access-Control-Allow-Headers: Range` ✅ |
| `HEAD` CORS exposure | `Accept-Ranges` correctly exposed ✅ |

Everything was right except the one verb that mattered.

### Controlled A/B

A transparent reverse proxy forwarded every request to `data.isamples.org` unchanged, altering
**exactly one thing**: a `HEAD` carrying `Range` returned `206` + `Content-Range`. The Explorer
was served locally and pointed at each proxy via `?data_base=`. Same build, same cold cache,
same everything else.

**Unthrottled**

| | Control (`HEAD`+Range → 200) | Treatment (→ 206) |
|---|---:|---:|
| Bytes from data host | **74,202,598** | **3,341,812** |
| `full HTTP read` fallbacks | 8 | **0** |
| `samples_map_lite_v3.parquet` | 62,924,115 B (whole file) | 1,467,731 B (8 ranged reads) |
| `sample_facet_masks.parquet` | 10,138,648 B (whole file) | 767,000 B (48 ranged reads) |

**3G fast — the user-visible result**

| | Control | Treatment |
|---|---:|---:|
| Globe drawn | 54.0 s | 54.1 s |
| **Facet panel** | **440.6 s** | **94.2 s** |
| Table rows | 30.8 s | 30.7 s |
| Bytes | 74.2 MB | 3.0 MB |

**4.7× faster to a usable filter panel, 24× less data**, from one status code.

Globe and table are unchanged because they read the small H3 summary, not the big files.

---

## Recommended fix

In the Cloudflare Worker fronting `data.isamples.org`: when a `HEAD` request carries a `Range`
header and the object supports ranges, respond **`206`** with `Content-Range` (and no body, as
`HEAD` requires) instead of `200`.

Notes for whoever implements it:

- Returning `200` to `HEAD`+`Range` is **not** an RFC violation — `raw.githubusercontent.com`
  does the same. This is about interoperating with DuckDB-WASM's capability probe, which is the
  single most important client this bucket has.
- `Content-Range` must stay in `Access-Control-Expose-Headers` (it already is) or the browser
  cannot read it cross-origin.
- **Verify with `HEAD`, not `GET`.** That mistake cost three false "server is fine" conclusions.
- The A/B proxy (`range_fix_proxy.py`, referenced in the issue) reproduces both arms in minutes.

### Also worth correcting once fixed

`index.qmd` claims *"typically less than 1 MB for initial exploration"* and `explorer.qmd`
claims *"only the bytes you need are transferred."* Both are currently false. After the fix the
measured figure is ~3.3 MB cold — still a good story, and an honest one.

---

## Method notes (read before trusting or extending the harness)

Two instrumentation traps were hit and corrected; both would have produced confidently wrong
conclusions:

1. **Page-level CDP does not see Web Worker traffic.** DuckDB-WASM runs in a worker. Measuring
   only the page session reported **568 KB and 3 requests** — which looks exactly like a healthy
   "only the bytes you need" result and is off by a factor of 130. Real accounting uses
   context-level `requestfinished` events, which do observe worker requests.
2. **The instrument changed the measurement, twice.** `Target.setAutoAttach` with
   `waitForDebuggerOnStart: true` paused workers that were never resumed, so the globe never
   rendered and the run looked broken. And `ctx.route(...) + continue_()` interception inflated
   time-to-globe from 2.5 s to 7.3 s. The final harness is passive.

Also: `sizes()` returns `-1` for indeterminate bodies; the harness counts those separately
rather than letting negatives offset real totals (an early version reported a file as −885 bytes).

**Limits.** Timings are single runs on one machine and one uplink, not medians over repeats —
treat them as order-of-magnitude, not benchmarks. Throttling is Chrome DevTools emulation, not a
real cellular link. Firefox/WebKit runs are unthrottled (CDP is Chromium-only). Only cold-cache
first visits were measured; a returning visitor with a warm cache is a different, much better
story that was not characterised here.

---

## Reproduce

```bash
# the matrix (production, desktop, four connection profiles)
python tests/playwright/bandwidth_matrix.py https://isamples.org \
    --profiles unthrottled,4g,3g-fast,3g-slow --budget 600 --out /tmp/matrix.json

# cross-browser
python tests/playwright/bandwidth_matrix.py https://isamples.org \
    --browsers chromium,firefox,webkit --viewports desktop,mobile --profiles unthrottled
```
