"""
Extract M queries from exported Dataflow Gen1 JSON files.

Parses JSON files produced by Export-PowerBIDataflow, extracts individual
M queries (Power Query / M language) as separate .pq files, and generates
a query_inventory.csv summarizing all discovered entities.

Usage:
    python extract_m_from_json.py --source "path/to/json/files" --output "path/to/m_queries"
    python extract_m_from_json.py --source "./exports" --output "./m_queries" --inventory "./inventory.csv"

Output:
    {output}/{dataflow_name}/*.pq   (individual M queries)
    {inventory}                      (CSV inventory of all queries)
"""

import argparse
import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime


def sanitize_filename(name: str) -> str:
    """Replace characters that are invalid in file/folder names."""
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()


def extract_queries_from_pqm(pqm_text: str) -> dict[str, str]:
    """
    Parse a Power Query M section document and extract individual named queries.

    Section document format:
        section Section1;
        shared #"Query Name" = let ... in result;
    """
    queries = {}
    pattern = r'shared\s+(#?"[^"]+"|[\w.]+)\s*=\s*'
    matches = list(re.finditer(pattern, pqm_text))

    for i, match in enumerate(matches):
        raw_name = match.group(1)
        query_name = raw_name.strip('"').lstrip('#').strip('"')

        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(pqm_text)
        body = pqm_text[start:end].strip()

        if body.endswith(';'):
            body = body[:-1].strip()

        if body:
            queries[query_name] = body

    return queries


def extract_queries_from_entities(entities: list[dict]) -> dict[str, str]:
    """Extract M expressions from the entities array (per-entity format)."""
    queries = {}
    for entity in entities:
        name = entity.get("name", "unknown")
        for partition in entity.get("partitions", []):
            expression = partition.get("source", {}).get("expression")
            if expression:
                m_code = "\n".join(expression) if isinstance(expression, list) else str(expression)
                if m_code.strip():
                    queries[name] = m_code.strip()
    return queries


def classify_source_type(code_lower: str) -> str:
    """Classify the data source type from M code patterns."""
    source_map = [
        (["sql.database", "sql.databases"], "sql_server"),
        (["analysisservices.database"], "analysis_services"),
        (["sharepoint.files", "sharepoint.tables"], "sharepoint"),
        (["excel.workbook"], "excel"),
        (["csv.document"], "csv"),
        (["web.contents", "web.browsercontents"], "web"),
        (["odata.feed"], "odata"),
        (["azurestorage.blobs", "azurestorage.datalake"], "azure_storage"),
        (["powerbi.dataflows"], "linked_dataflow"),
        (["table.fromrecords", "table.fromlist"], "static_table"),
        (["json.document"], "json"),
        (["mysql.database"], "mysql"),
        (["postgresql.database"], "postgresql"),
        (["oracle.database"], "oracle"),
        (["odbc.datasource", "odbc.query"], "odbc"),
        (["activedirectory.domains"], "active_directory"),
        (["exchange.contents"], "exchange"),
        (["facebook.graph"], "facebook"),
        (["salesforce.data"], "salesforce"),
        (["googlebigquery.database"], "bigquery"),
    ]
    for patterns, source_type in source_map:
        if any(p in code_lower for p in patterns):
            return source_type
    return "derived"


def classify_role(query_name: str, code_lower: str, all_queries: dict) -> str:
    """Classify whether a query is a staging/helper or an output entity."""
    name_lower = query_name.lower()

    if name_lower.startswith(("param_", "parameter", "fn_", "func_")):
        return "parameter_or_function"
    if name_lower in ("source", "connection"):
        return "helper"

    referenced = any(
        query_name in other_code
        for other_name, other_code in all_queries.items()
        if other_name != query_name
    )

    has_direct_source = any(
        p in code_lower for p in [
            "sql.database", "sharepoint.", "excel.workbook",
            "csv.document", "web.contents", "odata.feed",
            "azurestorage.blobs", "azurestorage.datalake",
            "json.document", "mysql.database", "postgresql.database",
        ]
    )

    if has_direct_source and not referenced:
        return "output_entity"
    elif has_direct_source and referenced:
        return "staging"
    elif not has_direct_source:
        return "transformation"
    return "unknown"


def process_json_file(json_path: Path, output_dir: Path, project_root: Path) -> list[dict]:
    """Process a single exported dataflow JSON file. Returns inventory records."""
    dataflow_name = json_path.stem
    safe_name = sanitize_filename(dataflow_name)
    output_subdir = output_dir / safe_name
    output_subdir.mkdir(parents=True, exist_ok=True)

    print(f"\nProcessing: {json_path.name}")

    with open(json_path, "r", encoding="utf-8-sig") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"  ERROR: Invalid JSON - {e}")
            return [{"dataflow_name": dataflow_name, "query_name": "PARSE_ERROR",
                     "file_path": "", "line_count": 0, "starts_with_let": False,
                     "source_type": "error", "role": "error", "extraction_method": "failed"}]

    queries = {}
    extraction_method = "unknown"

    # Method 1: pbi:mashup -> document (Export-PowerBIDataflow format)
    mashup = data.get("pbi:mashup", {})
    if isinstance(mashup, dict):
        pqm_text = mashup.get("document", "")
        if pqm_text and isinstance(pqm_text, str):
            queries = extract_queries_from_pqm(pqm_text)
            extraction_method = "pbi_mashup_document"

    # Method 2: annotations array
    if not queries:
        for annotation in data.get("annotations", []):
            if annotation.get("name") == "pbi:mashup.document":
                pqm_text = annotation.get("value", "")
                if pqm_text:
                    queries = extract_queries_from_pqm(pqm_text)
                    extraction_method = "annotation_pqm_document"
                    break

    # Method 3: entities array (per-entity expressions)
    if not queries:
        entities = data.get("entities", [])
        if entities:
            queries = extract_queries_from_entities(entities)
            if queries:
                extraction_method = "entities"

    # Method 4: root document key
    if not queries and "document" in data:
        doc = data["document"]
        if isinstance(doc, str):
            queries = extract_queries_from_pqm(doc)
            extraction_method = "root_document"
        elif isinstance(doc, dict) and "pqm" in doc:
            queries = extract_queries_from_pqm(doc["pqm"])
            extraction_method = "root_document_pqm"

    if not queries:
        print(f"  WARNING: No M queries found in {json_path.name}")
        print(f"  JSON top-level keys: {list(data.keys())}")
        return [{"dataflow_name": dataflow_name, "query_name": "NO_QUERIES_FOUND",
                 "file_path": "", "line_count": 0, "starts_with_let": False,
                 "source_type": "unknown", "role": "unknown", "extraction_method": "none"}]

    print(f"  Found {len(queries)} queries (method: {extraction_method})")

    inventory_rows = []
    for query_name, m_code in queries.items():
        safe_query = sanitize_filename(query_name)
        pq_file = output_subdir / f"{safe_query}.pq"
        pq_file.write_text(m_code, encoding="utf-8")

        code_lower = m_code.lower()
        starts_with_let = m_code.strip().startswith("let")
        line_count = len(m_code.splitlines())
        source_type = classify_source_type(code_lower)
        role = classify_role(query_name, code_lower, queries)

        try:
            rel_path = str(pq_file.relative_to(project_root))
        except ValueError:
            rel_path = str(pq_file)

        inventory_rows.append({
            "dataflow_name": dataflow_name,
            "query_name": query_name,
            "file_path": rel_path,
            "line_count": line_count,
            "starts_with_let": starts_with_let,
            "source_type": source_type,
            "role": role,
            "extraction_method": extraction_method,
        })
        print(f"    {query_name} -> {safe_query}.pq ({line_count} lines, {source_type}, {role})")

    return inventory_rows


def validate_extraction(inventory: list[dict]) -> None:
    """Print validation summary."""
    errors = [r for r in inventory if r["query_name"] in ("PARSE_ERROR", "NO_QUERIES_FOUND")]
    valid = [r for r in inventory if r not in errors]
    lets = [r for r in valid if r["starts_with_let"]]
    non_lets = [r for r in valid if not r["starts_with_let"]]

    print(f"\n{'=' * 60}")
    print("EXTRACTION VALIDATION SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total queries extracted:     {len(valid)}")
    print(f"Extraction errors:           {len(errors)}")
    print(f"Queries starting with 'let': {len(lets)}")
    print(f"Non-let queries:             {len(non_lets)}")

    if non_lets:
        print(f"\n  Non-let queries (may be parameters or simple expressions):")
        for r in non_lets:
            print(f"    - {r['dataflow_name']}/{r['query_name']} ({r['role']})")

    source_types = {}
    for r in valid:
        st = r["source_type"]
        source_types[st] = source_types.get(st, 0) + 1
    print(f"\nSource type breakdown:")
    for st, count in sorted(source_types.items(), key=lambda x: -x[1]):
        print(f"  {st}: {count}")

    roles = {}
    for r in valid:
        role = r["role"]
        roles[role] = roles.get(role, 0) + 1
    print(f"\nRole breakdown:")
    for role, count in sorted(roles.items(), key=lambda x: -x[1]):
        print(f"  {role}: {count}")

    dataflows = set(r["dataflow_name"] for r in valid)
    print(f"\nDataflows processed: {len(dataflows)}")
    for df in sorted(dataflows):
        df_queries = [r for r in valid if r["dataflow_name"] == df]
        print(f"  {df}: {len(df_queries)} queries")
    print(f"{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract M queries from exported Dataflow Gen1 JSON files"
    )
    parser.add_argument(
        "--source", required=True,
        help="Directory containing exported JSON files"
    )
    parser.add_argument(
        "--output", required=True,
        help="Directory for extracted .pq files (organized by dataflow)"
    )
    parser.add_argument(
        "--inventory", default=None,
        help="Path for query_inventory.csv (default: {output}/query_inventory.csv)"
    )
    args = parser.parse_args()

    source_dir = Path(args.source).resolve()
    output_dir = Path(args.output).resolve()
    inventory_file = Path(args.inventory).resolve() if args.inventory else output_dir / "query_inventory.csv"

    print("=" * 60)
    print("Dataflow Gen1 M Code Extractor")
    print(f"Source:    {source_dir}")
    print(f"Output:    {output_dir}")
    print(f"Inventory: {inventory_file}")
    print(f"Date:      {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    json_files = sorted(source_dir.glob("*.json"))
    # Exclude the manifest file
    json_files = [f for f in json_files if f.name != "dataflow_manifest.csv"]

    if not json_files:
        print(f"\nERROR: No JSON files found in {source_dir}")
        print("Run Export-AllDataflows.ps1 first to export dataflows.")
        sys.exit(1)

    print(f"\nFound {len(json_files)} JSON file(s) to process.")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use common parent as project root for relative paths
    project_root = source_dir.parent

    all_inventory = []
    for json_file in json_files:
        rows = process_json_file(json_file, output_dir, project_root)
        all_inventory.extend(rows)

    if all_inventory:
        fieldnames = [
            "dataflow_name", "query_name", "file_path", "line_count",
            "starts_with_let", "source_type", "role", "extraction_method",
        ]
        inventory_file.parent.mkdir(parents=True, exist_ok=True)
        with open(inventory_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_inventory)
        print(f"\nInventory written to: {inventory_file}")

    validate_extraction(all_inventory)
    print(f"\nDone.")


if __name__ == "__main__":
    main()
