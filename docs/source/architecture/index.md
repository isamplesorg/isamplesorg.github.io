# Architecture

**Contents**

```{toctree}

requirements
```

## Context

```{uml}
!include C4-PlantUML/C4_Context.puml

System(isc, "iSC", "iSamples Central")

System_Boundary(isamples, "iSamples"){
  System(isb, "iSB", "iSamples-In-A-Box")
  System_Ext(collection, "Collection", "Collection of sample records")
  Rel(isb, collection, "Get records from collection")
}
BiRel(isb, isc, "Synchronize records")
  
System_Ext(pid, "Id Authority", "Identifier authorities (IGSN, ARK, DOI, ROR, ...)")
Rel(pid, isb, "Allocate range of identifier values")
Rel(pid, isc, "Allocate range of identifier values?")

Person(user, "User", "Data User")
Rel(user, isc, "Discover, Annotate")
Rel(user, isb, "Discover, Retrieve, Annotate, [Create, Update if authorized]")

Person(admin, "Admin", "Administrator")
Rel_U(admin, isc, "Manage")
Rel(admin, isb, "Manage")

System_Ext(evocab, "Vocabularies", "Community maintained vocabularies and ontologies")
Rel(evocab, isb, "Inform")
Rel(evocab, isc, "Inform")

System_Ext(identity, "Identity", "User identity service (ORCID, GitHub, ...)")
Rel(isc, identity, "User metadata, Authenticate")
Rel(isb, identity, "User metadata, Authenticate (if applicable)")

System_Ext(publisher, "Publisher", "Source of identifier appareance in publications")
Rel(isc, publisher, "Get identifier appearances")

SHOW_LEGEND()
```

Note: It may be instructive to split the "User" into general public users and users authorized to manipulate content or see restricted information. Other user categories might include collection administrators and project sponsors (both for the iSamples project and for projects that contribute content to collections).