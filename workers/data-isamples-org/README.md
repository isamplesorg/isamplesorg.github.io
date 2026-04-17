# `data.isamples.org` Worker

A Cloudflare Worker that proxies the iSamples R2 bucket at
`data.isamples.org` and — most importantly — adds a `Cache-Control` header
so Cloudflare's edge and the user's browser can cache immutable parquet
versions aggressively.

## Why this exists

The parquet files under `data.isamples.org` are filename-versioned
(`isamples_202601_wide.parquet`, `isamples_202601_h3_summary_res4.parquet`,
etc.) — the month appears in the filename, so content at a given URL never
changes.

Without a `Cache-Control` header, Cloudflare's edge does **not** cache these
files, and browsers use unpredictable heuristic caching (often: re-fetch on
every visit). This Worker fixes that by emitting:

```
Cache-Control: public, max-age=31536000, immutable
```

…for any path matching `^isamples_\d{6}_.*\.parquet$`, and a short 5-minute
fallback for anything else.

## What it does

| Concern | How |
| --- | --- |
| R2 access | R2 bucket binding (`env.BUCKET`) — no public `r2.dev` hop |
| Range requests | Parsed and forwarded; required for DuckDB-WASM |
| CORS | `Access-Control-Allow-Origin: *`, exposes `Content-Range` etc. |
| HEAD requests | Uses `BUCKET.head()` and returns headers only |
| Immutable cache | `max-age=31536000, immutable` for versioned parquets |
| Short cache fallback | `max-age=300` for anything else |

## Deploying

One-time setup (if not already done):

```bash
cd workers/data-isamples-org
npm install -g wrangler    # or: npx wrangler ...
wrangler login             # opens browser, auth to isamples.org account
```

Verify the R2 bucket name in `wrangler.toml` matches your actual bucket
(Cloudflare dashboard → R2 → buckets). Update `bucket_name` if needed.

Deploy:

```bash
wrangler deploy
```

This publishes the Worker and installs the route `data.isamples.org/*`.

> The Worker is named `isamples-data` in `wrangler.toml` to match the
> pre-existing Worker that owned `data.isamples.org/*` before this repo
> existed. `wrangler deploy` atomically replaces the existing Worker at
> that name. If you rename, also unassign the old Worker from the route
> first (Cloudflare dashboard → Workers → Routes) or the deploy will
> fail with "already assigned to another worker."

## Verifying

After deploy:

```bash
curl -sI https://data.isamples.org/isamples_202601_h3_summary_res4.parquet \
  | grep -iE 'cache-control|cf-cache-status|etag'
```

You should see:

```
cache-control: public, max-age=31536000, immutable
etag: "..."
```

First request after deploy will show `cf-cache-status: MISS`; subsequent
requests should show `HIT` (edge cache warmed). Browser refreshes on the
Interactive Explorer (`?perf=1`) should drop phase 1 res4 duration toward
zero on warm cache.

## Local dev

```bash
wrangler dev
```

Starts a local server on `http://localhost:8787/` that proxies the live R2
bucket. Useful for testing header logic without touching production.

## Future extensions

- Path-based routing (e.g. `/parquet/...`, `/record/<uuid>`) per issue #81
- Per-object cache hints via R2 custom metadata
- Index listing at `/` (currently just a plain-text stub)
