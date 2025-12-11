---
comment: | 
  WARNING: This file is generated. Any edits will be lost!
title: "Biology Extension: Basic taxon classes for biological entity"
date: "2025-12-11T02:41:37.197064+00:00"
subtitle: |
  This is a vocabulary to categorize sampled organisms (whole or part) according to taxonomic classes. Classes are based largely on taxonomy found in Wikipedia, particularly Whittaker's five kingdom system (1969) (https://en.wikipedia.org/wiki/Kingdom_(biology), https://doi.org/10.1126%2Fscience.163.3863.150). The intended use is in iSamples cross domain categorization of material samples, recognizing that there are multiple view for taxonomy and cladistics for the tree of life. This is a high level view intended for cross domain purposes, not expert analysis. Other extension vocabularies should be used for other taxonomic schemes
execute:
  echo: false
categories: ["vocabulary"]
---

Source: 
[`https://raw.githubusercontent.com/isamplesorg/metadata_profile_biology/main/vocabulary/biology_sampledfeature_extension.ttl`](https://raw.githubusercontent.com/isamplesorg/metadata_profile_biology/main/vocabulary/biology_sampledfeature_extension.ttl)


Namespace: 
[`https://w3id.org/isample/biology/biosampledfeature/biologicentityvocabulary`](https://w3id.org/isample/biology/biosampledfeature/biologicentityvocabulary)

**History**

* 2024-01-19 SMR add cross reference to GBIF taxonomy backbone where mapping was apparent.
* 2024-04-12 SMR.  Import of GEOME records show that many samples are classified as Kingdom Chromista, but this is missing from this vocabulary extension (https://github.com/isamplesorg/vocabularies/issues/17).  Hierarchy and classes reviewed; deprecate Protista and make it an alternate name in Eukaryotic microorganism class and update definition; add Chromista; update scope notes for Eukaryote.  Harmonize better with GBIF tree of life:  Make Mycetozoa subclass of Protozoa, not subclass of Amoebozoa, add Other Protozoa class for logical completeness. increment version to 1.1; these are not breaking changes, but addition of new class and hierarchy adjustments in protozoa are more than incremental.
* 2024-09-13 SMR remove version number from URI
* Based on draft DiSSCo specimen & collection classification, table 2, https://docs.google.com/document/d/19OPyOm9VF2qfI3M6RmJPvRfo8JlZ3tt0II05aGCyBHQ/ , with added classes to attempt a logical hierarchy.

**Concepts**

- [Biological entity](#biologicalentity)
    - [Eukaryote](#eukaryote)
        - [Algae](#algae)
        - [Animalia](#animalia)
            - [Arthropod](#arthropod)
                - [Arachnid](#arachnid)
                - [Crustaceans](#crustacea)
                - [Insect](#hexapoda)
                - [Myriapod](#myriapod)
                - [Other arthropod ](#otherarthropod)
            - [Mollusca](#mollusca)
            - [Other invertebrate ](#otherinvertebrate)
            - [Porifera](#porifera)
            - [Vertebrate ](#vertebrate)
                - [Amphibian](#amphibian)
                - [Bird](#bird)
                - [Fish](#fish)
                - [Mammal](#mammal)
                - [Reptile](#reptile)
        - [Chromista](#chromista)
        - [Eukaryotic microorganism](#eukaryoticmicroorganism)
        - [Fungi](#fungi)
            - [Macrofungi](#macrofungi)
            - [Microfungi](#microfungi)
        - [Plantae](#plantae)
            - [Non-vascular plant](#nonvascularplant)
            - [Other plant](#otherplant)
            - [Vascular seed plant](#vascularseedplant)
            - [Vascular spore plant](#vascularsportplant)
        - [Protozoa](#protozoa)
            - [Amoebozoa](#amoebozoa)
            - [Mycetozoa](#mycetozoa)
            - [Other Protozoa](#otherprotozoa)
    - [Lichen](#lichen)
    - [Plasmid](#plasmid)
    - [Prokaryote](#prokaryote)
        - [Archaea](#archaea)
        - [Bacteria](#bacteria)
    - [Virus](#virus)
        - [Other Virus](#othervirus)
        - [Phage](#phage)

##  Biological entity

[]{#biologicalentity}

Concept: [`biologicalentity`](https://w3id.org/isample/vocabulary/sampledfeature/biologicalentity)

Sampled feature is an organism. Use for samples that represent some
species of organism as the proximate sampled feature for which the
focus is not the environment that the organism inhabits.

###  Eukaryote

[]{#eukaryote}

Concept: [`eukaryote`](https://w3id.org/isample/biology/biosampledfeature/eukaryote)

Child of:
 [`biologicalentity`](#biologicalentity)

Organism whose cells have a nucleus. Includes all animals, plants,
fungi, and many unicellular organisms
(https://en.wikipedia.org/wiki/Eukaryote).   Eucaryote membranes are
flexible, and contain cholesterol. The membrane, nucleus, and
structures are supported by cross-connecting protein filaments. Cells
are ~10 times larger in radius relative to prokaryotes. Cells have
several types of internal enclosed compartments. Cell walls, if
present, are made from cellulose or chitin, in contrast to
prokaryotes. Eukaryotes have novel modes of direct body movement and
swimming, based on sensors, and the mode of reproduction uses sexual
combination. Their DNA is linear but wound up into nucleosomes and
then chromosomes. (https://doi.org/10.1016/B978-044452115-6/50050-6,
table 7-2). Eukaryotes can be considered a chimera; a combination of
archaeal and bacterial features that result in the cellular complexity
and distinctive characteristics.
(https://doi.org/10.1016/j.tim.2021.11.003).

####  Algae

[]{#algae}

Concept: [`algae`](https://w3id.org/isample/biology/biosampledfeature/algae)

Child of:
 [`eukaryote`](#eukaryote)

Informal term for a large and diverse group of photosynthetic
eukaryotic organisms.  Included organisms range from unicellular
microalgae, such as Chlorella, Prototheca and the diatoms, to
multicellular forms, such as the giant kelp, a large brown alga which
may grow up to 50 metres (160 ft) in length. Most are aquatic and
autotrophic (they generate food internally) and lack many of the
distinct cell and tissue types, such as stomata, xylem and phloem that
are found in land plants.  Includes red algae (Rhodophycophyta), brown
algae (Phaeophycophyta), and green algae (Chlorophyta).
https://en.wikipedia.org/wiki/Algae

####  Animalia

[]{#animalia}

Concept: [`animalia`](https://w3id.org/isample/biology/biosampledfeature/animalia)

Child of:
 [`eukaryote`](#eukaryote)

Animals are distinguished from other eukaryotes based on several key
characteristics, including: 1) animals are multicellular organisms 2)
Animals are heterotrophic, they obtain their food by consuming other
organisms or organic matter; 3) Animals lack cell walls; 4) Many
animals have a nervous system; 5) Most animals reproduce sexually
(Chat GPT)

See Also:

* [<https://www.gbif.org/species/1>](https://www.gbif.org/species/1)

#####  Arthropod

[]{#arthropod}

Concept: [`arthropod`](https://w3id.org/isample/biology/biosampledfeature/arthropod)

Child of:
 [`animalia`](#animalia)

invertebrate animals with an exoskeleton, a segmented body, and paired
jointed appendages. Arthropods form the phylum Arthropoda. They are
distinguished by their jointed limbs and cuticle made of chitin, often
mineralised with calcium carbonate. The arthropod body plan consists
of segments, each with a pair of appendages. Arthropods are
bilaterally symmetrical and their body possesses an external skeleton.
(https://en.wikipedia.org/wiki/Arthropod)

See Also:

* [<https://www.gbif.org/species/54>](https://www.gbif.org/species/54)

######  Arachnid

[]{#arachnid}

Concept: [`arachnid`](https://w3id.org/isample/biology/biosampledfeature/arachnid)

Child of:
 [`arthropod`](#arthropod)

a group of arthropods that share several key characteristics,
including two main body segments, four pairs of legs, lack of
antennae, simple eyes, and specialized feeding and defense structures
called chelicerae (ChatGPT)

See Also:

* [<https://en.wikipedia.org/wiki/Arachnid>](https://en.wikipedia.org/wiki/Arachnid)
* [<https://www.gbif.org/species/367>](https://www.gbif.org/species/367)

######  Crustaceans

[]{#crustacea}

Concept: [`crustacea`](https://w3id.org/isample/biology/biosampledfeature/crustacea)

Child of:
 [`arthropod`](#arthropod)

arthropod taxon which includes such animals as decapods, seed shrimp,
branchiopods, fish lice, krill, remipedes, isopods, barnacles,
copepods, amphipods and mantis shrimp.  crustaceans have an
exoskeleton, which they moult to grow. They are distinguished from
other groups of arthropods, such as insects, myriapods and
chelicerates, by the possession of biramous (two-parted) limbs, and by
their larval forms, such as the nauplius stage of branchiopods and
copepods. (https://en.wikipedia.org/wiki/Crustacean)

######  Insect

[]{#hexapoda}

Concept: [`hexapoda`](https://w3id.org/isample/biology/biosampledfeature/hexapoda)

Child of:
 [`arthropod`](#arthropod)

Include all hexapoda here; Insects are a group of hexapod arthropods
characterized by having three main body segments (head, thorax, and
abdomen), six legs, and wings in many species. All other hexapod
arthropods, such as springtails and diplurans, are not classified as
insects, but they share the same body plan of three main body segments
and six legs. However, they lack wings and other features that are
unique to insects. Therefore, all insects are hexapods, but not all
hexapods are insects. (ChatGPT)

See Also:

* [<https://www.gbif.org/species/174780701>](https://www.gbif.org/species/174780701)

######  Myriapod

[]{#myriapod}

Concept: [`myriapod`](https://w3id.org/isample/biology/biosampledfeature/myriapod)

Child of:
 [`arthropod`](#arthropod)

Arthropods such as millipedes and centipedes.
(https://en.wikipedia.org/wiki/Myriapoda). A group of arthropods that
have long, segmented body with numerous pairs of legs, simple eyes,
specialized mouthparts, and a primarily terrestrial habitat, which
distinguishes them from other arthropod groups such as insects and
crustaceans. (ChatGPT)

######  Other arthropod

[]{#otherarthropod}

Concept: [`otherarthropod`](https://w3id.org/isample/biology/biosampledfeature/otherarthropod)

Child of:
 [`arthropod`](#arthropod)

includes Chelicerata (horseshoe crabs, scorpions, and sea spiders),
Trilobitomorpha ( extinct trilobites), and  Pentastomida (parasitic
arthropods that infect the respiratory systems of reptiles and
mammals). (ChatGPT)

#####  Mollusca

[]{#mollusca}

Concept: [`mollusca`](https://w3id.org/isample/biology/biosampledfeature/mollusca)

Child of:
 [`animalia`](#animalia)

animals that have a soft body with a mantle, a radula (ribbon-like
structure covered in tiny teeth that is used to scrape food), a
muscular foot, an open circulatory system, and a visceral mass that
contains the internal organs, including the digestive, excretory, and
reproductive systems. (ChatGPT)

See Also:

* [<https://www.gbif.org/species/52>](https://www.gbif.org/species/52)

#####  Other invertebrate

[]{#otherinvertebrate}

Concept: [`otherinvertebrate`](https://w3id.org/isample/biology/biosampledfeature/otherinvertebrate)

Child of:
 [`animalia`](#animalia)

Includes Cnidaria (jellyfish, coral, anemones), Echinodermata
(starfish, sea urchins, sea cucumbers), Nematoda (roundworms),
Platyhelminthes (flatworms), Annelida (segmented worms), Ctenophora
(comb jellies), Brachiopoda (lamp shells), Bryozoa (moss animals),
Chaetognatha (arrow worms), Hemichordata (acorn worms),
Xenacoelomorpha (simple-bodied worms) (ChatGPT)

#####  Porifera

[]{#porifera}

Concept: [`porifera`](https://w3id.org/isample/biology/biosampledfeature/porifera)

Child of:
 [`animalia`](#animalia)

multicellular animals that have bodies full of pores and channels
allowing water to circulate through them, consisting of jelly-like
mesohyl sandwiched between two thin layers of cells.
(https://en.wikipedia.org/wiki/Sponge)

See Also:

* [<https://www.gbif.org/species/105>](https://www.gbif.org/species/105)

#####  Vertebrate

[]{#vertebrate}

Concept: [`vertebrate`](https://w3id.org/isample/biology/biosampledfeature/vertebrate)

Child of:
 [`animalia`](#animalia)

Animals that have a vertebral column, a cranium, an endoskeleton, a
well-developed muscular system, and an advanced nervous system
(ChatGPT);

######  Amphibian

[]{#amphibian}

Concept: [`amphibian`](https://w3id.org/isample/biology/biosampledfeature/amphibian)

Child of:
 [`vertebrate`](#vertebrate)

Vertebrates that have a dual life cycle, semi-permeable skin, absence
of scales and claws, a three-chambered heart, and dependence on water
for reproduction and survival (ChatGPT)

######  Bird

[]{#bird}

Concept: [`bird`](https://w3id.org/isample/biology/biosampledfeature/bird)

Child of:
 [`vertebrate`](#vertebrate)

Vertebrates that have feathers, lightweight, hollow bones, a beak, an
efficient respiratory system, and are warm-blooded. (ChatGPT)

######  Fish

[]{#fish}

Concept: [`fish`](https://w3id.org/isample/biology/biosampledfeature/fish)

Child of:
 [`vertebrate`](#vertebrate)

Vertebrates that have gills, scales, fins, are cold-blooded, and
commonly have a swim bladder; includes jawless fish, cartilaginous
fish and bony fish. (ChatGPT)

######  Mammal

[]{#mammal}

Concept: [`mammal`](https://w3id.org/isample/biology/biosampledfeature/mammal)

Child of:
 [`vertebrate`](#vertebrate)

vertebrates that have mammary glands, hair or fur, three middle ear
bones, specialized teeth, and are warm-blooded. (ChatGPT)

######  Reptile

[]{#reptile}

Concept: [`reptile`](https://w3id.org/isample/biology/biosampledfeature/reptile)

Child of:
 [`vertebrate`](#vertebrate)

Vertebrates that have scaly skin and claws, amniotic eggs, are cold-
blooded, and are ectothermic (ChatGPT)

####  Chromista

[]{#chromista}

Concept: [`chromista`](https://w3id.org/isample/biology/biosampledfeature/chromista)

Child of:
 [`eukaryote`](#eukaryote)

Chromists are unified by a shared common ancestral body plan with (1)
a skeleton comprising cortical alveoli with subpellicular microtubules
and a microtubule bypassing band distinct from the three major
microtubule centriolar roots inherited from excavate protozoa, and (2)
chloroplasts of red algal origin inside the endomembrane system with
unique membrane topology and derlin-based periplastid protein import
machinery.  Chromists are distinguished from Plantae because of more
complex chloroplast-associated membrane topology and rigid tubular
multipartite ciliary hairs.  The kingdom includes highly divergent
cytoskeletons and trophic modes. Chromista comprise eight distinctive
phyla (Cavalier-Smith, 2018) and includes a majority of marine algae
and of heterotrophic protists,  various human disease agents such as
malaria parasites, and agricultural pathogens like potato blight and
sugar beet rhizomania disease. They have a greater range of body plans
and lifestyles than the entire plant kingdom and more phyla than
kingdoms Fungi or Protozoa.

See Also:

* [<https://www.gbif.org/species/4>](https://www.gbif.org/species/4)

####  Eukaryotic microorganism

[]{#eukaryoticmicroorganism}

Concept: [`eukaryoticmicroorganism`](https://w3id.org/isample/biology/biosampledfeature/eukaryoticmicroorganism)

Child of:
 [`eukaryote`](#eukaryote)

Unclassified Eukaryote single-cell organisms; might be microfungi,
microalgae, Protista or Chromista.

See Also:

* [<https://en.wikipedia.org/wiki/Protist>](https://en.wikipedia.org/wiki/Protist)

####  Fungi

[]{#fungi}

Concept: [`fungi`](https://w3id.org/isample/biology/biosampledfeature/fungi)

Child of:
 [`eukaryote`](#eukaryote)

eukaryotic organisms that contain chitin in their cell walls, are
heterotrophs (they obtain their nutrients by absorbing organic
material from their environment, either as decomposers, parasites, or
symbionts) , lack chloroplasts, reproduce both sexually and asexually,
and can take on a variety of growth forms, including single-celled
yeasts, multicellular molds, and complex, specialized fruiting bodies.
(ChatGPT).   Biologists use the term ‘fungus’ to include eukaryotic,
spore-bearing, achlorophyllous organisms that generally reproduce
sexually and asexually. They are usually made up of filamentous,
branched somatic structures which are typically surrounded by cell
walls containing chitin or cellulose, or both of these substances.
(https://plantlet.org/lower-fungi-higher-fungi/)

See Also:

* [<https://www.gbif.org/species/5>](https://www.gbif.org/species/5)

#####  Macrofungi

[]{#macrofungi}

Concept: [`macrofungi`](https://w3id.org/isample/biology/biosampledfeature/macrofungi)

Child of:
 [`fungi`](#fungi)

Macrofungi refers to all fungi that produce visible fruiting bodies.
These fungi are evolutionarily and ecologically very divergent.
Evolutionarily, they belong to two main phyla, Ascomycota and
Basidiomycota, and many of them have relatives that cannot form
visible fruiting
bodies.(https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6106070/)

#####  Microfungi

[]{#microfungi}

Concept: [`microfungi`](https://w3id.org/isample/biology/biosampledfeature/microfungi)

Child of:
 [`fungi`](#fungi)

Microfungi or micromycetes are fungi—eukaryotic organisms such as
molds, mildews and rusts, which have microscopic spore-producing
structures. They exhibit tube tip-growth and have cell walls composed
of chitin, a polymer of N-acetylglucosamine. Microfungi are a
paraphyletic group, distinguished from macrofungi only by the absence
of a large, multicellular fruiting body. Include moulds, yeasts.
(https://en.wikipedia.org/wiki/Microfungi)

####  Plantae

[]{#plantae}

Concept: [`plantae`](https://w3id.org/isample/biology/biosampledfeature/plantae)

Child of:
 [`eukaryote`](#eukaryote)

Plants are eukaryotes that have cell walls made of cellulose,
specialized organelles called chloroplasts, which contain chlorophyll
and other pigments that allow plants to perform photosynthesis and
produce their own food;  a unique life cycle that involves alternating
between a haploid gametophyte stage and a diploid sporophyte stage;
specialized regions called apical meristems at the tips of their roots
and shoots, which allow for growth and the development of new tissues;
specialized structures for reproduction, including flowers, cones, and
spores, and most plants have specialized tissues called xylem and
phloem, which transport water, nutrients, and other substances
throughout the plant. (ChatGPT). Subdivision here follows Margulis and
Schwartz 2001.

See Also:

* [<https://www.gbif.org/species/6>](https://www.gbif.org/species/6)

#####  Non-vascular plant

[]{#nonvascularplant}

Concept: [`nonvascularplant`](https://w3id.org/isample/biology/biosampledfeature/nonvascularplant)

Child of:
 [`plantae`](#plantae)

Non-vascular plants that do not have specialized tissues for
transporting water and nutrients;  includes mosses, Marchantiophyta
(liverworts), and Anthocerotophyta (hornworts). (ChatGPT)

See Also:

* [<https://www.gbif.org/species/35>](https://www.gbif.org/species/35)

#####  Other plant

[]{#otherplant}

Concept: [`otherplant`](https://w3id.org/isample/biology/biosampledfeature/otherplant)

Child of:
 [`plantae`](#plantae)

plants that do not fit in other plant sub class. Includes
Lycopodiophyta (clubmosses) and Equisetophyta (horsetails)

#####  Vascular seed plant

[]{#vascularseedplant}

Concept: [`vascularseedplant`](https://w3id.org/isample/biology/biosampledfeature/vascularseedplant)

Child of:
 [`plantae`](#plantae)

Plant that produces seeds, hence the alternative name seed plant.
Spermatophytes are a subset of the embryophytes or land plants. They
include most familiar types of plants, including all flowers and most
trees, but exclude some other types of plants such as ferns, mosses,
algae. (https://en.wikipedia.org/wiki/Spermatophyte). Includes
Gymnosperms (naked-seed plants) and Angiosperms (flowering plants).

#####  Vascular spore plant

[]{#vascularsportplant}

Concept: [`vascularsportplant`](https://w3id.org/isample/biology/biosampledfeature/vascularsportplant)

Child of:
 [`plantae`](#plantae)

a vascular plant (with xylem and phloem) that disperses spores; they
produce neither flowers nor seeds, Includes  Ferns, horsetails (often
treated as ferns), and lycophytes (clubmosses, spikemosses, and
quillworts)

####  Protozoa

[]{#protozoa}

Concept: [`protozoa`](https://w3id.org/isample/biology/biosampledfeature/protozoa)

Child of:
 [`eukaryote`](#eukaryote)

A single-celled eukaryote, either free-living or parasitic, that feed
on organic matter such as other microorganisms or organic tissues and
debris (predominantly heterotrophic). Historically, protozoans were
regarded as 'one-celled animals', because they often possess animal-
like behaviours, such as motility and predation, and lack a cell wall,
as found in plants and many algae.
(https://en.wikipedia.org/wiki/Protozoa)

See Also:

* [<https://www.gbif.org/species/7>](https://www.gbif.org/species/7)

#####  Amoebozoa

[]{#amoebozoa}

Concept: [`amoebozoa`](https://w3id.org/isample/biology/biosampledfeature/amoebozoa)

Child of:
 [`protozoa`](#protozoa)

a diverse group of organisms that share certain characteristics, such
as the ability to move using pseudopodia, temporary extensions of the
cell membrane and cytoplasm that allow the cell to crawl or engulf
food particles, the lack of rigid cell walls, presence of
mitochondria, which are organelles that generate energy for the cell
through cellular respiration (chatGPT)

See Also:

* [<https://www.gbif.org/species/7509337>](https://www.gbif.org/species/7509337)

#####  Mycetozoa

[]{#mycetozoa}

Concept: [`mycetozoa`](https://w3id.org/isample/biology/biosampledfeature/mycetozoa)

Child of:
 [`protozoa`](#protozoa)

Mycetozoa includes the slime molds, which are a group of organisms
that have both amoeboid and fungal-like characteristics. The Mycetozoa
can be further subdivided into two groups: the plasmodial slime molds
and the cellular slime molds. Myxomycetes has most child orders; they
are  class of slime molds.   Myxomycetes have a complex life cycle
involving the formation of spore-bearing structures called fruiting
bodies, which is a key feature that distinguishes them from other
amoebae.   All species pass through several, very different
morphologic phases, such as microscopic individual cells, slimy
amorphous organisms visible with the naked eye and conspicuously
shaped fruit bodies. Although they are monocellular, they can reach
immense widths and weights.
(https://en.wikipedia.org/wiki/Mycetozoa).  (ChatGPT)

See Also:

* [<https://www.gbif.org/species/33>](https://www.gbif.org/species/33)

#####  Other Protozoa

[]{#otherprotozoa}

Concept: [`otherprotozoa`](https://w3id.org/isample/biology/biosampledfeature/otherprotozoa)

Child of:
 [`protozoa`](#protozoa)

Protozoa is not Amoebozoa or Mycetozoa.  Includes phylum Euglenozoa
and Microsporidia prominently among others.

###  Lichen

[]{#lichen}

Concept: [`lichen`](https://w3id.org/isample/biology/biosampledfeature/lichen)

Child of:
 [`biologicalentity`](#biologicalentity)

A composite organism that arises from algae or cyanobacteria living
among filaments of multiple fungi species in a mutualistic
relationship. (https://en.wikipedia.org/wiki/Lichen). Lichens are not
classified under a specific kingdom as they are a symbiotic
association between a fungus and either an alga or a cyanobacterium.
The fungal partner belongs to the kingdom Fungi, while the algal or
cyanobacterial partner belongs to either the kingdom Plantae or the
kingdom Bacteria, respectively. (ChatGPT)

###  Plasmid

[]{#plasmid}

Concept: [`plasmid`](https://w3id.org/isample/biology/biosampledfeature/plasmid)

Child of:
 [`biologicalentity`](#biologicalentity)

A plasmid is a small, extrachromosomal DNA molecule within a cell that
is physically separated from chromosomal DNA and can replicate
independently. While chromosomes are large and contain all the
essential genetic information for living under normal conditions,
plasmids are usually very small and contain only additional genes that
may be useful in certain situations or conditions.
(https://en.wikipedia.org/wiki/Plasmid)

###  Prokaryote

[]{#prokaryote}

Concept: [`prokaryote`](https://w3id.org/isample/biology/biosampledfeature/prokaryote)

Child of:
 [`biologicalentity`](#biologicalentity)

single-celled organisms that lack a nucleus and other membrane-bound
organelles. Unlike cells of animals and other eukaryotes, bacterial
cells do not contain a nucleus and rarely harbour membrane-bound
organelles. Molecular systematics showed prokaryotic life to consist
of two separate domains, originally called Eubacteria and
Archaebacteria, but now called Bacteria and Archaea that evolved
independently from an ancient common ancestor. Almost all prokaryotes
have a cell wall, a protective structure that allows them to survive
in extreme conditions, which is located outside of their plasma
membrane. Archaea and bacteria cannot reproduce sexually.

####  Archaea

[]{#archaea}

Concept: [`archaea`](https://w3id.org/isample/biology/biosampledfeature/archaea)

Child of:
 [`prokaryote`](#prokaryote)

archaeal cell walls are composed of polysaccharides (sugars). they
never have peptidoglycan in their cell walls, their cell membranes
contain lipids of unique composition (glycerol molecules are mirror
images of those found in other cells, and form ether linkages to
isoprenoid side chains), and their 16S ribosomal- RNA nucleotide
sequences are unlike those of bacteria.
(https://quizlet.com/234154298/archaea-and-bacteria-flash-cards/).
The common characteristics of Archaebacteria known to date are these:
(1) the presence of characteristic tRNAs and ribosomal RNAs; (2) the
absence of peptidoglycan cell walls, with in many cases, replacement
by a largely proteinaceous coat; (3) the occurrence of ether linked
lipids built from phytanyl chains and (4) in all cases known so far,
their occurrence only in unusual habitats.
(https://pubmed.ncbi.nlm.nih.gov/691075/)

See Also:

* [<https://www.gbif.org/species/2>](https://www.gbif.org/species/2)

####  Bacteria

[]{#bacteria}

Concept: [`bacteria`](https://w3id.org/isample/biology/biosampledfeature/bacteria)

Child of:
 [`prokaryote`](#prokaryote)

a large domain of prokaryotic microorganisms. Bacterial cells do not
contain a nucleus and rarely harbour membrane-bound organelles.  The
bacterial cell is surrounded by a cell membrane, which is made
primarily of phospholipids. This membrane encloses the contents of the
cell and acts as a barrier to hold nutrients, proteins and other
essential components of the cytoplasm within the cell.  Bacterial cell
walls are composed of peptidoglycan, a complex of protein and sugars,
while archaeal cell walls are composed of polysaccharides (sugars).
(https://en.wikipedia.org/wiki/Bacteria)

See Also:

* [<https://www.gbif.org/species/3>](https://www.gbif.org/species/3)

###  Virus

[]{#virus}

Concept: [`virus`](https://w3id.org/isample/biology/biosampledfeature/virus)

Child of:
 [`biologicalentity`](#biologicalentity)

A virus is a submicroscopic infectious agent that replicates only
inside the living cells of an organism. Realms are Adnaviria,
Duplodnaviria, Monodnaviria, Riboviria, Ribozyviria, Varidnaviria
(https://en.wikipedia.org/wiki/Virus). Viruses are not cells at all,
so they are neither prokaryotes nor eukaryotes. (https://bio.libretext
s.org/Bookshelves/Introductory_and_General_Biology/Book)

See Also:

* [<https://www.gbif.org/species/8>](https://www.gbif.org/species/8)

####  Other Virus

[]{#othervirus}

Concept: [`othervirus`](https://w3id.org/isample/biology/biosampledfeature/othervirus)

Child of:
 [`virus`](#virus)

Virus that is not a member of order Caudovirales (e.g., bacteriophage
T4, lambda phage).

####  Phage

[]{#phage}

Concept: [`phage`](https://w3id.org/isample/biology/biosampledfeature/phage)

Child of:
 [`virus`](#virus)

A bacteriophage, also known informally as a phage, is a duplodnaviria
virus that infects and replicates within bacteria and archaea.
Bacteriophages are composed of proteins that encapsulate a DNA or RNA
genome, and may have structures that are either simple or elaborate.
Their genomes may encode as few as four genes (e.g. MS2) and as many
as hundreds of genes. Phages replicate within the bacterium following
the injection of their genome into its cytoplasm.
(https://en.wikipedia.org/wiki/Bacteriophage).  Includes all virus in
order Caudovirales (e.g., bacteriophage T4, lambda phage).


