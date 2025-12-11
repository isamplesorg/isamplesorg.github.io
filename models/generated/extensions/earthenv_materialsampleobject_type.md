---
comment: | 
  WARNING: This file is generated. Any edits will be lost!
title: "Earth and Environmental Science extension -  Material sample type"
date: "2025-12-11T02:41:32.972715+00:00"
subtitle: |
  This concept scheme contains skos concepts for categorizing kinds of Earth Material sample types, extending the iSamples Material Sample Object Type vocabulary. Defintions from SESAR, ODM2, wikipedia, ESS-DIVE, and other sources; sources are cited with each term.
execute:
  echo: false
categories: ["vocabulary"]
---

Source: 
[`https://raw.githubusercontent.com/isamplesorg/metadata_profile_earth_science/main/vocabulary/earthenv_materialsampleobject_type.ttl`](https://raw.githubusercontent.com/isamplesorg/metadata_profile_earth_science/main/vocabulary/earthenv_materialsampleobject_type.ttl)


Namespace: 
[`https://w3id.org/isample/earthenv/esmaterialsample/essampletype`](https://w3id.org/isample/earthenv/esmaterialsample/essampletype)

**History**

* 2023-07-07 SMR add solid material sample and broader relations from classes it subsumes.
* 2023-07-27 SMR modify base specimen type vocabulary, add 'Non biologic solid object' to replace 'solid material sample', change broader relations in this vocab to use that as parent class where appropriate. 'Solid material sample' is too closely linked to material type, created confusion. Intention is a specimen category for solid objects that are not biologic. Obviously there is some overlap with Research specimens.
* 2024-07-15 SMR fix import to base vocabulary on renamed material_sample_type vocabulary, change from specimentypevocabulary to materialsampleobjecttype/conceptscheme

**Concepts**

- [Analytical preparation](#analyticalpreparation)
    - [Cell culture](#cellculture)
    - [Dissolved chemical fraction](#dissolvedchemicalfraction)
        - [Eluate](#eluate)
    - [FIB lamella](#fiblamella)
    - [Glass slide smear](#glassslidesmear)
    - [Individual solid cube](#individualsolidcube)
    - [Magnetic fraction](#magneticfraction)
    - [Mechanical fraction](#mechanicalfraction)
    - [Mineral separate](#mineralseparate)
        - [Magnetic fraction](#magneticfraction)
        - [Non-magnetic fraction](#nonmagneticfraction)
    - [Sectioned specimen](#mountedsection)
        - [Thick section](#thicksection)
        - [Thin section](#thinsection)
            - [Polished thin section](#polishedthinsection)
        - [Ultra thin section](#ultrathinsection)
    - [Non-magnetic fraction](#nonmagneticfraction)
    - [Peel](#peel)
    - [Prepared powder](#preparedpowder)
        - [Prepared rock powder](#preparedrockpowder)
    - [Pressed pellet](#pressedpellet)
    - [Residual material](#residualmaterial)
    - [Slab](#slab)

- [Bundle biome aggregation](#bundlebiomeaggregation)
    - [Cell culture](#cellculture)

- [Fluid in container](#fluidincontainer)
    - [Direct fluid sample](#directfluidsample)
    - [Dissolved chemical fraction](#dissolvedchemicalfraction)
        - [Eluate](#eluate)
    - [Processed fluid sample](#processedfluidsample)
        - [Filtrate](#filtrate)

- [Generic aggregation](#genericaggregation)
    - [Boxed core](#boxedcore)
    - [Composite sample](#compositesample)
        - [Chip Channel Sample](#chipchannelsample)
        - [High Grade Sample](#highgradesample)
        - [Site composite sample](#sitecompositesample)
    - [Core catcher](#corecatcher)
    - [Cuttings](#cuttings)
    - [Dredge](#dredge)
    - [Material captured in filter](#materialcapturedinfilter)
    - [Mechanical fraction](#mechanicalfraction)
    - [Mineral separate](#mineralseparate)
        - [Magnetic fraction](#magneticfraction)
        - [Non-magnetic fraction](#nonmagneticfraction)
    - [Natural aggregate specimen](#naturalaggregate)
    - [Prepared powder](#preparedpowder)
        - [Prepared rock powder](#preparedrockpowder)
    - [TEM grid](#temgrid)
    - [Trawl](#trawl)

- [Other solid object](#othersolidobject)
    - [Dust wipe](#dustwipe)
    - [Glass slide smear](#glassslidesmear)
    - [Peel](#peel)

- [Solid material sample](#solidmaterialsample)
    - [Core](#core)
    - [Core half round](#corehalfround)
    - [Core piece](#corepiece)
    - [Core quarter round](#corequarterround)
    - [Core section](#coresection)
    - [Core subpeice](#coresubpeice)
    - [FIB lamella](#fiblamella)
    - [Individual solid cube](#individualsolidcube)
    - [Individual solid cylinder](#individualsolidcylinder)
    - [Meteorite](#meteorite)
    - [Mineral specimen](#mineralspecimen)
    - [Sectioned specimen](#mountedsection)
        - [Thick section](#thicksection)
        - [Thin section](#thinsection)
            - [Polished thin section](#polishedthinsection)
        - [Ultra thin section](#ultrathinsection)
    - [Pressed pellet](#pressedpellet)
    - [Rock hand sample](#rockhandsample)
    - [Slab](#slab)
    - [U-channel sample](#uchannelsample)
    - [Atom probe tip](#atomprobetip)
    - [Chip](#chip)
    - [Microtome slice](#microtomeslice)
    - [Mounted specimen](#mountedspecimen)
        - [Polished mounted specimen](#polishedmountedspecimen)
    - [Particle](#particle)

##  Analytical preparation

[]{#analyticalpreparation}

Concept: [`analyticalpreparation`](https://w3id.org/isample/vocabulary/materialsampleobjecttype/analyticalpreparation)

Specimen is a product of processing required for some observation
procedure, e.g. thin section, XRF bead, SEM stub, rock powder. If
identified separately, this should have a ‘parent’ link to the
original sample

###  Cell culture

[]{#cellculture}

Concept: [`cellculture`](https://w3id.org/isample/earthenv/esmaterialsample/cellculture)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`bundlebiomeaggregation`](#bundlebiomeaggregation)

a collection of cells are grown under controlled conditions, generally
outside of their natural environment

###  Dissolved chemical fraction

[]{#dissolvedchemicalfraction}

Concept: [`dissolvedchemicalfraction`](https://w3id.org/isample/earthenv/esmaterialsample/dissolvedchemicalfraction)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`fluidincontainer`](#fluidincontainer)

A fluid concentrating some constituent of interest from a parent
sample. The dissolved constituent is actually the sample material of
interest.

####  Eluate

[]{#eluate}

Concept: [`eluate`](https://w3id.org/isample/earthenv/esmaterialsample/eluate)

Child of:
 [`dissolvedchemicalfraction`](#dissolvedchemicalfraction)

The fluid product that contains the analyte of interest washed from a
chromatography column

###  FIB lamella

[]{#fiblamella}

Concept: [`fiblamella`](https://w3id.org/isample/earthenv/esmaterialsample/fiblamella)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`solidmaterialsample`](#solidmaterialsample)

very thin sheet of solid material milled from a larger sample using a
focused ion beam. Used for TEM analysis.

###  Glass slide smear

[]{#glassslidesmear}

Concept: [`glassslidesmear`](https://w3id.org/isample/earthenv/esmaterialsample/glassslidesmear)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`othersolidobject`](#othersolidobject)

sample from a cell culture (or other microparticulate suspension)
spread into a thin layer on a glass slide for optical investigation

###  Individual solid cube

[]{#individualsolidcube}

Concept: [`individualsolidcube`](https://w3id.org/isample/earthenv/esmaterialsample/individualsolidcube)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`solidmaterialsample`](#solidmaterialsample)

A sample that is a prepared cube of material, intended as a sample of
that material.

###  Magnetic fraction

[]{#magneticfraction}

Concept: [`magneticfraction`](https://w3id.org/isample/earthenv/esmaterialsample/magneticfraction)

Child of:
 [`mineralseparate`](#mineralseparate)
 [`analyticalpreparation`](#analyticalpreparation)

a collection of particles separated from a crushed rock sample based
on their attraction to a magnet.

###  Mechanical fraction

[]{#mechanicalfraction}

Concept: [`mechanicalfraction`](https://w3id.org/isample/earthenv/esmaterialsample/mechanicalfraction)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`genericaggregation`](#genericaggregation)

defined by sample preparation involving mechanical processing, e.g.
grain size, density, or grain shape separation.

###  Mineral separate

[]{#mineralseparate}

Concept: [`mineralseparate`](https://w3id.org/isample/earthenv/esmaterialsample/mineralseparate)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`genericaggregation`](#genericaggregation)

an aggregation of particles of the same mineral extracted and
concentrated from a rock.

####  Magnetic fraction

[]{#magneticfraction}

Concept: [`magneticfraction`](https://w3id.org/isample/earthenv/esmaterialsample/magneticfraction)

Child of:
 [`mineralseparate`](#mineralseparate)
 [`analyticalpreparation`](#analyticalpreparation)

a collection of particles separated from a crushed rock sample based
on their attraction to a magnet.

####  Non-magnetic fraction

[]{#nonmagneticfraction}

Concept: [`nonmagneticfraction`](https://w3id.org/isample/earthenv/esmaterialsample/nonmagneticfraction)

Child of:
 [`mineralseparate`](#mineralseparate)
 [`analyticalpreparation`](#analyticalpreparation)

collection of particles from a crushed rock sample based on their lack
of attraction to a magnet

###  Sectioned specimen

[]{#mountedsection}

Concept: [`mountedsection`](https://w3id.org/isample/earthenv/esmaterialsample/mountedsection)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`solidmaterialsample`](#solidmaterialsample)

a thin slice of a solid material that has been mounted on a glass
slide for study

####  Thick section

[]{#thicksection}

Concept: [`thicksection`](https://w3id.org/isample/earthenv/esmaterialsample/thicksection)

Child of:
 [`mountedsection`](#mountedsection)

Thick sections are like thin sections, but milled to a greater
thickness. Typcially polished on one or both sides and used for fluid
or melt inclusion studies, Raman analyses, and infrared spectroscopy
analyses, and SEM or electron microprobe. The standard thickness for a
fluid inclusion thick section is 50 micrometers, but thick sections
can be made at any thickness.  Thick sections can be attached to a
glass slide, or can be prepared so that they can be removed from their
mount as a stand-alone slice of rock.

####  Thin section

[]{#thinsection}

Concept: [`thinsection`](https://w3id.org/isample/earthenv/esmaterialsample/thinsection)

Child of:
 [`mountedsection`](#mountedsection)

thin sliver of rock cut from a sample with a diamond saw and ground
optically flat, and then mounted on a glass slide and ground smooth
using progressively finer abrasive grit until the sample is 30 microns
thick.

#####  Polished thin section

[]{#polishedthinsection}

Concept: [`polishedthinsection`](https://w3id.org/isample/earthenv/esmaterialsample/polishedthinsection)

Child of:
 [`thinsection`](#thinsection)

a thin section that has its free surface polished until perfectly
planar and free of pits and scratches. Used for reflected light
petrography and for electron microprobe or SEM investigation.

####  Ultra thin section

[]{#ultrathinsection}

Concept: [`ultrathinsection`](https://w3id.org/isample/earthenv/esmaterialsample/ultrathinsection)

Child of:
 [`mountedsection`](#mountedsection)

An ordinary thin section that is attached to the glass slide using a
soluble cement such as Canada balsam (soluble in ethanol) to allow
both sides to be worked on. The section is polished on both sides
using a fine diamond paste until it has a thickness in the range of
2-12 microns. This technique has been used to study the microstructure
of very fine-grained carbonate rocks, and also in the preparation of
mineral and rock specimens for transmission electron microscopy.

###  Non-magnetic fraction

[]{#nonmagneticfraction}

Concept: [`nonmagneticfraction`](https://w3id.org/isample/earthenv/esmaterialsample/nonmagneticfraction)

Child of:
 [`mineralseparate`](#mineralseparate)
 [`analyticalpreparation`](#analyticalpreparation)

collection of particles from a crushed rock sample based on their lack
of attraction to a magnet

###  Peel

[]{#peel}

Concept: [`peel`](https://w3id.org/isample/earthenv/esmaterialsample/peel)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`othersolidobject`](#othersolidobject)

Acetate peels are made by polishing a planar surface on a sample,
etching it with acid to give it some relief, and then chemically
melting a piece of acetate onto that surface. The acetate is then
pulled off for examination under a microscope. The acetate preserves a
fingerprint of the internal structure of the sample surface. Used in
paleontology to study complex fossils, e.g. bryozoan.

###  Prepared powder

[]{#preparedpowder}

Concept: [`preparedpowder`](https://w3id.org/isample/earthenv/esmaterialsample/preparedpowder)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`genericaggregation`](#genericaggregation)

distinguish from particulate in that particulate is sampled as a
micron-size aggregate, whereas this material is ground to a powder for
subsequent analysis; it is a powder as a function of some preparation
process (e.g. chemical precipitation)

####  Prepared rock powder

[]{#preparedrockpowder}

Concept: [`preparedrockpowder`](https://w3id.org/isample/earthenv/esmaterialsample/preparedrockpowder)

Child of:
 [`preparedpowder`](#preparedpowder)

a powder manufactured by pulverizing a rock.

###  Pressed pellet

[]{#pressedpellet}

Concept: [`pressedpellet`](https://w3id.org/isample/earthenv/esmaterialsample/pressedpellet)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`solidmaterialsample`](#solidmaterialsample)

a sample prepared by grinding a parent sample to a fine powder, mixing
it with a binder, and pressing the mixture into a die at a pressure of
between 15 and 35 tons to produce a solid disc for subsequent
analysis, typically by X-Ray fluorescence.

###  Residual material

[]{#residualmaterial}

Concept: [`residualmaterial`](https://w3id.org/isample/earthenv/esmaterialsample/residualmaterial)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)

Sample is material remaining after processing to extract some other
components of interest from the sample.

###  Slab

[]{#slab}

Concept: [`slab`](https://w3id.org/isample/earthenv/esmaterialsample/slab)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`solidmaterialsample`](#solidmaterialsample)

a relatively planar rock sample,cut from a large sample to produce a
tabular peice of rock with the irregular outline of the original
sample on the diameter where the cut was mate.


##  Bundle biome aggregation

[]{#bundlebiomeaggregation}

Concept: [`bundlebiomeaggregation`](https://w3id.org/isample/vocabulary/materialsampleobjecttype/bundlebiomeaggregation)

An aggregation of whole organisms representative of some biome

###  Cell culture

[]{#cellculture}

Concept: [`cellculture`](https://w3id.org/isample/earthenv/esmaterialsample/cellculture)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`bundlebiomeaggregation`](#bundlebiomeaggregation)

a collection of cells are grown under controlled conditions, generally
outside of their natural environment


##  Fluid in container

[]{#fluidincontainer}

Concept: [`fluidincontainer`](https://w3id.org/isample/vocabulary/materialsampleobjecttype/fluidincontainer)

Specimen is a container whose contents are liquid, gas, or mixed
dominantly fluid phases that is the actual sample material. Fluid
might include minor solid particles. Container typically human made,
but also includes natural fluid container, e.g. fluid inclusion in a
mineral grain.  Includes colloids, foams, gels, suspensions. The
sample is the fluid substance; fluid samples collected to analyze the
contained biome should be considered 'Biome Aggregation'

###  Direct fluid sample

[]{#directfluidsample}

Concept: [`directfluidsample`](https://w3id.org/isample/earthenv/esmaterialsample/directfluidsample)

Child of:
 [`fluidincontainer`](#fluidincontainer)

a fluid collected from the sampled feature (e.g. water body,
hydrothermal vent, atmosphere...) with no processing. (e.g.
filtration, addition of preservatives).

###  Dissolved chemical fraction

[]{#dissolvedchemicalfraction}

Concept: [`dissolvedchemicalfraction`](https://w3id.org/isample/earthenv/esmaterialsample/dissolvedchemicalfraction)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`fluidincontainer`](#fluidincontainer)

A fluid concentrating some constituent of interest from a parent
sample. The dissolved constituent is actually the sample material of
interest.

####  Eluate

[]{#eluate}

Concept: [`eluate`](https://w3id.org/isample/earthenv/esmaterialsample/eluate)

Child of:
 [`dissolvedchemicalfraction`](#dissolvedchemicalfraction)

The fluid product that contains the analyte of interest washed from a
chromatography column

###  Processed fluid sample

[]{#processedfluidsample}

Concept: [`processedfluidsample`](https://w3id.org/isample/earthenv/esmaterialsample/processedfluidsample)

Child of:
 [`fluidincontainer`](#fluidincontainer)

fluid sample that has been processed in some way during or after
collection, e.g. by filtering, addition of preservatives.

####  Filtrate

[]{#filtrate}

Concept: [`filtrate`](https://w3id.org/isample/earthenv/esmaterialsample/filtrate)

Child of:
 [`processedfluidsample`](#processedfluidsample)

A sample that has gone through a filtration process to separate solids
from fluids (liquids or gases), using a filter medium through which
only the fluid can pass. Must be associated with a filter size.


##  Generic aggregation

[]{#genericaggregation}

Concept: [`genericaggregation`](https://w3id.org/isample/vocabulary/materialsampleobjecttype/genericaggregation)

An aggregate specimen that is not biogenic or composed of
anthropogenic material fragments.  Examples: loose soil or sediment
(e.g. in a bag), rock chips, particulate filtrate or precipitate; rock
powders.

###  Boxed core

[]{#boxedcore}

Concept: [`boxedcore`](https://w3id.org/isample/earthenv/esmaterialsample/boxedcore)

Child of:
 [`genericaggregation`](#genericaggregation)

A collection of core peices that are stored in an individual box.
Typically the box will contain core peices from the same core.

###  Composite sample

[]{#compositesample}

Concept: [`compositesample`](https://w3id.org/isample/earthenv/esmaterialsample/compositesample)

Child of:
 [`genericaggregation`](#genericaggregation)

a sample composed of multiple peices, representative of some material,
or representative of some site. The peices do not all originate from
the same object.

####  Chip Channel Sample

[]{#chipchannelsample}

Concept: [`chipchannelsample`](https://w3id.org/isample/earthenv/esmaterialsample/chipchannelsample)

Child of:
 [`compositesample`](#compositesample)

small chips of rock collected over a specified interval, with the
objective to obtain a representative sample for that interval. Most of
the time chip channel samples are collected in succession along a
sample line which is laid out in advance using a tape.  The freshest
material possible is sampled, preferably chipping directly from
bedrock. Sample intervals are set at a specified width, usually
ranging from 30cm to 7m. Due to the method of sampling, chip channel
samples tend to be rather large (up to 20 pounds for a five foot
interval)

####  High Grade Sample

[]{#highgradesample}

Concept: [`highgradesample`](https://w3id.org/isample/earthenv/esmaterialsample/highgradesample)

Child of:
 [`compositesample`](#compositesample)

in mineral exploration, selective pieces of the most highly
mineralized material from a mineralize site, intentionally excluding
less mineralized material. A high grade sample might be collected to
indicate what the best possible values are, or to provide material for
certain types of trace element analyses.

####  Site composite sample

[]{#sitecompositesample}

Concept: [`sitecompositesample`](https://w3id.org/isample/earthenv/esmaterialsample/sitecompositesample)

Child of:
 [`compositesample`](#compositesample)

an aggregation of peices of uniform material collected over some area
(generally greater than 2.5m across). These are the ideal
'representative' samples used in mineral exploration. A composite
sample might be collected to determine the background values of trace
elements in a particular type of rock, or to determine if ore grade
mineralization is present over a large area.

###  Core catcher

[]{#corecatcher}

Concept: [`corecatcher`](https://w3id.org/isample/earthenv/esmaterialsample/corecatcher)

Child of:
 [`genericaggregation`](#genericaggregation)

material recovered from the core catcher of a sedimentary core and
which is treated as a separate section from the core. The core catcher
is a device at the bottom of the core barrel that prevents the core
from sliding out while the barrel is retrieved from the hole.
(http://publications.iodp.org/proceedings/323/102/102_.htm)

###  Cuttings

[]{#cuttings}

Concept: [`cuttings`](https://w3id.org/isample/earthenv/esmaterialsample/cuttings)

Child of:
 [`genericaggregation`](#genericaggregation)

unconsolidated Earth material produced by the grinding action of a
drill bit during drilling of a borehole.

###  Dredge

[]{#dredge}

Concept: [`dredge`](https://w3id.org/isample/earthenv/esmaterialsample/dredge)

Child of:
 [`genericaggregation`](#genericaggregation)

an aggregation of material sampled by dragging a collection bucket
(dredge) across the bottom of a water body

###  Material captured in filter

[]{#materialcapturedinfilter}

Concept: [`materialcapturedinfilter`](https://w3id.org/isample/earthenv/esmaterialsample/materialcapturedinfilter)

Child of:
 [`genericaggregation`](#genericaggregation)

A material sample captured in filter, for example from a water sample
that was filtered. Must be associated with filter size field.

###  Mechanical fraction

[]{#mechanicalfraction}

Concept: [`mechanicalfraction`](https://w3id.org/isample/earthenv/esmaterialsample/mechanicalfraction)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`genericaggregation`](#genericaggregation)

defined by sample preparation involving mechanical processing, e.g.
grain size, density, or grain shape separation.

###  Mineral separate

[]{#mineralseparate}

Concept: [`mineralseparate`](https://w3id.org/isample/earthenv/esmaterialsample/mineralseparate)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`genericaggregation`](#genericaggregation)

an aggregation of particles of the same mineral extracted and
concentrated from a rock.

####  Magnetic fraction

[]{#magneticfraction}

Concept: [`magneticfraction`](https://w3id.org/isample/earthenv/esmaterialsample/magneticfraction)

Child of:
 [`mineralseparate`](#mineralseparate)
 [`analyticalpreparation`](#analyticalpreparation)

a collection of particles separated from a crushed rock sample based
on their attraction to a magnet.

####  Non-magnetic fraction

[]{#nonmagneticfraction}

Concept: [`nonmagneticfraction`](https://w3id.org/isample/earthenv/esmaterialsample/nonmagneticfraction)

Child of:
 [`mineralseparate`](#mineralseparate)
 [`analyticalpreparation`](#analyticalpreparation)

collection of particles from a crushed rock sample based on their lack
of attraction to a magnet

###  Natural aggregate specimen

[]{#naturalaggregate}

Concept: [`naturalaggregate`](https://w3id.org/isample/earthenv/esmaterialsample/naturalaggregate)

Child of:
 [`genericaggregation`](#genericaggregation)

E.g beach sand, soil, river sediment, scoop of regolith.
Specimen is aggregate of non-consolidated material formed by natural
processes. Particles have not been intentionally modified from the
sampled feature.

###  Prepared powder

[]{#preparedpowder}

Concept: [`preparedpowder`](https://w3id.org/isample/earthenv/esmaterialsample/preparedpowder)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`genericaggregation`](#genericaggregation)

distinguish from particulate in that particulate is sampled as a
micron-size aggregate, whereas this material is ground to a powder for
subsequent analysis; it is a powder as a function of some preparation
process (e.g. chemical precipitation)

####  Prepared rock powder

[]{#preparedrockpowder}

Concept: [`preparedrockpowder`](https://w3id.org/isample/earthenv/esmaterialsample/preparedrockpowder)

Child of:
 [`preparedpowder`](#preparedpowder)

a powder manufactured by pulverizing a rock.

###  TEM grid

[]{#temgrid}

Concept: [`temgrid`](https://w3id.org/isample/earthenv/esmaterialsample/temgrid)

Child of:
 [`genericaggregation`](#genericaggregation)

FIB sections and microtome slices set onto a small grid for handling,
transport, and analysis using a transmission electron microscope
(TEM). The grid itself can be given a single sample identifier
(similar to how there are multiple grains in a grain mount). The
linkage from the individual samples in the grid to their parent
sample(s) should be documented

###  Trawl

[]{#trawl}

Concept: [`trawl`](https://w3id.org/isample/earthenv/esmaterialsample/trawl)

Child of:
 [`genericaggregation`](#genericaggregation)

an aggregation of biogenic or non-biogenic material extracted from a
water body


##  Other solid object

[]{#othersolidobject}

Concept: [`othersolidobject`](https://w3id.org/isample/vocabulary/materialsampleobjecttype/othersolidobject)

Single piece of material not one of the other types.

###  Dust wipe

[]{#dustwipe}

Concept: [`dustwipe`](https://w3id.org/isample/earthenv/esmaterialsample/dustwipe)

Child of:
 [`othersolidobject`](#othersolidobject)

a pre-weighed and packaged paper towel (wipe) used to wipe over a
surface to collect particulates from the surface

###  Glass slide smear

[]{#glassslidesmear}

Concept: [`glassslidesmear`](https://w3id.org/isample/earthenv/esmaterialsample/glassslidesmear)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`othersolidobject`](#othersolidobject)

sample from a cell culture (or other microparticulate suspension)
spread into a thin layer on a glass slide for optical investigation

###  Peel

[]{#peel}

Concept: [`peel`](https://w3id.org/isample/earthenv/esmaterialsample/peel)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`othersolidobject`](#othersolidobject)

Acetate peels are made by polishing a planar surface on a sample,
etching it with acid to give it some relief, and then chemically
melting a piece of acetate onto that surface. The acetate is then
pulled off for examination under a microscope. The acetate preserves a
fingerprint of the internal structure of the sample surface. Used in
paleontology to study complex fossils, e.g. bryozoan.


##  Solid material sample

[]{#solidmaterialsample}

Concept: [`solidmaterialsample`](https://w3id.org/isample/vocabulary/materialsampleobjecttype/solidmaterialsample)


###  Core

[]{#core}

Concept: [`core`](https://w3id.org/isample/earthenv/esmaterialsample/core)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

Cylinder of rock or sediment extracted from within the earth, and
representing the entire sample extracted during a single borehole
drilling event.  Typically using some rotary drilling technology. In
many cases the core is extracted in segments that are 'core sections'.
A core from a single borehole is rarely a continous unbroken object;
commonly parts of the core will break up during drilling or
extraction, leaving gaps or sections that are granular material. Cores
are normally composed of consolidated ('solid') material, but in some
cases loosely consolidated material might be recovered, and considered
sediment or tephra. To be called 'core' the material must be
sufficiently consolidated to maintain a cylindrical shape. A core
hasPart (hasChild) 'Core section'

###  Core half round

[]{#corehalfround}

Concept: [`corehalfround`](https://w3id.org/isample/earthenv/esmaterialsample/corehalfround)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

Half-cylindrical peice of consolidated material produced by along-axis
split of a core whole round along a selected diameter .    Has childOf
relation to core section or core, core section, or Core peice from
which is was split

###  Core piece

[]{#corepiece}

Concept: [`corepiece`](https://w3id.org/isample/earthenv/esmaterialsample/corepiece)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

A cylindrical peice of consolidated earth material extracted as a
single solid object between breaks in recovery of core from a
borehole. has parent core section

###  Core quarter round

[]{#corequarterround}

Concept: [`corequarterround`](https://w3id.org/isample/earthenv/esmaterialsample/corequarterround)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

a partial cylindrical peice of consolidated material created by along-
axis split of a core half round. Has Parent core half round

###  Core section

[]{#coresection}

Concept: [`coresection`](https://w3id.org/isample/earthenv/esmaterialsample/coresection)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

Segment of a core representing some interval along the well bore.
Child of Core

###  Core subpeice

[]{#coresubpeice}

Concept: [`coresubpeice`](https://w3id.org/isample/earthenv/esmaterialsample/coresubpeice)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

A peice of consolidated material broken from a core peice. has Parent
core peice or core section

###  FIB lamella

[]{#fiblamella}

Concept: [`fiblamella`](https://w3id.org/isample/earthenv/esmaterialsample/fiblamella)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`solidmaterialsample`](#solidmaterialsample)

very thin sheet of solid material milled from a larger sample using a
focused ion beam. Used for TEM analysis.

###  Individual solid cube

[]{#individualsolidcube}

Concept: [`individualsolidcube`](https://w3id.org/isample/earthenv/esmaterialsample/individualsolidcube)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`solidmaterialsample`](#solidmaterialsample)

A sample that is a prepared cube of material, intended as a sample of
that material.

###  Individual solid cylinder

[]{#individualsolidcylinder}

Concept: [`individualsolidcylinder`](https://w3id.org/isample/earthenv/esmaterialsample/individualsolidcylinder)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

A cylindrical peice of consolidated material not obtained by
subsurface drilling.  Cores drilled for paleomagnetic analysis are a
common example. Tree ring cores are another...

###  Meteorite

[]{#meteorite}

Concept: [`meteorite`](https://w3id.org/isample/earthenv/esmaterialsample/meteorite)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

A meteorite is a solid object that originates in interplanetary space
and survives passage through an atmosphere to reach the surface of a
planet or moon.

###  Mineral specimen

[]{#mineralspecimen}

Concept: [`mineralspecimen`](https://w3id.org/isample/earthenv/esmaterialsample/mineralspecimen)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

a solid object consisting of one particular mineral, or several
minerals intended to be representative of one or more of the mineral
species.

###  Sectioned specimen

[]{#mountedsection}

Concept: [`mountedsection`](https://w3id.org/isample/earthenv/esmaterialsample/mountedsection)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`solidmaterialsample`](#solidmaterialsample)

a thin slice of a solid material that has been mounted on a glass
slide for study

####  Thick section

[]{#thicksection}

Concept: [`thicksection`](https://w3id.org/isample/earthenv/esmaterialsample/thicksection)

Child of:
 [`mountedsection`](#mountedsection)

Thick sections are like thin sections, but milled to a greater
thickness. Typcially polished on one or both sides and used for fluid
or melt inclusion studies, Raman analyses, and infrared spectroscopy
analyses, and SEM or electron microprobe. The standard thickness for a
fluid inclusion thick section is 50 micrometers, but thick sections
can be made at any thickness.  Thick sections can be attached to a
glass slide, or can be prepared so that they can be removed from their
mount as a stand-alone slice of rock.

####  Thin section

[]{#thinsection}

Concept: [`thinsection`](https://w3id.org/isample/earthenv/esmaterialsample/thinsection)

Child of:
 [`mountedsection`](#mountedsection)

thin sliver of rock cut from a sample with a diamond saw and ground
optically flat, and then mounted on a glass slide and ground smooth
using progressively finer abrasive grit until the sample is 30 microns
thick.

#####  Polished thin section

[]{#polishedthinsection}

Concept: [`polishedthinsection`](https://w3id.org/isample/earthenv/esmaterialsample/polishedthinsection)

Child of:
 [`thinsection`](#thinsection)

a thin section that has its free surface polished until perfectly
planar and free of pits and scratches. Used for reflected light
petrography and for electron microprobe or SEM investigation.

####  Ultra thin section

[]{#ultrathinsection}

Concept: [`ultrathinsection`](https://w3id.org/isample/earthenv/esmaterialsample/ultrathinsection)

Child of:
 [`mountedsection`](#mountedsection)

An ordinary thin section that is attached to the glass slide using a
soluble cement such as Canada balsam (soluble in ethanol) to allow
both sides to be worked on. The section is polished on both sides
using a fine diamond paste until it has a thickness in the range of
2-12 microns. This technique has been used to study the microstructure
of very fine-grained carbonate rocks, and also in the preparation of
mineral and rock specimens for transmission electron microscopy.

###  Pressed pellet

[]{#pressedpellet}

Concept: [`pressedpellet`](https://w3id.org/isample/earthenv/esmaterialsample/pressedpellet)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`solidmaterialsample`](#solidmaterialsample)

a sample prepared by grinding a parent sample to a fine powder, mixing
it with a binder, and pressing the mixture into a die at a pressure of
between 15 and 35 tons to produce a solid disc for subsequent
analysis, typically by X-Ray fluorescence.

###  Rock hand sample

[]{#rockhandsample}

Concept: [`rockhandsample`](https://w3id.org/isample/earthenv/esmaterialsample/rockhandsample)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

individual peice of rock broken from an outcrop or larger peice of
rock.

###  Slab

[]{#slab}

Concept: [`slab`](https://w3id.org/isample/earthenv/esmaterialsample/slab)

Child of:
 [`analyticalpreparation`](#analyticalpreparation)
 [`solidmaterialsample`](#solidmaterialsample)

a relatively planar rock sample,cut from a large sample to produce a
tabular peice of rock with the irregular outline of the original
sample on the diameter where the cut was mate.

###  U-channel sample

[]{#uchannelsample}

Concept: [`uchannelsample`](https://w3id.org/isample/earthenv/esmaterialsample/uchannelsample)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

a rectangular prism of loosely consolidated sediment extracted from a
core segment. has parent core piece or core segment

###  Atom probe tip

[]{#atomprobetip}

Concept: [`atomprobetip`](https://w3id.org/isample/vocabulary/materialsampleobjecttype/atomprobetip)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

needle-shaped sample milled out of a larger sample with a focused ion
beam (FIB).

###  Chip

[]{#chip}

Concept: [`chip`](https://w3id.org/isample/vocabulary/materialsampleobjecttype/chip)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

Individual solid object intentionally broken off a larger solid object
sample. A Chip must have a documented parent sample.

###  Microtome slice

[]{#microtomeslice}

Concept: [`microtomeslice`](https://w3id.org/isample/vocabulary/materialsampleobjecttype/microtomeslice)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

Typically from TEM analysis. Slices are commonly deposited in a grid
contain with multiple slices and the grid will be given a single
sample name, not the individual slices within it. The provenance of
the slice from paticle to mounted specimen to slice should be
carefully documented
A very thin slice cut from a mounted specimen using a mocrotome or
ultramicrotome.

###  Mounted specimen

[]{#mountedspecimen}

Concept: [`mountedspecimen`](https://w3id.org/isample/vocabulary/materialsampleobjecttype/mountedspecimen)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

one or more solid objects embedded in a stabilizing matrix, typically
epoxy, metal, or paraffin to allow slicing through the mounted
object(s).

####  Polished mounted specimen

[]{#polishedmountedspecimen}

Concept: [`polishedmountedspecimen`](https://w3id.org/isample/earthenv/esmaterialsample/polishedmountedspecimen)

Child of:
 [`mountedspecimen`](#mountedspecimen)

Mounted specimen with polished surface exposing mounted material for
analysis

###  Particle

[]{#particle}

Concept: [`particle`](https://w3id.org/isample/vocabulary/materialsampleobjecttype/particle)

Child of:
 [`solidmaterialsample`](#solidmaterialsample)

Can also used for small peices broken from a 'Rock hand sample'.
OSIRIS-Rex definition specifies 'competent individual geologic sample
of any size'. 'Competent' interpreted to be equivalent to 'solid', or
'consolidated'.  The definition here is broader in that it includes
materials of any origin, but narrower in that it is restricted to
small objects.
A small individual solid object that is not one of the other sample
types.


