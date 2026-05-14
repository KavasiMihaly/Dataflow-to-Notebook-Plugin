# Dataflow Gen1 JSON Formats

The `Export-PowerBIDataflow` cmdlet and Power BI REST API produce JSON files with M code embedded in different locations depending on the dataflow version and export method. The parser tries 4 extraction methods in order.

## Method 1: `pbi:mashup.document` (most common)

The primary format from `Export-PowerBIDataflow`. M code is a section document string.

```json
{
  "name": "My Dataflow",
  "pbi:mashup": {
    "fastCombine": false,
    "allowNativeQueries": false,
    "queriesMetadata": { ... },
    "document": "section Section1;\r\nshared #\"Query1\" = let\r\n  Source = ...\r\nin\r\n  result;\r\nshared #\"Query2\" = let\r\n  ..."
  },
  "annotations": [...],
  "entities": [...]
}
```

**Key path:** `data["pbi:mashup"]["document"]`

The document uses Power Query section syntax:
```
section Section1;
shared #"Query Name" = let
    Step1 = ...,
    Step2 = ...
in
    Step2;
```

Query names with spaces are quoted: `#"My Query"`. Each query ends with `;`.

## Method 2: Annotation-based

Some older exports store M code in the annotations array.

```json
{
  "annotations": [
    {
      "name": "pbi:mashup.document",
      "value": "section Section1;\r\nshared ..."
    }
  ]
}
```

**Key path:** `data["annotations"][name="pbi:mashup.document"]["value"]`

## Method 3: Per-entity expressions

Admin API exports may store M code per entity rather than as a single document.

```json
{
  "entities": [
    {
      "name": "QueryName",
      "partitions": [
        {
          "source": {
            "expression": "let\n  Source = ...\nin\n  result"
          }
        }
      ]
    }
  ]
}
```

**Key path:** `data["entities"][*]["partitions"][*]["source"]["expression"]`

The expression can be a string or an array of strings (joined with newlines).

## Method 4: Root document

Rare format where the M document is at the root level.

```json
{
  "document": "section Section1;\r\nshared ..."
}
```

Or nested:

```json
{
  "document": {
    "pqm": "section Section1;\r\nshared ..."
  }
}
```

## queriesMetadata

The `pbi:mashup.queriesMetadata` object lists all queries with metadata:

```json
{
  "Query Name": {
    "queryId": "guid",
    "queryName": "Query Name",
    "loadEnabled": true  // only present if entity is loaded to storage
  }
}
```

Queries without `loadEnabled: true` are helper/staging queries not materialized as tables.
