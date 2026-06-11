# Frontend-derived parquet pipeline — reproducible, AI-free.
#
#   make test       # fast fixture tests (no network, no big data) — the CI gate
#   make wide       # download + checksum the canonical wide parquet
#   make derived    # build the derived files from $(WIDE) into $(OUTDIR)
#   make validate   # algebraic trust gate over the built files (non-zero exit on failure)
#   make all        # wide -> derived -> validate
#
# Override on the command line, e.g.:
#   make all WIDE_URL=https://data.isamples.org/isamples_202604_wide.parquet TAG=isamples_202606
#
# Requirements: python with `pip install -r scripts/requirements.txt`, plus
# network access on first run (DuckDB pulls the h3 community extension).

PY      ?= python
WIDE_URL ?= https://data.isamples.org/isamples_202604_wide.parquet
OUTDIR  ?= build/derived
WIDE    ?= $(OUTDIR)/wide.parquet
TAG     ?= isamples_dev
BUILD   := scripts/build_frontend_derived.py
VALIDATE := scripts/validate_frontend_derived.py

.PHONY: help test wide derived validate all clean
help:
	@grep -E '^#   make' Makefile | sed 's/^#   /  /'

# Fast, deterministic fixture tests — the gate a human (or CI) runs without any AI.
test:
	$(PY) -m pytest tests/test_frontend_derived.py -q

wide: $(WIDE)
$(WIDE):
	@mkdir -p $(OUTDIR)
	curl -fSL -o $(WIDE) "$(WIDE_URL)"
	@echo "sha256: $$(shasum -a 256 $(WIDE) | cut -d' ' -f1)  $(WIDE)"

derived: $(WIDE)
	$(PY) $(BUILD) --wide $(WIDE) --outdir $(OUTDIR) --tag $(TAG) --skip wide_h3

validate:
	$(PY) $(VALIDATE) --dir $(OUTDIR) --tag $(TAG)

all: wide derived validate

clean:
	rm -rf $(OUTDIR)
