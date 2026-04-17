#!/usr/bin/env python3
"""Check whether Eric Kansa's OC PQG files on GCS have drifted from our R2 mirror.

Reads our latest.json + the per-file manifests from data.isamples.org/oc_pqg/,
HEADs the GCS source, and reports whether upstream has a newer version.

Exit codes:
  0 — in sync, no drift
  1 — drift detected (GCS has a different etag from what we've mirrored)
  2 — probe failure (network error, malformed response, etc.)

Run manually for now:
    python scripts/check_oc_pqg_drift.py

Later: wire to GitHub Actions cron.
"""
import json
import sys
import urllib.request

LATEST_URL = "https://data.isamples.org/oc_pqg/latest.json"
GCS_BASE = "https://storage.googleapis.com/opencontext-parquet/"
GCS_FILES = {
    "narrow": "oc_isamples_pqg.parquet",
    "wide":   "oc_isamples_pqg_wide.parquet",
}


def fetch_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "isamples-oc-drift-check/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def head(url, timeout=20):
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "isamples-oc-drift-check/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return dict(r.headers)


def main() -> int:
    try:
        latest = fetch_json(LATEST_URL)
    except Exception as e:
        print(f"ERROR: could not fetch {LATEST_URL}: {e}", file=sys.stderr)
        return 2

    drift_any = False
    for flavor, gcs_name in GCS_FILES.items():
        flavor_ptr = latest.get(flavor)
        if not flavor_ptr:
            print(f"ERROR: latest.json has no entry for {flavor!r}", file=sys.stderr)
            return 2

        try:
            manifest = fetch_json(f"https://data.isamples.org/{flavor_ptr['manifest']}")
        except Exception as e:
            print(f"ERROR: could not fetch manifest for {flavor}: {e}", file=sys.stderr)
            return 2

        try:
            gcs_headers = head(f"{GCS_BASE}{gcs_name}")
        except Exception as e:
            print(f"ERROR: HEAD {GCS_BASE}{gcs_name}: {e}", file=sys.stderr)
            return 2

        gcs_etag = gcs_headers.get("ETag", "").strip('"')
        gcs_last_modified = gcs_headers.get("Last-Modified", "")
        our_etag = manifest.get("source_etag", "")
        our_updated = manifest.get("source_updated", "")

        in_sync = gcs_etag == our_etag
        state = "in sync" if in_sync else "DRIFT"
        print(f"[{flavor}] {state}")
        print(f"    mirrored: etag={our_etag} updated={our_updated}")
        print(f"    gcs:      etag={gcs_etag} last-modified={gcs_last_modified}")
        if not in_sync:
            drift_any = True

    return 1 if drift_any else 0


if __name__ == "__main__":
    sys.exit(main())
