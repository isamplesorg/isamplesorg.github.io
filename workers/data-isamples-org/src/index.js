/**
 * Cloudflare Worker: data.isamples.org
 *
 * Proxies the iSamples R2 bucket and adds cache-control headers so the
 * Cloudflare edge and the browser can cache immutable parquet versions
 * aggressively.
 *
 * Strategy:
 *   - Filename-versioned parquets (isamples_YYYYMM_*.parquet) are immutable
 *     by naming convention → cache one year + immutable.
 *   - Anything else falls back to a short TTL.
 *
 * Uses the R2 bucket binding (env.BUCKET) rather than fetching the r2.dev
 * public URL — fewer hops, lower latency, no need to expose the bucket
 * publicly.
 *
 * Range requests are supported so DuckDB-WASM's HTTP range fetches keep
 * working.
 */

// Immutable-by-filename patterns. Match files whose path fully determines
// their contents (filename includes a version / date stamp).
//   - isamples_YYYYMM_*.parquet  (monthly iSamples snapshots)
//   - oc_pqg/oc_isamples_pqg*_YYYYMMDD.parquet  (mirror of Eric Kansa's
//     OpenContext PQG files — versioned by the upstream GCS updated-date)
const IMMUTABLE_PATTERNS = [
  /^isamples_\d{6}_.*\.parquet$/,
  /^oc_pqg\/oc_isamples_pqg.*_\d{8}\.parquet$/,
];
const IMMUTABLE_MAX_AGE = 60 * 60 * 24 * 365; // 1 year
const FALLBACK_MAX_AGE = 300; // 5 minutes

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
  'Access-Control-Allow-Headers': 'Range',
  'Access-Control-Expose-Headers': 'Content-Length, Content-Range, Accept-Ranges, ETag',
};

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method not allowed', { status: 405, headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    const key = decodeURIComponent(url.pathname.replace(/^\/+/, ''));

    if (!key) {
      // Simple root response — could be replaced with an index listing later.
      return new Response('data.isamples.org — R2 bucket proxy\n', {
        status: 200,
        headers: { 'content-type': 'text/plain; charset=utf-8', ...CORS_HEADERS },
      });
    }

    // === /current/ alias layer ===
    // `/current/<flavor>.parquet` reads `current/manifest.json` from R2 and
    // 302-redirects to the dated file it points to. Lets consumers pin to a
    // stable URL while the underlying immutable file rotates out-of-band.
    const currentAliasMatch = key.match(/^current\/([a-z0-9_-]+)\.parquet$/i);
    if (currentAliasMatch) {
      const flavor = currentAliasMatch[1];
      const manifestObj = await env.BUCKET.get('current/manifest.json');
      if (!manifestObj) {
        return new Response('current/manifest.json not found', { status: 503, headers: CORS_HEADERS });
      }
      let manifest;
      try {
        manifest = JSON.parse(await manifestObj.text());
      } catch (e) {
        return new Response('current/manifest.json is invalid JSON', { status: 503, headers: CORS_HEADERS });
      }
      const entry = manifest[flavor];
      if (!entry || !entry.public_url) {
        return new Response(
          `current/manifest.json has no entry for flavor '${flavor}'`,
          { status: 404, headers: CORS_HEADERS }
        );
      }
      // 302 Found preserves the request method semantics and lets clients
      // re-issue range requests against the target URL directly.
      return new Response(null, {
        status: 302,
        headers: {
          'Location': entry.public_url,
          // Short TTL so rotation propagates quickly without stale fanout.
          'Cache-Control': `public, max-age=${FALLBACK_MAX_AGE}`,
          ...CORS_HEADERS,
        },
      });
    }

    // Parse Range header if present. R2's get() accepts { offset, length } or
    // { suffix }, mirroring HTTP Range semantics.
    const rangeHeader = request.headers.get('range');
    const range = rangeHeader ? parseRange(rangeHeader) : undefined;

    const getOptions = range ? { range } : {};
    const object = request.method === 'HEAD'
      ? await env.BUCKET.head(key)
      : await env.BUCKET.get(key, getOptions);

    if (!object) {
      return new Response('Not found', { status: 404, headers: CORS_HEADERS });
    }

    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set('ETag', object.httpEtag);
    headers.set('Accept-Ranges', 'bytes');

    for (const [k, v] of Object.entries(CORS_HEADERS)) headers.set(k, v);

    // Cache-Control: this is the optimization.
    if (IMMUTABLE_PATTERNS.some(p => p.test(key))) {
      headers.set('Cache-Control', `public, max-age=${IMMUTABLE_MAX_AGE}, immutable`);
    } else {
      headers.set('Cache-Control', `public, max-age=${FALLBACK_MAX_AGE}`);
    }

    if (request.method === 'HEAD') {
      headers.set('Content-Length', String(object.size));
      return new Response(null, { status: 200, headers });
    }

    // Range response: 206 + Content-Range. R2 populates object.range when a
    // range was requested, but for safety compute the Content-Range ourselves.
    if (range) {
      const total = object.size !== undefined ? object.size : null;
      // object.get with range returns only the sliced body + partial size info.
      // We need the full object size for the Content-Range header; fetch via
      // head() once per cold request.
      let fullSize = total;
      if (fullSize == null || typeof fullSize !== 'number') {
        const head = await env.BUCKET.head(key);
        fullSize = head ? head.size : null;
      }
      const start = range.offset ?? 0;
      const length = range.length ?? (fullSize != null ? fullSize - start : undefined);
      const end = length != null ? start + length - 1 : (fullSize != null ? fullSize - 1 : 0);
      if (fullSize != null) {
        headers.set('Content-Range', `bytes ${start}-${end}/${fullSize}`);
        headers.set('Content-Length', String(end - start + 1));
      }
      return new Response(object.body, { status: 206, headers });
    }

    return new Response(object.body, { status: 200, headers });
  },
};

/**
 * Parse an HTTP Range header into the { offset, length } shape R2 expects.
 * Supports `bytes=START-END` and `bytes=-SUFFIX`. Returns undefined for
 * anything we can't parse so the caller falls back to a full-object fetch.
 */
function parseRange(header) {
  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!match) return undefined;
  const [, startStr, endStr] = match;
  if (startStr === '' && endStr === '') return undefined;
  if (startStr === '') {
    // Suffix: last N bytes
    const suffix = Number(endStr);
    if (!Number.isFinite(suffix) || suffix <= 0) return undefined;
    return { suffix };
  }
  const offset = Number(startStr);
  if (!Number.isFinite(offset) || offset < 0) return undefined;
  if (endStr === '') return { offset };
  const end = Number(endStr);
  if (!Number.isFinite(end) || end < offset) return undefined;
  return { offset, length: end - offset + 1 };
}
