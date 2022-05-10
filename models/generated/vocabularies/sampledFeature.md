---
comment: | 
  WARNING: This file is generated. Any edits will be lost!
title: "Sampled Feature Type vocabulary"
date: "2022-05-10T11:27:47.557590+00:00"
subtitle: |
  Categories to specify the broad context that a sample is intended to represent.
execute:
  echo: false
categories: ["vocabulary"]
---

Namespace: 
[`https://w3id.org/isample/vocabulary/sampledfeature/0.9/sampledfeaturevocabulary`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/sampledfeaturevocabulary)

**History**

* 2021-12-10 SMR add missing skos:inScheme statements
* 2022-01-07 SMR change to https://w3id.org/isample/ uri base, make the ConceptScheme an ontology as well. For uploading to ESIP COR and w3id resolution redirect set up. Add some mappings to other ontologies using seeAlso, closeMatch, narrowMatch.
* 2022-03-11 SMR change definitions from rdfs:comment to skos:definition. Minor fixes in definitions. Add skos matches to URIs from other vocabularies. Fix typo in glacierenvrionment URI (changed the URI to glacierenvironment)
* Remove Marine biome, Subaerial terrestrial environment, Subaqueous terrestrial environment per github issue https://github.com/isamplesorg/metadata/issues/41. Make Experiment setting and Laboratory or curatorial environemtn  subclasses of Active human occupation site.

**Concepts**

- [Any sampled feature](#anysampledfeature)
    - [Anthropogenic environment](#anthropogenicenvironment)
        - [Active human occupation site](#activehumanoccupationsite)
            - [Experiment setting](#experimentsetting)
            - [Laboratory or curatorial environment](#laboratorycuratorialenvironment)
        - [Site of past human activities](#pasthumanoccupationsite)
    - [Earth environment](#earthenvironment)
        - [Atmosphere](#atmosphere)
        - [Earth interior](#earthinterior)
        - [Earth Surface](#earthsurface)
            - [Lake, river, or stream bed](#lakeriverstreambottom)
            - [Marine water body bottom](#marinewaterbodybottom)
            - [Subaerial surface environment](#subaerialsurfaceenvironment)
        - [Glacier environment ](#glacierenvironment)
        - [Subsurface fluid reservoir](#subsurfacefluidreservoir)
        - [Water body](#waterbody)
            - [Marine environment](#marinewaterbody)
            - [Terrestrial water body](#terrestrialwaterbody)
    - [Extraterrestrial environment](#extraterrestrialenvironment)

##  Any sampled feature

[]{#anysampledfeature}

Concept: [`anysampledfeature`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/anysampledfeature)

Top concept in sampled feature type vocabulary.

###  Anthropogenic environment

[]{#anthropogenicenvironment}

Concept: [`anthropogenicenvironment`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/anthropogenicenvironment)

Child of:
 [`anysampledfeature`](#anysampledfeature)

Sampled feature is produced by or related to human activity past or
present.

####  Active human occupation site

[]{#activehumanoccupationsite}

Concept: [`activehumanoccupationsite`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/activehumanoccupationsite)

Child of:
 [`anthropogenicenvironment`](#anthropogenicenvironment)

Specimen samples materials or objects produced by current or ongoing
human activity

#####  Experiment setting

[]{#experimentsetting}

Concept: [`experimentsetting`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/experimentsetting)

Child of:
 [`activehumanoccupationsite`](#activehumanoccupationsite)

Sampled feature is the expermental set up that produced the sample.

#####  Laboratory or curatorial environment

[]{#laboratorycuratorialenvironment}

Concept: [`laboratorycuratorialenvironment`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/laboratorycuratorialenvironment)

Child of:
 [`activehumanoccupationsite`](#activehumanoccupationsite)

specimen samples environment in a laboratory; e.g. lab blank
measurements.

####  Site of past human activities

[]{#pasthumanoccupationsite}

Concept: [`pasthumanoccupationsite`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/pasthumanoccupationsite)

Child of:
 [`anthropogenicenvironment`](#anthropogenicenvironment)

specimen samples a place where humans have been and left evidence of
their activity. Includes prehistoric and paleo hominid sites

###  Earth environment

[]{#earthenvironment}

Concept: [`earthenvironment`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/earthenvironment)

Child of:
 [`anysampledfeature`](#anysampledfeature)

specimen samples the natural earth environment

See Also:

* [<http://purl.bioontology.org/ontology/MESH/D004777>](http://purl.bioontology.org/ontology/MESH/D004777)
* [<http://semanticscience.org/resource/SIO_000955>](http://semanticscience.org/resource/SIO_000955)

####  Atmosphere

[]{#atmosphere}

Concept: [`atmosphere`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/atmosphere)

Child of:
 [`earthenvironment`](#earthenvironment)

specimen samples the Earth's atmosphere

See Also:

* [obo:ENVO_01000267](http://purl.obolibrary.org/obo/ENVO_01000267)
* [obo:RBO_00000018](http://purl.obolibrary.org/obo/RBO_00000018)

####  Earth interior

[]{#earthinterior}

Concept: [`earthinterior`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/earthinterior)

Child of:
 [`earthenvironment`](#earthenvironment)

Specimen samples solid material within the earth (fluids in pore space
in earth interior sample 'subsurface fluid reservoir'

####  Earth Surface

[]{#earthsurface}

Concept: [`earthsurface`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/earthsurface)

Child of:
 [`earthenvironment`](#earthenvironment)

Specimen samples the interface between solid earth and hydrosphere or
atmosphere. Includes samples representing things collected on the
surface, or in the uppermost part of the material below the surface.
Not including recently deposited sediment that has not been modified
by interaction with the surface environment.

#####  Lake, river, or stream bed

[]{#lakeriverstreambottom}

Concept: [`lakeriverstreambottom`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/lakeriverstreambottom)

Child of:
 [`earthsurface`](#earthsurface)

Specimen samples the solid Earth interface with a lake or flowing
water body

#####  Marine water body bottom

[]{#marinewaterbodybottom}

Concept: [`marinewaterbodybottom`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/marinewaterbodybottom)

Child of:
 [`earthsurface`](#earthsurface)

Specimen samples the solid Earth interface with marine or brackish
water body. Includes benthic boundary layer:  the bottom layer of
water and the uppermost layer of sediment directly influenced by the
overlying water

#####  Subaerial surface environment

[]{#subaerialsurfaceenvironment}

Concept: [`subaerialsurfaceenvironment`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/subaerialsurfaceenvironment)

Child of:
 [`earthsurface`](#earthsurface)

Specimen samples the  interface between solid Earth and atmosphere.
Sample is collected on the surface, or immediately below surface (zone
of bioturbation). Include soil ‘O’ horizon and ‘biomantle’. Soil
horizons below surface, or sediment in active deposition (no soil
development) is considered part of solid Earth.

####  Glacier environment

[]{#glacierenvironment}

Concept: [`glacierenvironment`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/glacierenvironment)

Child of:
 [`earthenvironment`](#earthenvironment)

Sample of ice or water from a glacier, ice sheet, ice shelf, iceberg.
Does not include various environments adjacent to glacier.

####  Subsurface fluid reservoir

[]{#subsurfacefluidreservoir}

Concept: [`subsurfacefluidreservoir`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/subsurfacefluidreservoir)

Child of:
 [`earthenvironment`](#earthenvironment)

Specimen samples fluid that resides in fractures or intergranular
porosity in the solid earth.

####  Water body

[]{#waterbody}

Concept: [`waterbody`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/waterbody)

Child of:
 [`earthenvironment`](#earthenvironment)

specimen samples the hydrosphere

#####  Marine environment

[]{#marinewaterbody}

Concept: [`marinewaterbody`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/marinewaterbody)

Child of:
 [`waterbody`](#waterbody)

specimen samples marine hydrosphere

See Also:

* [obo:ENVO_01000686](http://purl.obolibrary.org/obo/ENVO_01000686)

#####  Terrestrial water body

[]{#terrestrialwaterbody}

Concept: [`terrestrialwaterbody`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/terrestrialwaterbody)

Child of:
 [`waterbody`](#waterbody)

specimen samples terrestrial hydrosphere-- lake, other standing water,
or a flowing water body (river, stream..) Include saline water in
terrestrial evaporite environments.

###  Extraterrestrial environment

[]{#extraterrestrialenvironment}

Concept: [`extraterrestrialenvironment`](https://w3id.org/isample/vocabulary/sampledfeature/0.9/extraterrestrialenvironment)

Child of:
 [`anysampledfeature`](#anysampledfeature)

specimen samples environment outside of solid earth, hydrosphere, or
atmosphere.


