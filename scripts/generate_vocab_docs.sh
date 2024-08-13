#!/bin/bash
#
# Regenerates the vocabulary markdown files from the GH sources
#
#

# get the core sample type vocabularies
SCRIPT_FOLDER="$(dirname ${0})"
#SOURCE_BASE="https://raw.githubusercontent.com/isamplesorg/metadata/develop/src/vocabularies/"

SOURCE_BASE="https://raw.githubusercontent.com/isamplesorg/vocabularies/main/vocabulary/"

SOURCES=("material_type.ttl" "sampled_feature_type.ttl" "material_sample_object_type.ttl")
DEST_FOLDER="models/generated/vocabularies/"
mkdir -p "${DEST_FOLDER}"
for src in ${SOURCES[@]}; do
    fname="${src%%.*}.md"
    echo "Generating ${fname}..."
#    python "${SCRIPT_FOLDER}/vocab2md.py" "${SOURCE_BASE}${src}" > "${DEST_FOLDER}${fname}"
    vocab markdown "${SOURCE_BASE}${src}" > "${DEST_FOLDER}${fname}"
done

#
#**************************************************************************************************
# add extension vocabularies here. Each extension will be in a separate github repo,
#  and might include more than one vocabulary.  Any public repo that contains appropriatedly
#  formatted SKOS turtle files should work. See SHACL shape files for validating iSamples SKOS
#  at https://github.com/smrgeoinfo/vocab_tools/tree/main/vocab_tools/data

# Earth Science extension
SOURCE_BASE="https://raw.githubusercontent.com/isamplesorg/metadata_profile_earth_science/main/vocabulary/"
SOURCES=("earthenv_material_extension_mineral_group.ttl" "earthenv_material_extension_rock_sediment.ttl" "earthenv_sampled_feature_role.ttl" "earthenv_specimen_type.ttl")
DEST_FOLDER="models/generated/extensions/"
mkdir -p "${DEST_FOLDER}"
for src in ${SOURCES[@]}; do
    fname="${src%%.*}.md"
    echo "Generating ${fname}..."
#    python "${SCRIPT_FOLDER}/vocab2md.py" "${SOURCE_BASE}${src}" > "${DEST_FOLDER}${fname}"
    vocab markdown "${SOURCE_BASE}${src}" > "${DEST_FOLDER}${fname}"
done

SOURCE_BASE="https://raw.githubusercontent.com/isamplesorg/metadata_profile_archaeology/main/vocabulary/"
SOURCES=("opencontext_material_extension.ttl" "opencontext_materialsampletype.ttl")
DEST_FOLDER="models/generated/extensions/"
mkdir -p "${DEST_FOLDER}"
for src in ${SOURCES[@]}; do
    fname="${src%%.*}.md"
    echo "Generating ${fname}..."
#    python "${SCRIPT_FOLDER}/vocab2md.py" "${SOURCE_BASE}${src}" > "${DEST_FOLDER}${fname}"
    vocab markdown "${SOURCE_BASE}${src}" > "${DEST_FOLDER}${fname}"
done

SOURCE_BASE="https://raw.githubusercontent.com/isamplesorg/metadata_profile_biology/main/vocabulary/"
SOURCES=("biology_sampledfeature_extension.ttl")
DEST_FOLDER="models/generated/extensions/"
mkdir -p "${DEST_FOLDER}"
for src in ${SOURCES[@]}; do
    fname="${src%%.*}.md"
    echo "Generating ${fname}..."
#    python "${SCRIPT_FOLDER}/vocab2md.py" "${SOURCE_BASE}${src}" > "${DEST_FOLDER}${fname}"
    vocab markdown "${SOURCE_BASE}${src}" > "${DEST_FOLDER}${fname}"
done

echo "Done."

