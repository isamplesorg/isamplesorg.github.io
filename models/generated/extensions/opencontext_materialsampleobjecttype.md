---
comment: | 
  WARNING: This file is generated. Any edits will be lost!
title: "Open Context vocabulary extension for material sample object type"
date: "2025-12-11T02:41:36.548073+00:00"
subtitle: |
  categories for kinds of sample objects specific to archaeological studies
  Vocabulary created based on summary of 'type' values found in OpenContext sample descriptions. This is a bottom-up vocabulary intended as a first draft and demonstration of a material sample type extension for the Open Context community in the iSamples context. Most of the categories are subclasses of msot:Artifact, except for 'bone object' which is a msot:OrganismPart.
execute:
  echo: false
categories: ["vocabulary"]
---

Source: 
[`https://raw.githubusercontent.com/isamplesorg/metadata_profile_archaeology/main/vocabulary/opencontext_materialsampleobjecttype.ttl`](https://raw.githubusercontent.com/isamplesorg/metadata_profile_archaeology/main/vocabulary/opencontext_materialsampleobjecttype.ttl)


Namespace: 
[`https://w3id.org/isample/opencontext/materialsampleobjecttype/oc_msotvocab`](https://w3id.org/isample/opencontext/materialsampleobjecttype/oc_msotvocab)

**History**

* 2024-09-13 SMR remove version number from URI

**Concepts**

- [Artifact](#artifact)
    - [Architectural element](#architecturalelement)
    - [Clothing](#clothing)
    - [Coin](#coin)
    - [Container object](#containerobject)
    - [Domestic item](#domesticitem)
    - [Ornament](#ornament)
    - [Photograph](#photograph)
    - [Pot sherd](#sherd)
    - [Tile](#tile)
    - [Utility item](#utilityitem)
    - [Weapon](#weapon)

- [Organism part](#organismpart)
    - [Bone object](#peiceofbone)

##  Artifact

[]{#artifact}

Concept: [`artifact`](https://w3id.org/isample/vocabulary/materialsampleobjecttype/artifact)

An object made (manufactured, shaped, modified) by a human being, or
precursor hominid. Include a set of pieces belonging originally to a
single object and treated as a single specimen.

###  Architectural element

[]{#architecturalelement}

Concept: [`architecturalelement`](https://w3id.org/isample/opencontext/materialsampleobjecttype/architecturalelement)

Child of:
 [`artifact`](#artifact)

Artifact that was part of a building.

###  Clothing

[]{#clothing}

Concept: [`clothing`](https://w3id.org/isample/opencontext/materialsampleobjecttype/clothing)

Child of:
 [`artifact`](#artifact)

Item intended to be worn to cover the (human) body

###  Coin

[]{#coin}

Concept: [`coin`](https://w3id.org/isample/opencontext/materialsampleobjecttype/coin)

Child of:
 [`artifact`](#artifact)

peice of metal issued by some authority and recognized as money.

###  Container object

[]{#containerobject}

Concept: [`containerobject`](https://w3id.org/isample/opencontext/materialsampleobjecttype/containerobject)

Child of:
 [`artifact`](#artifact)

Item designed to contain some fluid, granular material, or other items
for preservation, transportation or display.

###  Domestic item

[]{#domesticitem}

Concept: [`domesticitem`](https://w3id.org/isample/opencontext/materialsampleobjecttype/domesticitem)

Child of:
 [`artifact`](#artifact)

item intended for household use.

###  Ornament

[]{#ornament}

Concept: [`ornament`](https://w3id.org/isample/opencontext/materialsampleobjecttype/ornament)

Child of:
 [`artifact`](#artifact)

item intended for decoration.

###  Photograph

[]{#photograph}

Concept: [`photograph`](https://w3id.org/isample/opencontext/materialsampleobjecttype/photograph)

Child of:
 [`artifact`](#artifact)

image produced by the action of light on a chemically sensitive
surface, preserved on paper, glass or other physical substrate.

###  Pot sherd

[]{#sherd}

Concept: [`sherd`](https://w3id.org/isample/opencontext/materialsampleobjecttype/sherd)

Child of:
 [`artifact`](#artifact)

fragment of pottery

###  Tile

[]{#tile}

Concept: [`tile`](https://w3id.org/isample/opencontext/materialsampleobjecttype/tile)

Child of:
 [`artifact`](#artifact)

flat or curved piece of fired clay, stone, or concrete used especially
for roofs, floors, or walls and often for ornamental work

###  Utility item

[]{#utilityitem}

Concept: [`utilityitem`](https://w3id.org/isample/opencontext/materialsampleobjecttype/utilityitem)

Child of:
 [`artifact`](#artifact)

Item intended for use in manufacture, construction, agriculture or
other work activity.

###  Weapon

[]{#weapon}

Concept: [`weapon`](https://w3id.org/isample/opencontext/materialsampleobjecttype/weapon)

Child of:
 [`artifact`](#artifact)

Item for use in combat, hunting, or self defense


##  Organism part

[]{#organismpart}

Concept: [`organismpart`](https://w3id.org/isample/vocabulary/materialsampleobjecttype/organismpart)

Part of an organism, e.g. a tissue sample, plant leaf, flower, bird
feather. Include internal parts not composed of organic material (e.g.
teeth, bone), and hard body parts that are not shed (hoof, horn, tusk,
claw).  Hair is tricky, include here for now.  Does not necessarily
imply existance of parent sample. Not fossilized; generally includes
organism parts native to deposits of Holocene to Recent age.

###  Bone object

[]{#peiceofbone}

Concept: [`peiceofbone`](https://w3id.org/isample/opencontext/materialsampleobjecttype/peiceofbone)

Child of:
 [`organismpart`](#organismpart)

Sample is an individual bone or part of a bone from an animal.


