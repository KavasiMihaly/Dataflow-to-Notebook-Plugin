#!/usr/bin/env python3
"""
Convert Power Query M code from PBIP semantic models (TMDL) to Fabric PySpark notebooks.

Usage:
    # Convert all tables in a PBIP semantic model
    python convert_m_to_pyspark.py --tmdl-path "path/to/Model.SemanticModel/definition"

    # Convert a single .tmdl file
    python convert_m_to_pyspark.py --tmdl-file "path/to/tables/Sales.tmdl"

    # Convert raw M code from a file
    python convert_m_to_pyspark.py --m-file "query.m"

    # Convert M code from a string
    python convert_m_to_pyspark.py --m-code "let Source = ... in Result"

    # Specify output directory (default: current dir)
    python convert_m_to_pyspark.py --tmdl-path "path" --output-dir "output/"

    # List tables without converting
    python convert_m_to_pyspark.py --tmdl-path "path" --list-tables

    # Verbose mode
    python convert_m_to_pyspark.py --tmdl-path "path" --verbose
"""

import argparse
import os
import sys
import re

# Add scripts directory to path for sibling imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tmdl_extractor import TmdlExtractor
from m_parser import MParser
from pyspark_generator import PySparkGenerator
from function_map import M_TO_PYSPARK_TYPES


def to_snake_case(name: str) -> str:
    """Convert a name to snake_case."""
    name = re.sub(r'[^a-zA-Z0-9\s_]', '', name)
    name = re.sub(r'([a-z])([A-Z])', r'\1_\2', name)
    name = re.sub(r'[\s]+', '_', name)
    return name.lower().strip('_')


def convert_tmdl_folder(args):
    """Convert all M partitions in a TMDL folder."""
    extractor = TmdlExtractor()
    parser = MParser()
    generator = PySparkGenerator()

    extracts = extractor.extract_from_folder(args.tmdl_path)

    if not extracts:
        print(f"No M partitions found in: {args.tmdl_path}")
        return 1

    output_dir = args.output_dir or "."
    os.makedirs(output_dir, exist_ok=True)

    success_count = 0
    error_count = 0

    for extract in extracts:
        table_name = extract["table_name"]
        m_code = extract["m_code"]
        source_file = extract["source_file"]

        if args.verbose:
            print(f"\n{'='*60}")
            print(f"Converting: {table_name} (from {source_file})")
            print(f"Mode: {extract['mode']}")
            print(f"M code length: {len(m_code)} chars")

        try:
            parsed = parser.parse(m_code)
            pyspark_code = generator.generate(parsed, table_name, source_file)

            snake_name = to_snake_case(table_name)
            output_file = os.path.join(output_dir, f"nb_bronze_{snake_name}.py")

            with open(output_file, "w", encoding="utf-8") as f:
                f.write(pyspark_code)

            success_count += 1
            if args.verbose:
                step_types = [s["type"] for s in parsed["steps"]]
                unknown = sum(1 for t in step_types if t == "unknown")
                print(f"  Steps: {len(parsed['steps'])} ({unknown} unknown)")
                print(f"  Output: {output_file}")
            else:
                print(f"  {table_name} -> {output_file}")

        except Exception as e:
            error_count += 1
            print(f"  ERROR converting {table_name}: {e}", file=sys.stderr)
            if args.verbose:
                import traceback
                traceback.print_exc()

    # Summary
    print(f"\nConversion complete: {success_count} succeeded, {error_count} failed")
    return 0 if error_count == 0 else 1


def convert_single_file(args):
    """Convert a single .tmdl file."""
    extractor = TmdlExtractor()
    parser = MParser()
    generator = PySparkGenerator()

    extracts = extractor.extract_from_file(args.tmdl_file)

    if not extracts:
        print(f"No M partitions found in: {args.tmdl_file}")
        return 1

    output_dir = args.output_dir or "."
    os.makedirs(output_dir, exist_ok=True)

    for extract in extracts:
        table_name = extract["table_name"]
        parsed = parser.parse(extract["m_code"])
        pyspark_code = generator.generate(parsed, table_name, extract["source_file"])

        snake_name = to_snake_case(table_name)
        output_file = os.path.join(output_dir, f"nb_bronze_{snake_name}.py")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(pyspark_code)

        print(f"  {table_name} -> {output_file}")

    return 0


def convert_m_file(args):
    """Convert M code from a .m file."""
    parser = MParser()
    generator = PySparkGenerator()

    with open(args.m_file, "r", encoding="utf-8") as f:
        m_code = f.read()

    table_name = os.path.splitext(os.path.basename(args.m_file))[0]
    parsed = parser.parse(m_code)
    pyspark_code = generator.generate(parsed, table_name, args.m_file)

    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
        snake_name = to_snake_case(table_name)
        output_file = os.path.join(args.output_dir, f"nb_bronze_{snake_name}.py")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(pyspark_code)
        print(f"  {table_name} -> {output_file}")
    else:
        print(pyspark_code)

    return 0


def convert_m_string(args):
    """Convert M code from a string argument."""
    parser = MParser()
    generator = PySparkGenerator()

    parsed = parser.parse(args.m_code)
    pyspark_code = generator.generate(parsed, "Query", "stdin")

    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
        output_file = os.path.join(args.output_dir, "nb_bronze_query.py")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(pyspark_code)
        print(f"  Query -> {output_file}")
    else:
        print(pyspark_code)

    return 0


def list_tables(args):
    """List tables and their M partitions without converting."""
    extractor = TmdlExtractor()
    tables = extractor.list_tables(args.tmdl_path)

    if not tables:
        print(f"No tables with M partitions found in: {args.tmdl_path}")
        return 1

    print(f"\nTables with M partitions in: {args.tmdl_path}\n")
    print(f"{'Table Name':<40} {'Partitions':<12} {'Mode':<15} {'Source File'}")
    print(f"{'-'*40} {'-'*12} {'-'*15} {'-'*20}")

    for t in tables:
        print(f"{t['table_name']:<40} {t['partition_count']:<12} {t['mode']:<15} {t['source_file']}")

    print(f"\nTotal: {len(tables)} tables")
    return 0


def main():
    argparser = argparse.ArgumentParser(
        description="Convert Power Query M code from PBIP semantic models (TMDL) to Fabric PySpark notebooks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --tmdl-path "Model.SemanticModel/definition"
  %(prog)s --tmdl-file "tables/Sales.tmdl"
  %(prog)s --m-file "query.m"
  %(prog)s --m-code "let Source = Sql.Database(\\"srv\\", \\"db\\") in Source"
  %(prog)s --tmdl-path "definition" --list-tables
  %(prog)s --tmdl-path "definition" --output-dir "notebooks/" --verbose
""",
    )

    # Input sources (mutually exclusive)
    input_group = argparser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--tmdl-path",
        help="Path to PBIP semantic model 'definition' folder (converts all tables)",
    )
    input_group.add_argument(
        "--tmdl-file",
        help="Path to a single .tmdl file",
    )
    input_group.add_argument(
        "--m-file",
        help="Path to a raw .m file containing Power Query code",
    )
    input_group.add_argument(
        "--m-code",
        help="Raw M code string to convert",
    )

    # Options
    argparser.add_argument(
        "--output-dir",
        help="Output directory for generated .py files (default: current directory)",
    )
    argparser.add_argument(
        "--list-tables",
        action="store_true",
        help="List tables and partitions without converting",
    )
    argparser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output with step details",
    )

    args = argparser.parse_args()

    # Dispatch to appropriate handler
    if args.list_tables:
        if not args.tmdl_path:
            argparser.error("--list-tables requires --tmdl-path")
        return list_tables(args)

    if args.tmdl_path:
        return convert_tmdl_folder(args)
    elif args.tmdl_file:
        return convert_single_file(args)
    elif args.m_file:
        return convert_m_file(args)
    elif args.m_code:
        return convert_m_string(args)
    else:
        argparser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
