# Mapping from sources to core


In general the process is :

```{uml} assets/mapping_general.puml
---
scale: 50%
---
```


## GEOME

| s | p | o | Label | Source |
| --- | --- | --- | --- | --- |
| ARK | has_record | _id | event | GEOME | 
| ARK | has_record | _id | sample | GEOME |
| ARK | has_record | _id | tissue | GEOME |
| IGSN | has_record | _id | sample | SESAR |
| ARK | has_record | _id | SMITHSONIAN |



```{figure} assets/geome_mapping.drawio.svg
---
align: left
---
Source record representation.
```

```{figure} assets/geome_mapping_1.drawio.svg
---
align: left
---
Mapping to individual core records and relation records. 
```

Relations between entities are modelled as triples with subject (s) indicating the source of the relation, the predicate (p) the type of relation, and object (o) identifying the target. 


```{figure} assets/geome_mapping_2.drawio.svg
---
align: left
---
Mapping to individual core records and including relations in the records.
```

Relations between entities are modelled as key-value pairs within the record, with key being a field name, and value being a list of identifiers.
