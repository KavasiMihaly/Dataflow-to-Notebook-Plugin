"""
Extract M code from TMDL partition blocks in .tmdl table files.

TMDL files use tab-based indentation. Partition blocks look like:

    partition '<Name>' = m
        mode: import
        source =
            let
                Source = Sql.Database("server", "db"),
                ...
            in
                Result

This module extracts the M code from those blocks.
"""

import os
import re


class TmdlExtractor:
    """Extracts M code from TMDL files in a PBIP semantic model."""

    def extract_from_folder(self, definition_path: str) -> list:
        """Extract M code from all .tmdl files in a definition folder.

        Args:
            definition_path: Path to the 'definition' folder of a semantic model,
                             or the 'definition/tables' subfolder.

        Returns:
            List of dicts with table_name, partition_name, mode, m_code, source_file.
        """
        results = []

        # Normalize: accept either 'definition' or 'definition/tables'
        tables_dir = definition_path
        if os.path.isdir(os.path.join(definition_path, "tables")):
            tables_dir = os.path.join(definition_path, "tables")

        if not os.path.isdir(tables_dir):
            return results

        # Process all .tmdl files in tables directory
        for filename in sorted(os.listdir(tables_dir)):
            if filename.endswith(".tmdl"):
                filepath = os.path.join(tables_dir, filename)
                results.extend(self.extract_from_file(filepath))

        # Also check for expressions.tmdl at definition level
        expr_candidates = [
            os.path.join(definition_path, "expressions.tmdl"),
            os.path.join(os.path.dirname(tables_dir), "expressions.tmdl"),
        ]
        for expr_path in expr_candidates:
            if os.path.isfile(expr_path):
                results.extend(self._extract_expressions(expr_path))
                break

        return results

    def extract_from_file(self, tmdl_path: str) -> list:
        """Extract M code from a single .tmdl file.

        Args:
            tmdl_path: Path to a .tmdl file.

        Returns:
            List of dicts with table_name, partition_name, mode, m_code, source_file.
        """
        if not os.path.isfile(tmdl_path):
            return []

        with open(tmdl_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Derive table name from file or content
        table_name = self._get_table_name(content, tmdl_path)
        return self._parse_tmdl_partitions(content, table_name, tmdl_path)

    def _get_table_name(self, content: str, filepath: str) -> str:
        """Extract table name from TMDL content or filename."""
        # Look for 'table <Name>' or "table '<Name>'" at start
        match = re.search(r"^table\s+'?([^'\n]+)'?\s*$", content, re.MULTILINE)
        if match:
            return match.group(1).strip()

        # Fall back to filename without extension
        basename = os.path.basename(filepath)
        return os.path.splitext(basename)[0]

    def _parse_tmdl_partitions(self, content: str, table_name: str, source_file: str) -> list:
        """Parse partition blocks from TMDL content.

        Handles both formats:
            partition '<Name>' = m
            partition <Name> = m
        """
        results = []
        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # Match partition = m line
            partition_match = re.match(
                r"^(\t*)partition\s+'?([^'=\n]+?)'?\s*=\s*m\s*$", line
            )
            if partition_match:
                base_indent = partition_match.group(1)
                partition_name = partition_match.group(2).strip()
                i += 1

                mode = "import"
                m_code = None

                # Parse partition body (indented deeper than the partition line)
                partition_indent = base_indent + "\t"

                while i < len(lines):
                    current = lines[i]

                    # Check if we've left the partition block
                    if current.strip() and not current.startswith(partition_indent):
                        break

                    stripped = current.strip()

                    # Parse mode line
                    if stripped.startswith("mode:"):
                        mode = stripped.split(":", 1)[1].strip()
                        i += 1
                        continue

                    # Parse source/expression block (the M code)
                    if stripped.startswith("source =") or stripped.startswith("expression ="):
                        # Check if M code starts on the same line
                        eq_parts = current.split("=", 1)
                        inline = eq_parts[1].strip() if len(eq_parts) > 1 else ""
                        i += 1

                        m_lines = []
                        if inline:
                            m_lines.append(inline)

                        # Collect indented M code lines
                        source_indent = partition_indent + "\t"
                        while i < len(lines):
                            current = lines[i]
                            # M code block continues while lines are indented
                            # or are blank lines within the block
                            if current.strip() == "":
                                # Blank line - keep if followed by more M code
                                if i + 1 < len(lines) and (
                                    lines[i + 1].startswith(source_indent)
                                    or lines[i + 1].strip() == ""
                                ):
                                    m_lines.append("")
                                    i += 1
                                    continue
                                else:
                                    break
                            elif current.startswith(source_indent) or current.startswith(
                                partition_indent + "\t\t"
                            ):
                                # Strip the source indentation
                                m_lines.append(self._strip_indent(current, source_indent))
                                i += 1
                            else:
                                break

                        m_code = "\n".join(m_lines).strip()
                        continue

                    i += 1

                if m_code:
                    results.append(
                        {
                            "table_name": table_name,
                            "partition_name": partition_name,
                            "mode": mode,
                            "m_code": m_code,
                            "source_file": os.path.basename(source_file),
                        }
                    )
            else:
                i += 1

        return results

    def _extract_expressions(self, expr_path: str) -> list:
        """Extract shared expressions/parameters from expressions.tmdl."""
        results = []

        with open(expr_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # Match expression blocks: expression <Name> = or expression '<Name>' =
            expr_match = re.match(
                r"^(\t*)expression\s+'?([^'=\n]+?)'?\s*=\s*$", line
            )
            if expr_match:
                base_indent = expr_match.group(1)
                expr_name = expr_match.group(2).strip()
                expr_indent = base_indent + "\t"
                i += 1

                m_lines = []
                while i < len(lines):
                    current = lines[i]
                    if current.strip() == "":
                        if i + 1 < len(lines) and lines[i + 1].startswith(expr_indent):
                            m_lines.append("")
                            i += 1
                            continue
                        else:
                            break
                    elif current.startswith(expr_indent):
                        m_lines.append(self._strip_indent(current, expr_indent))
                        i += 1
                    else:
                        break

                m_code = "\n".join(m_lines).strip()
                if m_code:
                    results.append(
                        {
                            "table_name": expr_name,
                            "partition_name": expr_name,
                            "mode": "expression",
                            "m_code": m_code,
                            "source_file": "expressions.tmdl",
                        }
                    )
            else:
                i += 1

        return results

    def _strip_indent(self, line: str, prefix: str) -> str:
        """Strip a known indentation prefix from a line."""
        if line.startswith(prefix):
            return line[len(prefix):]
        # Try stripping equivalent spaces (4 spaces per tab)
        space_prefix = prefix.replace("\t", "    ")
        if line.startswith(space_prefix):
            return line[len(space_prefix):]
        return line.lstrip("\t")

    def list_tables(self, definition_path: str) -> list:
        """List tables and their partition counts without extracting full M code.

        Returns list of dicts with table_name, partition_count, source_file.
        """
        extracts = self.extract_from_folder(definition_path)
        tables = {}
        for e in extracts:
            key = e["table_name"]
            if key not in tables:
                tables[key] = {
                    "table_name": key,
                    "partition_count": 0,
                    "source_file": e["source_file"],
                    "mode": e["mode"],
                }
            tables[key]["partition_count"] += 1
        return list(tables.values())
