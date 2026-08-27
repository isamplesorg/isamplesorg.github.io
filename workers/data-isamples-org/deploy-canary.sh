#!/usr/bin/env bash
# Deploy the #345 HEAD+Range shim to a NON-PRODUCTION canary and verify it.
#
# Safe by construction: uses wrangler.canary.toml, which has a different Worker
# name and NO routes, so it cannot land in front of data.isamples.org. The
# production wrangler.toml is never read or modified.
#
#   ./deploy-canary.sh            # deploy + verify + print the test URL
#   ./deploy-canary.sh --verify   # verify an already-deployed canary
#   ./deploy-canary.sh --teardown # delete the canary
set -uo pipefail
cd "$(dirname "$0")"

NAME="isamples-data-345-canary"
PROBE_FILE="isamples_202608_h3_summary_res4.parquet"
PROBE_SIZE=505651
STAGING="https://rdhyee.github.io/isamplesorg.github.io"

if [ "${1:-}" = "--teardown" ]; then
  echo "Deleting canary Worker '$NAME'..."
  npx wrangler delete --name "$NAME"
  exit $?
fi

# --- auth -------------------------------------------------------------------
if ! npx wrangler whoami >/dev/null 2>&1; then
  echo "Not logged in to Cloudflare."
  echo "Run this in an interactive terminal first:"
  echo
  echo "    npx wrangler login"
  echo
  echo "(or export CLOUDFLARE_API_TOKEN=... with Workers Scripts:Edit + R2 read)"
  exit 1
fi

# --- deploy -----------------------------------------------------------------
if [ "${1:-}" != "--verify" ]; then
  echo "==> Deploying canary (NO routes, workers.dev only)"
  # Abort explicitly on a failed deploy. This script deliberately does not use
  # `set -e` (several grep pipelines below are allowed to fail), so without this
  # check a failed upload would fall through and verify an OLDER canary, then
  # report success — the wrong answer with a confident face.
  if ! npx wrangler deploy -c wrangler.canary.toml | tee /tmp/canary_deploy.log; then
    echo "!! wrangler deploy failed — nothing verified, nothing promoted."
    exit 1
  fi
  echo
fi

# The deploy output contains the workers.dev URL; recover it, else construct it.
URL=$(grep -oE 'https://[a-z0-9._-]*\.workers\.dev' /tmp/canary_deploy.log 2>/dev/null | head -1)
if [ -z "$URL" ]; then
  SUB=$(npx wrangler whoami 2>/dev/null | grep -oE '[a-z0-9-]+\.workers\.dev' | head -1)
  [ -n "$SUB" ] && URL="https://${NAME}.${SUB}"
fi
if [ -z "$URL" ]; then
  echo "!! Could not determine the canary URL. Check /tmp/canary_deploy.log and pass it manually:"
  echo "   CANARY_URL=https://... $0 --verify"
  URL="${CANARY_URL:-}"
  [ -z "$URL" ] && exit 1
fi

echo "==> Canary URL: $URL"
echo

# --- wait for the workers.dev route to go live ------------------------------
# A freshly deployed workers.dev hostname is NOT immediately routable: for the
# first few seconds Cloudflare's edge answers 404 before the route propagates.
# The first version of this script verified instantly and reported seven
# confident failures against a Worker that was in fact perfectly healthy —
# including "the shim has widened", which was simply untrue. Poll for readiness
# before asserting anything.
echo "==> Waiting for the workers.dev route to propagate"
ready=0
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$URL/")
  if [ "$code" = "200" ]; then
    echo "  route live after ~$((i*2))s"
    ready=1
    break
  fi
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  echo "  !! route still not answering 200 at $URL/ after ~60s."
  echo "     Not asserting anything — a 404 here means 'not deployed yet',"
  echo "     not 'the change is broken'. Re-run with --verify shortly."
  exit 1
fi
echo

# --- verify the handshake actually changed ---------------------------------
fail=0
ok() { printf "  ok   %s\n" "$1"; }
no() { printf "  FAIL %s (%s)\n" "$1" "$2"; fail=1; }

echo "==> Verifying the DuckDB probe now gets 206"
S=$(curl -s -o /dev/null -w '%{http_code}' -I -H 'Range: bytes=0-' "$URL/$PROBE_FILE")
CR=$(curl -sI -H 'Range: bytes=0-' "$URL/$PROBE_FILE" | grep -i '^content-range:' | tr -d '\r' | cut -d' ' -f2-)
[ "$S" = "206" ] && ok "HEAD+Range 'bytes=0-' -> 206" || no "HEAD+Range -> 206" "got $S"
[ "$CR" = "bytes 0-$((PROBE_SIZE-1))/$PROBE_SIZE" ] && ok "Content-Range correct" \
  || no "Content-Range" "got '$CR'"
# DuckDB-WASM accepts the probe on 206 + a usable Content-Length, so assert the
# length too (a 206 with a wrong/missing length still means whole-file reads).
CL=$(curl -sI -H 'Range: bytes=0-' "$URL/$PROBE_FILE" | grep -i '^content-length:' | tr -d '\r' | awk '{print $2}')
[ "$CL" = "$PROBE_SIZE" ] && ok "Content-Length == $PROBE_SIZE" || no "Content-Length" "got '$CL'"

echo
echo "==> Verifying the shim did NOT widen (these must stay standards-correct 200)"
for R in 'bytes=0-99' 'bytes=100-199' 'bytes=-100'; do
  S=$(curl -s -o /dev/null -w '%{http_code}' -I -H "Range: $R" "$URL/$PROBE_FILE")
  [ "$S" = "200" ] && ok "HEAD '$R' -> 200" || no "HEAD '$R' -> 200" "got $S"
done

echo
echo "==> Verifying GET paths unchanged"
S=$(curl -s -o /dev/null -w '%{http_code}' -H 'Range: bytes=0-99' "$URL/$PROBE_FILE")
[ "$S" = "206" ] && ok "ranged GET -> 206" || no "ranged GET -> 206" "got $S"
S=$(curl -s -o /dev/null -w '%{http_code}' "$URL/$PROBE_FILE")
[ "$S" = "200" ] && ok "plain GET -> 200" || no "plain GET -> 200" "got $S"

echo
if [ "$fail" -ne 0 ]; then
  echo "VERIFICATION FAILED — do not promote to the data.isamples.org route."
  exit 1
fi
echo "All canary checks passed."
echo
echo "───────────────────────────────────────────────────────────────"
echo "Open the staging Explorer against the canary:"
echo
echo "  $STAGING/explorer.html?data_base=$URL"
echo
echo "Measure it end-to-end (from the repo root):"
echo
echo "  python tests/playwright/bandwidth_matrix.py $STAGING \\"
echo "      --profiles unthrottled,3g-fast --budget 600 \\"
echo "      --query \"?data_base=$URL\""
echo
echo "Expect: ~3 MB instead of ~74 MB, and 0 'full HTTP read' fallbacks."
echo
echo "Tear down when done:   $0 --teardown"
echo "───────────────────────────────────────────────────────────────"
