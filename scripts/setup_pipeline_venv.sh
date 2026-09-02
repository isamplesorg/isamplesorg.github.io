#!/usr/bin/env bash
# Create (or refresh) an isolated Python environment for the one-shot
# reproducible-build scripts in this directory (also used by `make`, see
# Makefile's PY var), pinned exactly per scripts/requirements.txt. Never
# installs into a shared/ambient interpreter (e.g. pyenv's `myenv`, used by
# other projects): the pin in scripts/requirements.txt didn't itself drift
# between 2026-08-28 and 2026-08-31 — nothing had ever installed FROM it
# into an isolated env, so the pipeline ran against whatever duckdb `myenv`
# happened to have (1.4.4, then silently 1.5.5, from an unrelated project's
# upgrade), and that ambient drift changed the pipeline's output bytes. See
# provenance/isamples_202609/step9_clean_rerun_2026-08-31.md in the
# isamples-suite provenance repo (private supporting evidence, not in this
# repo) for the incident.
#
# Usage:
#   bash scripts/setup_pipeline_venv.sh
#   make derived TAG=isamples_dev          # Makefile defaults PY to this venv
#   scripts/.venv/bin/python scripts/enrich_wide_with_oc_thumbnails.py ...
#
# Requires `uv` (https://docs.astral.sh/uv/). Mirrors the hermetic pattern
# the `pqg` repo's step 1 already uses (its own `uv.lock`), applied here via
# a pinned requirements.txt instead of a uv project, since these are
# one-shot scripts rather than an installable package. Not a full lockfile:
# transitive dependencies, the Python version, and `uv` itself are still
# resolver-chosen (see scripts/requirements.txt's header comment).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VENV=scripts/.venv
uv venv "$VENV" --quiet
uv pip install --python "$VENV/bin/python" --quiet -r scripts/requirements.txt
"$VENV/bin/python" -c "import duckdb, pandas, pyarrow, rdflib; print(f'duckdb {duckdb.__version__}  pandas {pandas.__version__}  pyarrow {pyarrow.__version__}  rdflib {rdflib.__version__}')"
echo "Pipeline venv ready: $VENV"
