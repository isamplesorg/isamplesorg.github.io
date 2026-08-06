#!/usr/bin/env bash
# HTTP contract test for the data.isamples.org Worker, run against `wrangler dev --local`.
#
# Exists because of #345: the Worker answered 200 to a HEAD carrying a Range header,
# which is the exact probe DuckDB-WASM uses to decide whether a server supports
# partial reads. Answering 200 made it download whole files — 74 MB on a cold
# Explorer load instead of ~3 MB.
#
# Setup (once):
#   curl -H 'User-Agent: isamples-worker-test/1.0' \
#     -o /tmp/test_res4.parquet \
#     https://data.isamples.org/isamples_202608_h3_summary_res4.parquet
#   npx wrangler r2 object put isamples-ry/isamples_202608_h3_summary_res4.parquet \
#     --file=/tmp/test_res4.parquet --local
#
# Run:
#   npx wrangler dev --local --port 8787 &
#   ./test/range_contract.sh 8787
set -uo pipefail

PORT="${1:-8787}"
BASE="http://127.0.0.1:${PORT}"
KEY="isamples_202608_h3_summary_res4.parquet"
SIZE=505651

pass=0; fail=0
check() { # check <name> <expected> <actual>
  if [ "$2" = "$3" ]; then printf "  ok   %-52s %s\n" "$1" "$3"; pass=$((pass+1))
  else printf "  FAIL %-52s expected=%s actual=%s\n" "$1" "$2" "$3"; fail=$((fail+1)); fi
}
status()  { curl -s -o /dev/null -w '%{http_code}' "$@"; }
header()  { local h="$1"; shift; curl -sI "$@" | grep -i "^${h}:" | head -1 | cut -d' ' -f2- | tr -d '\r'; }
ghdr()    { local h="$1"; shift; curl -s -D - -o /dev/null "$@" | grep -i "^${h}:" | head -1 | cut -d' ' -f2- | tr -d '\r'; }
bodylen() { curl -s -o /dev/null -w '%{size_download}' "$@"; }

# #345 — a NARROW, deliberately nonstandard compatibility shim.
#
# RFC 9110 §14.2 is explicit: Range is defined only for GET, and a server MUST
# IGNORE Range on other methods including HEAD. So 200 is the CORRECT answer and
# these assertions encode a knowing divergence, scoped as tightly as possible:
# only the exact probe DuckDB-WASM 1.24.0 sends (`Range: bytes=0-`) is answered
# 206. Every other ranged HEAD stays standards-correct at 200, so the divergence
# cannot leak to other clients. Remove this shim when the Explorer no longer
# depends on that probe (see the removal path in the issue).
echo "=== #345 shim: ONLY the exact DuckDB probe (Range: bytes=0-) gets 206 ==="
check "probe HEAD status"        "206"                        "$(status -I -H 'Range: bytes=0-' "$BASE/$KEY")"
check "probe HEAD Content-Range" "bytes 0-$((SIZE-1))/$SIZE"  "$(header content-range -H 'Range: bytes=0-' "$BASE/$KEY")"
check "probe HEAD sends no body" "0"                          "$(bodylen -I -H 'Range: bytes=0-' "$BASE/$KEY")"

echo
echo "=== the shim must NOT widen: other ranged HEADs stay standards-correct (200) ==="
check "HEAD bytes=0-99 status"   "200" "$(status -I -H 'Range: bytes=0-99' "$BASE/$KEY")"
check "HEAD bytes=0-99 no CR"    ""    "$(header content-range -H 'Range: bytes=0-99' "$BASE/$KEY")"
check "HEAD suffix range status" "200" "$(status -I -H 'Range: bytes=-100' "$BASE/$KEY")"
check "HEAD mid-range status"    "200" "$(status -I -H 'Range: bytes=100-199' "$BASE/$KEY")"

echo
echo "=== must not regress: plain HEAD stays 200 with full Content-Length ==="
check "HEAD status"              "200"    "$(status -I "$BASE/$KEY")"
check "HEAD Content-Length"      "$SIZE"  "$(header content-length "$BASE/$KEY")"
check "HEAD Accept-Ranges"       "bytes"  "$(header accept-ranges "$BASE/$KEY")"

echo
echo "=== must not regress: GET paths ==="
check "GET status"               "200"                  "$(status "$BASE/$KEY")"
check "GET body size"            "$SIZE"                "$(bodylen "$BASE/$KEY")"
check "ranged GET status"        "206"                  "$(status -H 'Range: bytes=0-99' "$BASE/$KEY")"
check "ranged GET body size"     "100"                  "$(bodylen -H 'Range: bytes=0-99' "$BASE/$KEY")"
check "ranged GET Content-Range" "bytes 0-99/$SIZE"     "$(ghdr content-range -H 'Range: bytes=0-99' "$BASE/$KEY")"

echo
echo "=== must not regress: caching + CORS contract (the Worker's raison d'etre) ==="
check "immutable Cache-Control"  "public, max-age=31536000, immutable" "$(header cache-control "$BASE/$KEY")"
check "CC same on HEAD+Range"    "public, max-age=31536000, immutable" "$(header cache-control -H 'Range: bytes=0-' "$BASE/$KEY")"
check "CORS allow-origin"        "*"                                   "$(header access-control-allow-origin "$BASE/$KEY")"
check "exposes Content-Range"    "Content-Length, Content-Range, Accept-Ranges, ETag" \
                                 "$(header access-control-expose-headers -H 'Range: bytes=0-' "$BASE/$KEY")"
check "OPTIONS preflight"        "204"                                 "$(status -X OPTIONS "$BASE/$KEY")"
check "404 for missing key"      "404"                                 "$(status "$BASE/no_such_file.parquet")"

echo
echo "=== ETag must be stable across methods (cache correctness) ==="
E_GET=$(ghdr etag "$BASE/$KEY"); E_HEAD=$(header etag "$BASE/$KEY"); E_HR=$(header etag -H 'Range: bytes=0-' "$BASE/$KEY")
check "ETag HEAD == GET"         "$E_GET" "$E_HEAD"
check "ETag HEAD+Range == GET"   "$E_GET" "$E_HR"

echo
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
