---
title: Requirements
format:
  html:
    toc: true
    toc-location: body
    toc-title: Contents
number-sections: false
---

## 01 Mint Identifiers

Mint identifiers and manage record.

Records are never deleted in SESAR. Sometimes they are deactivated.

Metadata will need to be updated.

Derived from

Actors

- Curator
- Research Contributor

Components

- iSB

- [Original Source](https://docs.google.com/document/d/16397FFbd0NjzW93TTD95ZqYkrwEpsC5DzBJnE7xnLPA/edit#heading=h.wm0ue5lp5goi)


## 02 Awareness of how specimens are being used

Provide metrics that indicate usage of a specimen. 

Requires that specimen access events are logged and retrievable. 

Usage metrics should include derived products as well, and so it is necessary to locate related content and usage metrics associated with the related content.

Derived from:

- S1

Actors

- Portal manager
- Research-contributor
- Research-consumer

Components

- iSB
- iSC


## 03 Availability of all information related to a sample

A sample has related content. All relations (transitive) need to be discoverable in the view of a sample. There are different types of relations. For example an image may be associated with a sample through a relationship that is different to the relationship between a sample and derived products. In an RDF view, the type of relation is the predicate of the association between a sample (subject) and the related item (object). Relationships occur within a context and there may be multiple contexts associated with any content.

Derived from:

- S2, S3, S4, S5, S10, O2, O8, O9, O10, O18, O11, O13, R02, R12, R17, G1, G3, G7, G9, G10, C1

Actors

- Research-consumer

Components

- iSC
- iSB
- Metadata model


## 04 Define relationships between things such as samples and derived products

Guidelines and mechanisms to support the creation of relationships between things such as samples, images of samples, components of other projects (e.g. Field Notes project of Smithsonian), derived products, annotations.

Instrument calibration records associated with an analysis.

Q. Should relationships include actions like loaning a sample? This seems more like a provenance topic, though provenance can be expressed as relations...

Derived from:

- S4, S3, S2, S6, O4, O8, O9, O18, O11, O12, O13, R17, G1, G3, G6, G7, C2

Actors

- Research-contributor
- Portal manager
- Curator

Components

- Metadata model
- iSC
- iSB
- Portal


## 05 Support sample management (loans, duplicates, subsamples)

Guidelines and mechanisms to support tracking of samples on loan or moved to a new institution. Allow for duplicate samples in different organizations, as is common in botany. For samples that can be sub-samples, track the subsamples and the status (i.e. amount remaining) of the parent sample.

Note that the process of sample loaning, moving, or other disposition is an operation of the collection. iSamples should support the tracking and discovery of samples that may be on loan or moved.

Derived from:

- S1, S2, S6.2, S6.3, O2, O8, O9, G1, 

Actors

- Research-contributor
- Portal manager
- Curator

Components

- Metadata model
- iSC
- iSB
- Portal


## 06 All metadata for all samples should be searchable and retrievable

Searchable should be against metadata properties. Can also be against relationship types. It may be feasible to search properties of related content up to n steps removed (n=0..?)

See also: Availability of all information related to a sample

Derived from:

- S7, S6, S10, O2, O9, O10, O11, R02, R06, R12, G7, G10

Actors

- Research-consumer
- Research-contributor
- Portal manager

Components

- Metadata model
- iSC (collated metadata)
- iSB (expose metadata, retrieve subsets)


## 07 Services support content negotiation, alternate renderings

Different renderings of the same content are needed for different purposes. A human should see a different rendering of metadata than a piece of software. Note that the rendering may be performed client side using a programmatic expression of the metadata. For example, a web UI may consume the same JSON to render in HTML that is also used by software.

Derived from:

- S9, O5, O6, R04, R05, R12, G9, G11

Actors

- Any user

Components

- Any component exposing content


## 08 Recognize that any entity may have multiple identifiers, some of which may not be globally unique.

There are many examples of different types of identifiers attached to content. Some identifiers may be well formed (globally unique and resolvable) others may be more context specific. Context specific identifiers should include sufficient information to determine the context.

Ad-hoc identifiers created in the field can be an example of context specific identifiers. For example, a field investigator may simply label items 1, 2, 3, … Those identifiers are only useful when the context of their creation is known and available.

Globally unique identifiers may take many different forms (e.g. DOI, ARK, IGSN, …), there may be multiple GUIDs for content.

Identifiers may be used at different levels of aggregation.

Inappropriate use of identifiers (e.g. ROR for samples) should be discouraged or blocked.

Derived from:

- O3, O4, O7, O12, O13, O15, O17, G2, G4, G5, G9, C1

Actors

- Curator
- Research-contributor
- Research-consumer

Components

- Metadata model
- iSC
- iSB


## 09 Content must be programmatically accessible and transferable to different systems
  

All content should be accessible through API and should exhibit no loss of information in the transfer to another system.

Note that it is expected that collections of content will be large (>> 10E6 items) so efficient paging, windowing and other subset selection mechanisms are needed.

The web publishing pattern (i.e. robots.txt -> sitemap -> schema.org) should be available for all resources appropriate for broad discovery.

See also [Services support content negotiation, alternate renderings](https://docs.google.com/document/d/16397FFbd0NjzW93TTD95ZqYkrwEpsC5DzBJnE7xnLPA/edit#heading=h.xsuxu7mw1taf)

Derived from:

- O6, R04, R05, R06, R08, R10, R12, R17, G1, G9, G11
  
Actors

- Research-consumer
  
Components

- Any components exposing APIs
  

## 10 User Interfaces for discovery and display of information should be efficient and practical for research use and expose relationships between items as appropriate.
  

At the global scale, low resolution maps, timescales and general discovery mechanisms are useful. As specificity increases, opportunities for expressing relationships between content as a means of assisting discovery and interpretation can follow.

See also: 

- [Availability of all information related to a sample](https://docs.google.com/document/d/16397FFbd0NjzW93TTD95ZqYkrwEpsC5DzBJnE7xnLPA/edit#heading=h.ggvgwq1kyba4)
  
- [All metadata for all samples should be searchable and retrievable](https://docs.google.com/document/d/16397FFbd0NjzW93TTD95ZqYkrwEpsC5DzBJnE7xnLPA/edit#heading=h.7lzhf0qirmsj)
  
Derived from:

- O14, R01, R06, R08, G5. G6
  
Actors

- Research-consumer
- Curator
  
Components

- iSC
- iSB
  

## 11 The diversity of metadata standards in use should be supported whilst also encouraging consistency in use and possibly reducing the diversity as appropriate with no loss of meaning.
  

There are many metadata formats in use, and this will continue. Creation of new metadata formats should be discouraged by facilitating concept matching to existing metadata elements. 

Mixed authority metadata formats should be supported. E.g. a metadata document may contain concepts defined in Dublin Core, ISO-19115, and the Observation Data Model

Vocabulary reuse should be encouraged.

Standard vocabularies for common concepts should be readily available (e.g. missing values, types of samples).

Recognize that there are natural levels of aggregation for metadata describing different things. For example individuals, groups, organizations.

Derived from:

- O16, R02, R03, R16, G4, G2, G5, G6, G10, G11
  
Actors

- Research-contributor
- Curator

Components

- iSB  


## 12 Ingest and deliver meta/data in multiple open formats
  

Portals  may choose what formats they will allow for data upload and ingest and what format they want to use to deliver data. iSB shouldmust support the use of common open formats such as CSV, JSON, possibly XML and XLSX. 

iSC will receive data only from iSB instances and project personnel, so it can limit the number of input formats. Metadata delivered as a result of searching the iSC index should be delivered in one or a few open formats.

Note that translation between serialization formats may result in loss of information. Support of multiple serializations can significantly increase implementation overhead.

Derived from:

Actors:

- Research-contributor  
- Curator
  
Components

- iSB
- iSC
- Portal
  

## 13 Support creation of identifiers early in a project
  
Early association of an identifier with content improves efficiency of data handling. Ideally, identifiers should be reliably mintable with no knowledge except for an initial state.

Derived from:

- C1

Actors:

- Research-contributor  
- Curator

Components

- iSB
    

## 14 Web interfaces should be flexible and loosely coupled through standard APIs to encourage diverse adoption
  

Portal web interfaces can serve a variety of audiences. In some cases (e.g. iSC) the interface will serve a very broad, diverse community. Other instances may be very specific (e.g. iSB or web UI serving the needs of a specific project). 

UIs should leverage standard APIs as far as possible, and underlying infrastructure should similarly express APIs using standard mechanisms.

REST, GraphQL are common API standards that should be leveraged. Other more specific interfaces such as the various Open Geospatial Consortium standards, and HDF should be utilized in preference to custom APIs.

Derived from:

- R05, R09, R08, R06, R10, R12


Actors

- Research-contributor  
- Research-consumer
- Curator

Components

- All
  

## 15 All content sources should be assumed to be dynamic and attached components should facilitate efficient synchronization of subscribed content.
  

With the transition to geoparquet-based data access, content synchronization now occurs through periodic updates of parquet files rather than real-time API synchronization. This approach provides better performance and reliability for analytical workloads.

Derived from:

- R10, R12  

Actors

- Administrators
- Research-consumer
- Research-contributor
- Curator

Components

- iSC  
- iSB
  

## 16 Data and metadata to be stored by iSamples in a box.
  

SESAR would like to utilize iSB as a data repository.

Also recognize that data and metadata may be stored on separate systems, and so reliable linking (e.g. via identifier) is necessary. Such indirect reference should be at least context aware (with context as part of metadata) or globally resolvable.

Note: the data may be large and so all data may not be stored on iSC. Q. How to determine boundaries of what is replicated? Metadata will be copied to iSC.

Derived from:

- R13, C2

Actors

- Research-contributor
- Curator

Components

- iSB


## 17 Content may not all be publicly accessible.
  

There may be content (metadata, data, related content) with information that should not be publicly accessible (e.g. artifact location). This implies that the system should either reject access controlled content or implement access control at all levels.

Implementation of access control all or nothing. It must be integrated at all levels and rigorous. A break in trust can have significant consequences beyond the project.

Leverage existing user management infrastructure as far as possible. ORCID for user identification, oauth + JWT for access

Group management should be delegated to another system if possible. TODO: suggestions for infrastructure? Enable arbitrary group creation, management. Roles.

Derived from:

- R14, O8, O9

Actors

- All

Components

- All
  

## 18 Validation rules can assist with production of higher quality content. 
  

Just like a spell checker, validation rules can assist with production of higher quality content. Validation rules should be sharable and reusable. Content entry / editing systems should leverage validation mechanisms for immediate user feedback and/or guidance.

Note that validation is context dependent, and the validity rules may change over time.

Derived from:

- G4, G8
  
Actors

- Research-contributor
- Curator
  
Components

- Portal
- iSB
