# Namespaces defined by iSamples

Namespaces are used to uniquely address resources offered by the project. 

In order to support introspection, all namespace IRIs are to be resolvable. Resolution involves three variables: the IRI, the requested content type, and an optional profile.

The IRI provides the location of the resource. Reference to specific items within a resource can be made in two ways: by path (e.g. `/resource/element`) and by fragment (e.g. `resource#element`). IRI fragments are not transmitted to a server by a client, hence a fragment identifier is always relative to the retrieved document. The basic rule is thus, the path element reference is used to reference a specific document, then a fragment is used to reference a specific component of the document.

The requested content type is presented by a client in the Accept header. If no Accept header is presented by the client or the Accept header is ambiguous (e.g. `*/*`), then the default content type is returned. If a specific content type can not be matched, then a [406 Not Acceptable](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/406) status is returned. 

## Namespace base

IRI
: `https://w3id.org/isamples/`

The namespace base provides the root for project IRIs. The project will utilize the [w3id.org](https://w3id.org/) infrastructure to enable abstraction of the advertised location and the physical location of the resource. Such abstraction is especially important early in the project as locations of resources are in flux.

## Definitions

The default format for definitions is JSON-LD. Other formats may be requested using the Accept header.

IRI
: `iss: <https://w3id.org/isamples/models/>`

Definitions include static content such as vocabularies, ontologies, schemas, and other documents providing machine and human actionable documents describing resources.

Vocabularies
: `https://w3id.org/isamples/models/vocab/`

Specimen Type Vocabulary:
: `https://w3id.org/isamples/models/vocab/specimen_type/`

Sampled Feature Vocabulary:
: `https://w3id.org/isamples/models/vocab/sampled_feature/`

Material Type Vocabulary:
: `https://w3id.org/isamples/models/vocab/material_type/`

## Services

IRI
: `https://w3id.org/isamples/svc/`

### Record access

IRI
: `https://w3id.org/isamples/svc/meta/`

