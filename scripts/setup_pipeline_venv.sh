#!/usr/bin/env bash
# Create (or refresh) an isolated Python environment for the one-shot
# reproducible-build scripts in this directory, pinned exactly per
# scripts/requirements.txt. Never installs into a shared/ambient
# interpreter (e.g. pyenv's `myenv`, used by other projects) — that's how
# scripts/requirements.txt's duckdb==1.4.4 pin silently drifted to 1.5.5
# between 2026-08-28 and 2026-08-31 (see
# provenance/isamples_202609/step9_clean_rerun_2026-08-31.md in the
# isamples-suite provenance repo): nothing actually installed FROM this
# file into an isolated env, so ambient package upgrades unrelated to this
# project changed the pipeline's output bytes without anyone touching this
# repo.
#
# Usage:
#   bash scripts/setup_pipeline_venv.sh
#   scripts/.venv/bin/python scripts/enrich_wide_with_oc_thumbnails.py ...
#
# Requires `uv` (https://docs.astral.sh/uv/). Mirrors the hermetic pattern
# the `pqg` repo's step 1 already uses (its own `uv.lock`), applied here via
# a pinned requirements.txt instead of a uv project, since these are
# one-shot scripts rather than an installable package.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VENV=scripts/.venv
uv venv "$VENV" --quiet
uv pip install --python "$VENV/bin/python" --quiet -r scripts/requirements.txt

echo "Pipeline venv ready: $VENV"
"$VENV/bin/python" -c "import duckdb, pandas, pyarrow, rdflib; print(f'duckdb {duckdb.__version__}  pandas {pandas.__version__}  pyarrow {pyarrow.__version__}  rdflib {rdflib.__version__}')"
