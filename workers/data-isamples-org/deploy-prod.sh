#!/usr/bin/env bash
# Deploy the data.isamples.org Worker to PRODUCTION, verify it, and print the
# one-command rollback. Companion to deploy-canary.sh (which must have passed
# first — this script refuses to run unless you say the canary was verified).
#
#   ./deploy-prod.sh --preflight        # read-only: what would change, and the rollback id
#   ./deploy-prod.sh                    # deploy + verify (asks for confirmation)
#   ./deploy-prod.sh --verify           # verify production only (no deploy)
#   ./deploy-prod.sh --rollback <id>    # roll production back to a previous version
#
# Why this exists (#345): the Worker change is ~30 lines, but the route is
# data.isamples.org/* — every Explorer visitor and every Python/DuckDB user of the
# parquet files goes through it. A bad deploy is a production incident for all of
# them at once. So: pre-flight, explicit confirmation, verification with the same
# assertions as the canary, and a rollback you can paste without thinking.
set -uo pipefail
cd "$(dirname "$0")"

ORIGIN="https://data.isamples.org"
PROBE_FILE="isamples_202608_h3_summary_res4.parquet"
PROBE_SIZE=505651
BIG_FILE="isamples_202608_samples_map_lite_v3.parquet"   # the one a whole-file read hurts
ACCOUNT_ID_EXPECTED="75e8a095c424e5a4e18fd6f5e6145064"
UA="isamples-deploy-prod/1.0 (+https://isamples.org)"

ok() { printf "  ok   %s\n" "$1"; }
no() { printf "  FAIL %s (%s)\n" "$1" "$2"; fail=1; }
hdr() { curl -s -A "$UA" -I "$@" | grep -i "^$H:" | head -1 | tr -d '\r' | cut -d' ' -f2-; }

current_version() {
  npx wrangler deployments list -c wrangler.toml 2>/dev/null | grep -oE '\(100%\) [0-9a-f-]{36}' | tail -1 | awk '{print $2}'
}

# --- auth + account sanity ---------------------------------------------------
if ! npx wrangler whoami >/dev/null 2>&1; then
  echo "Not logged in to Cloudflare. Run: npx wrangler login"; exit 1
fi
if ! npx wrangler whoami 2>/dev/null | grep -q "$ACCOUNT_ID_EXPECTED"; then
  echo "!! The logged-in Cloudflare identity cannot see account $ACCOUNT_ID_EXPECTED (wrangler.toml). Stop."; exit 1
fi

# --- rollback -----------------------------------------------------------------
if [ "${1:-}" = "--rollback" ]; then
  [ -z "${2:-}" ] && { echo "usage: $0 --rollback <version-id>"; exit 2; }
  echo "==> Rolling data.isamples.org back to version $2"
  npx wrangler rollback "$2" -c wrangler.toml --message "rollback via deploy-prod.sh" || exit 1
  exec "$0" --verify --expect-shim no
fi

# --- verify ---------------------------------------------------------------------
verify() {
  local expect_shim="$1" fail=0
  echo "==> Verifying $ORIGIN (expecting the #345 shim: $expect_shim)"
  local S CR CL
  S=$(curl -s -A "$UA" -o /dev/null -w '%{http_code}' -I -H 'Range: bytes=0-' "$ORIGIN/$PROBE_FILE")
  H=content-range; CR=$(hdr -H 'Range: bytes=0-' "$ORIGIN/$PROBE_FILE")
  H=content-length; CL=$(hdr -H 'Range: bytes=0-' "$ORIGIN/$PROBE_FILE")
  if [ "$expect_shim" = "yes" ]; then
    [ "$S" = "206" ] && ok "DuckDB probe HEAD+Range 'bytes=0-' -> 206" || no "probe -> 206" "got $S"
    [ "$CR" = "bytes 0-$((PROBE_SIZE-1))/$PROBE_SIZE" ] && ok "Content-Range correct" || no "Content-Range" "got '$CR'"
    [ "$CL" = "$PROBE_SIZE" ] && ok "Content-Length == $PROBE_SIZE" || no "Content-Length" "got '$CL'"
  else
    [ "$S" = "200" ] && ok "probe HEAD+Range -> 200 (shim absent, as expected)" || no "probe -> 200" "got $S"
  fi
  for R in 'bytes=0-99' 'bytes=100-199' 'bytes=-100'; do
    S=$(curl -s -A "$UA" -o /dev/null -w '%{http_code}' -I -H "Range: $R" "$ORIGIN/$PROBE_FILE")
    [ "$S" = "200" ] && ok "HEAD '$R' -> 200 (shim has not widened)" || no "HEAD '$R' -> 200" "got $S"
  done
  S=$(curl -s -A "$UA" -o /dev/null -w '%{http_code}' -I "$ORIGIN/$PROBE_FILE")
  H=content-length; CL=$(hdr "$ORIGIN/$PROBE_FILE")
  [ "$S" = "200" ] && [ "$CL" = "$PROBE_SIZE" ] && ok "plain HEAD -> 200, Content-Length $PROBE_SIZE" || no "plain HEAD" "got $S / '$CL'"
  S=$(curl -s -A "$UA" -o /dev/null -w '%{http_code}' -H 'Range: bytes=0-99' "$ORIGIN/$PROBE_FILE")
  [ "$S" = "206" ] && ok "ranged GET -> 206" || no "ranged GET -> 206" "got $S"
  local N; N=$(curl -s -A "$UA" -o /dev/null -w '%{size_download}' -H 'Range: bytes=0-99' "$ORIGIN/$PROBE_FILE")
  [ "$N" = "100" ] && ok "ranged GET body = 100 bytes" || no "ranged GET body" "got $N"
  S=$(curl -s -A "$UA" -o /dev/null -w '%{http_code}' "$ORIGIN/$PROBE_FILE")
  [ "$S" = "200" ] && ok "plain GET -> 200" || no "plain GET -> 200" "got $S"
  H=cache-control; local CC; CC=$(hdr "$ORIGIN/$PROBE_FILE")
  [ "$CC" = "public, max-age=31536000, immutable" ] && ok "immutable Cache-Control intact" || no "Cache-Control" "got '$CC'"
  H=access-control-expose-headers; local EX; EX=$(hdr -H 'Range: bytes=0-' "$ORIGIN/$PROBE_FILE")
  echo "$EX" | grep -qi 'content-range' && ok "CORS exposes Content-Range" || no "CORS expose" "got '$EX'"
  S=$(curl -s -A "$UA" -o /dev/null -w '%{http_code}' -I "$ORIGIN/$BIG_FILE")
  [ "$S" = "200" ] && ok "boot-critical file present ($BIG_FILE)" || no "boot-critical file" "got $S"
  S=$(curl -s -A "$UA" -o /dev/null -w '%{http_code}' -I "$ORIGIN/current/wide.parquet")
  [ "$S" = "302" ] && ok "/current/ alias still redirects (302)" || no "/current/ alias" "got $S"
  echo
  if [ "$fail" -ne 0 ]; then echo "VERIFICATION FAILED."; return 1; fi
  echo "All production checks passed."
}

if [ "${1:-}" = "--verify" ]; then
  EXPECT=yes; [ "${2:-}" = "--expect-shim" ] && EXPECT="${3:-yes}"
  verify "$EXPECT"; exit $?
fi

# --- preflight --------------------------------------------------------------------
PREV=$(current_version)
echo "==> Production Worker 'isamples-data' — currently active version: ${PREV:-unknown}"
echo "==> Route: data.isamples.org/*   Account: $ACCOUNT_ID_EXPECTED"
echo "==> Branch: $(git rev-parse --abbrev-ref HEAD) @ $(git rev-parse --short HEAD)  (clean: $([ -z "$(git status --porcelain -- src wrangler.toml)" ] && echo yes || echo NO))"
echo "==> Rollback command (keep this):"
echo "      $0 --rollback ${PREV:-<version-id>}"
echo
echo "==> Production today:"
verify no || { echo "!! Production does not look like the expected pre-deploy state. Stop and look."; exit 1; }
[ "${1:-}" = "--preflight" ] && exit 0

# --- confirm + deploy -------------------------------------------------------------
echo
read -r -p "Canary verified with ./deploy-canary.sh --verify just now? Type 'canary ok' to deploy to PRODUCTION: " ans
[ "$ans" = "canary ok" ] || { echo "Aborted."; exit 1; }
echo "==> Deploying to production (wrangler.toml, route data.isamples.org/*)"
if ! npx wrangler deploy -c wrangler.toml | tee /tmp/prod_deploy.log; then
  echo "!! wrangler deploy failed. Production is unchanged (previous version ${PREV:-?} still active)."; exit 1
fi
NEW=$(current_version)
echo "==> Active version now: ${NEW:-unknown}  (was ${PREV:-unknown})"
echo "==> Waiting for the edge to pick up the new version"
for i in $(seq 1 30); do
  S=$(curl -s -A "$UA" -o /dev/null -w '%{http_code}' -I -H 'Range: bytes=0-' "$ORIGIN/$PROBE_FILE")
  [ "$S" = "206" ] && { echo "  shim visible after ~$((i*2))s"; break; }
  sleep 2
done
echo
if ! verify yes; then
  echo
  echo "!! Verification FAILED. Roll back now:"
  echo "      $0 --rollback ${PREV:-<version-id>}"
  exit 1
fi
echo
echo "───────────────────────────────────────────────────────────────"
echo "Deployed. Next:"
echo "  1. Open https://isamples.org/explorer.html, DevTools console: expect ZERO"
echo "     'falling back to full HTTP read' warnings; Network tab total ~3-4 MB, not ~74 MB."
echo "  2. ISAMPLES_DATA_ORIGIN=$ORIGIN pytest -q tests/test_data_origin_contract.py  (expect 5 passed / XPASS)"
echo "  3. Remove the xfail marker in tests/test_data_origin_contract.py, merge #348."
echo "  4. ./deploy-canary.sh --teardown"
echo "Rollback if anything looks wrong:  $0 --rollback ${PREV:-<version-id>}"
echo "───────────────────────────────────────────────────────────────"
