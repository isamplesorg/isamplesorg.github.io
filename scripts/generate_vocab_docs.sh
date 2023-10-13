#!/bin/bash
#
# Regenerates the vocabulary markdown files from the GH sources
#
#
SCRIPT_FOLDER="$(dirname ${0})"
SOURCE_BASE="https://raw.githubusercontent.com/isamplesorg/metadata/relation-vocabulary/src/vocabularies/"
SOURCES=("materialType.ttl" "sampledFeature.ttl" "specimenType.ttl" "relation-test.ttl")
DEST_FOLDER="models/generated/vocabularies/"
mkdir -p "${DEST_FOLDER}"
for src in ${SOURCES[@]}; do
    fname="${src%%.*}.qmd"
    echo "Generating ${fname}..."
    python "${SCRIPT_FOLDER}/vocab2md.py" "${SOURCE_BASE}${src}" > "${DEST_FOLDER}${fname}"
done
echo "Done."
