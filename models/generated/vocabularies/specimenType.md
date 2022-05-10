---
comment: | 
  WARNING: This file is generated. Any edits will be lost!
title: "iSamples Specimen Type Vocabulary"
date: "2022-05-10T10:01:07.659577+00:00"
subtitle: |
  Broad categories to classify any kind of physical specimen
execute:
  echo: false
categories: ["vocabulary"]
---

Namespace: 
[`https://w3id.org/isample/vocabulary/specimentype/0.9/specimentypevocabulary`](https://w3id.org/isample/vocabulary/specimentype/0.9/specimentypevocabulary)

**History**

* 2022-01-07 SMR Change base URI to https://w3id.org/isample/vocabulary/, setting up resolution using w3id. Make the conceptScheme and ontology. Add Dublin core imports.
* 2022-03-11 SMR change definitions from rdfs:comment to skos:definition. Minor fixes in definitions. Add skos matches to URIs from other vocabularies.

**Concepts**

- [Physical specimen](#physicalspecimen)
    - [Any aggregation specimen](#anyaggregation)
        - [Anthropogenic aggregation](#anthropogenicaggregation)
        - [Biome aggregation specimen](#biomeaggregation)
        - [Aggregation](#genericaggregation)
    - [Artifact](#artifact)
    - [Any biological specimen](#biologicalspecimen)
        - [Biome aggregation specimen](#biomeaggregation)
        - [Organism part](#organismpart)
        - [Organism product](#organismproduct)
        - [Whole organism specimen](#wholeorganism)
    - [Fossil](#fossil)
    - [Liquid or gas](#liquidorgas)
    - [Other solid object](#othersolidobject)
    - [Research product](#researchproduct)
        - [Analytical preparation](#analyticalpreparation)
        - [Experiment product](#experimentalproduct)

##  Physical specimen

[]{#physicalspecimen}

Concept: [`physicalspecimen`](https://w3id.org/isample/vocabulary/specimentype/0.9/physicalspecimen)

top concept in specimen type hierarchy.  Represents any physical
specimen.

###  Any aggregation specimen

[]{#anyaggregation}

Concept: [`anyaggregation`](https://w3id.org/isample/vocabulary/specimentype/0.9/anyaggregation)

Child of:
 [`physicalspecimen`](#physicalspecimen)

Sample consists of a bunch of material fragments, not related to the
same object (e.g. not a bunch of broken pot sherds that might be
reassembled), but taken together representative of the sampled
feature. Examples: loose soil, sediment, crushed rock,  particulate,
bunches of unrelated pot sherd, human production waste, filtrates and
residues. The sample requires some kind of container to keep it
together. Cores of loosely consolidated material are considered 'piece
of solid material' because the internal parts have spatial
relationships (e.g. upper part, lower part).

####  Anthropogenic aggregation

[]{#anthropogenicaggregation}

Concept: [`anthropogenicaggregation`](https://w3id.org/isample/vocabulary/specimentype/0.9/anthropogenicaggregation)

Child of:
 [`anyaggregation`](#anyaggregation)

Aggregation consists of fragments of material produced by human
activity,  not described individually, and generally not all
originating from the same object.  Includes pottery in an excavation
unit that gets an aggregate description, production waste, production
raw-materials, or other residues (broken bits of plaster from an
destroyed wall), synthetic powders.

####  Biome aggregation specimen

[]{#biomeaggregation}

Concept: [`biomeaggregation`](https://w3id.org/isample/vocabulary/specimentype/0.9/biomeaggregation)

Child of:
 [`anyaggregation`](#anyaggregation)
 [`biologicalspecimen`](#biologicalspecimen)

Specimen is an aggregation of whole or fragmentary parts of multiple
organisms, microscopic or megascopic, representative of some site.

####  Aggregation

[]{#genericaggregation}

Concept: [`genericaggregation`](https://w3id.org/isample/vocabulary/specimentype/0.9/genericaggregation)

Child of:
 [`anyaggregation`](#anyaggregation)

An aggregate specimen that is not biogenic or composed of
anthropogenic material fragments.  Examples: loose soil or sediment
(e.g. in a bag), rock chips, particulate filtrate or precipitate; rock
powders.

###  Artifact

[]{#artifact}

Concept: [`artifact`](https://w3id.org/isample/vocabulary/specimentype/0.9/artifact)

Child of:
 [`physicalspecimen`](#physicalspecimen)

An object made (manufactured, shaped, modified) by a human being, or
precursor hominid. Include a set of pieces belonging originally to a
single object and treated as a single specimen.

###  Any biological specimen

[]{#biologicalspecimen}

Concept: [`biologicalspecimen`](https://w3id.org/isample/vocabulary/specimentype/0.9/biologicalspecimen)

Child of:
 [`physicalspecimen`](#physicalspecimen)

Specimen for which the sampled feature is one or more living organisms
from a particular biome context, megascopic or microscopic

####  Biome aggregation specimen

[]{#biomeaggregation}

Concept: [`biomeaggregation`](https://w3id.org/isample/vocabulary/specimentype/0.9/biomeaggregation)

Child of:
 [`anyaggregation`](#anyaggregation)
 [`biologicalspecimen`](#biologicalspecimen)

Specimen is an aggregation of whole or fragmentary parts of multiple
organisms, microscopic or megascopic, representative of some site.

####  Organism part

[]{#organismpart}

Concept: [`organismpart`](https://w3id.org/isample/vocabulary/specimentype/0.9/organismpart)

Child of:
 [`biologicalspecimen`](#biologicalspecimen)

Part of an organism, e.g. a tissue sample, plant leaf, flower, bird
feather. Include internal parts not composed of organic material (e.g.
teeth, bone), and hard body parts that are not shed (hoof, horn, tusk,
claw).  Hair is tricky, include here for now.  Does not necessarily
imply existance of parent sample. Not fossilized; generally includes
organism parts native to deposits of Holocene to Recent age.

####  Organism product

[]{#organismproduct}

Concept: [`organismproduct`](https://w3id.org/isample/vocabulary/specimentype/0.9/organismproduct)

Child of:
 [`biologicalspecimen`](#biologicalspecimen)

Specimen is a thing produced by some organism, generally not composed
of organic material or including biological tissue, e.g. Shell,
antler, egg shell, coral skeleton (organic tissue not included), fecal
matter, cocoon, web.  Consider internal parts not composed of organic
material (e.g. teeth, bone) and hard body parts that are not shed
(hoof, horn, tusk) to be organism parts.

####  Whole organism specimen

[]{#wholeorganism}

Concept: [`wholeorganism`](https://w3id.org/isample/vocabulary/specimentype/0.9/wholeorganism)

Child of:
 [`biologicalspecimen`](#biologicalspecimen)

Specimen consists of the bodies of one or more entire organisms of the
same species, from any kingdom. Note that are also 'solid object’

###  Fossil

[]{#fossil}

Concept: [`fossil`](https://w3id.org/isample/vocabulary/specimentype/0.9/fossil)

Child of:
 [`physicalspecimen`](#physicalspecimen)

Specimen is the remains of one or more organisms preserved in rock;
includes whole body, body parts (usually bone or shell), and trace
fossils. An organism or organism part becomes a fossil when it has
undergone some fossilization process that generally entails physical
and chemical changes akin to diagenesis in a sedimentary rock. Trace
fossils are manifestations of biologic activity preserved in a rock
body (typically sedimentary), without included preserved body parts.

###  Liquid or gas

[]{#liquidorgas}

Concept: [`liquidorgas`](https://w3id.org/isample/vocabulary/specimentype/0.9/liquidorgas)

Child of:
 [`physicalspecimen`](#physicalspecimen)

Liquid, gas, or mixed dominantly fluid phases, necessarily in some
kind of container to maintain identity. Might include minor solid
particles. Container typically human made, but also includes natural
fluid container, e.g. fluid inclusion in a mineral grain.  Includes
colloids, foams, gels, suspensions. The sampled feature is the fluid
substance; fluid samples collected to analyze the contained biome
should be considered *Biome Aggregation*

###  Other solid object

[]{#othersolidobject}

Concept: [`othersolidobject`](https://w3id.org/isample/vocabulary/specimentype/0.9/othersolidobject)

Child of:
 [`physicalspecimen`](#physicalspecimen)

Single piece of material not one of the other types, e.g. rock
specimen, mineral specimen, core. Ice and permafrost are considered
solid materials.

###  Research product

[]{#researchproduct}

Concept: [`researchproduct`](https://w3id.org/isample/vocabulary/specimentype/0.9/researchproduct)

Child of:
 [`physicalspecimen`](#physicalspecimen)

Specimen is a product of some research workflow, e.g. a thin section,
an XRF pellet, a grain mount, SEM stub, synthetic rock or mineral ...
In general there should be a link to a parent specimen from which this
was derived.  Might be aggregation (e.g. a synthetic material powder)
or a solid object.

####  Analytical preparation

[]{#analyticalpreparation}

Concept: [`analyticalpreparation`](https://w3id.org/isample/vocabulary/specimentype/0.9/analyticalpreparation)

Child of:
 [`researchproduct`](#researchproduct)

Specimen is a product of processing required for some observation
procedure, e.g. thin section, XRF bead, SEM stub, rock powder. If
identified separately, this should have a ‘parent’ link to the
original sample

####  Experiment product

[]{#experimentalproduct}

Concept: [`experimentalproduct`](https://w3id.org/isample/vocabulary/specimentype/0.9/experimentalproduct)

Child of:
 [`researchproduct`](#researchproduct)

Specimen is product of an experimental procedure (e.g. synthetic
material)


