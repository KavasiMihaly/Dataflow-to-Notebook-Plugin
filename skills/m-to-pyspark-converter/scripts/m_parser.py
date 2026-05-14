"""
Parse Power Query M let/in expressions into a structured intermediate representation.

Handles the common M patterns found in PBIP semantic models:
- let/in blocks with named steps
- Table.* transformation functions
- Source/navigation patterns (Sql.Database, schema navigation)
- Quoted identifiers (#"Column Name")
- each [...] expressions
"""

import re
from function_map import M_TABLE_FUNCTIONS, M_SOURCE_FUNCTIONS, is_source_function


class MParser:
    """Parses M code into an intermediate representation for PySpark generation."""

    def parse(self, m_code: str) -> dict:
        """Parse a complete M expression.

        Args:
            m_code: Raw M code string (typically a let/in block).

        Returns:
            Dict with steps, return_step, parameters, raw_m_code.
        """
        m_code = m_code.strip()

        # Handle non-let/in expressions (simple single-line M)
        if not self._has_let_in(m_code):
            return {
                "steps": [
                    {
                        "name": "Source",
                        "type": "unknown",
                        "function": None,
                        "args": {},
                        "raw": m_code,
                    }
                ],
                "return_step": "Source",
                "parameters": [],
                "raw_m_code": m_code,
            }

        let_body, return_expr = self._split_let_in(m_code)
        raw_steps = self._extract_steps(let_body)

        steps = []
        for name, expression in raw_steps:
            step = self._parse_step(name, expression)
            steps.append(step)

        return {
            "steps": steps,
            "return_step": return_expr.strip(),
            "parameters": self._extract_parameters(steps),
            "raw_m_code": m_code,
        }

    def _has_let_in(self, m_code: str) -> bool:
        """Check if the M code contains a let/in structure."""
        return bool(re.search(r"(?:^|\s)let\b", m_code, re.IGNORECASE))

    def _split_let_in(self, m_code: str) -> tuple:
        """Split M code into the let body and the in return expression.

        Returns:
            Tuple of (let_body, return_expression).
        """
        # Find the outermost 'let' and final 'in'
        # The final 'in' at the same nesting level as 'let'
        let_match = re.search(r"(?:^|\s)(let)\b", m_code, re.IGNORECASE)
        if not let_match:
            return m_code, ""

        let_start = let_match.end()

        # Find the matching 'in' - it's the last 'in' at the base indentation
        # or after matching nested let/in pairs
        depth = 1
        pos = let_start
        in_pos = None

        while pos < len(m_code):
            # Look for 'let' or 'in' keywords at word boundaries
            let_inner = re.search(r"\blet\b", m_code[pos:], re.IGNORECASE)
            in_inner = re.search(r"\bin\b", m_code[pos:], re.IGNORECASE)

            let_idx = (pos + let_inner.start()) if let_inner else len(m_code)
            in_idx = (pos + in_inner.start()) if in_inner else len(m_code)

            if let_idx == len(m_code) and in_idx == len(m_code):
                break

            if let_idx < in_idx:
                # Check it's not inside a string or part of another word
                if self._is_keyword(m_code, let_idx, "let"):
                    depth += 1
                pos = let_idx + 3
            else:
                if self._is_keyword(m_code, in_idx, "in"):
                    depth -= 1
                    if depth == 0:
                        in_pos = in_idx
                        break
                pos = in_idx + 2

        if in_pos is not None:
            let_body = m_code[let_start:in_pos].strip()
            return_expr = m_code[in_pos + 2:].strip()
        else:
            let_body = m_code[let_start:].strip()
            return_expr = ""

        return let_body, return_expr

    def _is_keyword(self, text: str, pos: int, keyword: str) -> bool:
        """Check if the word at pos is a standalone keyword (not part of identifier)."""
        # Check character before
        if pos > 0:
            before = text[pos - 1]
            if before.isalnum() or before == "_" or before == '"':
                return False
        # Check character after
        end = pos + len(keyword)
        if end < len(text):
            after = text[end]
            if after.isalnum() or after == "_":
                return False
        return True

    def _extract_steps(self, let_body: str) -> list:
        """Extract named steps from the let body.

        Handles both:
            StepName = expression,
            #"Step Name" = expression,

        Returns list of (name, expression) tuples.

        Uses balanced delimiter tracking to correctly handle commas inside
        braces, brackets, and parentheses (e.g., navigation expressions).
        """
        steps = []

        # First, split the let body into top-level comma-separated segments
        # respecting nested delimiters and strings
        segments = self._split_top_level_steps(let_body)

        for segment in segments:
            segment = segment.strip()
            if not segment:
                continue

            # Match assignment: StepName = expr or #"Step Name" = expr
            assign_match = re.match(
                r'(#"[^"]+"|[A-Za-z_]\w*)\s*=\s*', segment
            )
            if assign_match:
                name = assign_match.group(1).strip()
                if name.startswith('#"') and name.endswith('"'):
                    name = name[2:-1]
                expression = segment[assign_match.end():].strip()
                steps.append((name, expression))

        return steps

    def _split_top_level_steps(self, text: str) -> list:
        """Split let body by top-level commas, respecting nested delimiters."""
        parts = []
        depth_paren = 0
        depth_brace = 0
        depth_bracket = 0
        in_string = False
        current = []

        i = 0
        while i < len(text):
            ch = text[i]

            if in_string:
                current.append(ch)
                if ch == '"':
                    # Check for escaped quote (doubled)
                    if i + 1 < len(text) and text[i + 1] == '"':
                        current.append('"')
                        i += 2
                        continue
                    in_string = False
                i += 1
                continue

            if ch == '"':
                in_string = True
                current.append(ch)
            elif ch == '(':
                depth_paren += 1
                current.append(ch)
            elif ch == ')':
                depth_paren -= 1
                current.append(ch)
            elif ch == '{':
                depth_brace += 1
                current.append(ch)
            elif ch == '}':
                depth_brace -= 1
                current.append(ch)
            elif ch == '[':
                depth_bracket += 1
                current.append(ch)
            elif ch == ']':
                depth_bracket -= 1
                current.append(ch)
            elif ch == ',' and depth_paren == 0 and depth_brace == 0 and depth_bracket == 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(ch)

            i += 1

        if current:
            parts.append("".join(current))

        return parts

    def _parse_step(self, step_name: str, expression: str) -> dict:
        """Classify a single step by detecting the M function used.

        Returns dict with name, type, function, args, raw, and type-specific fields.
        """
        func_name, func_args_str = self._identify_function(expression)

        # Determine step type
        if func_name and is_source_function(func_name):
            return self._parse_source_step(step_name, expression, func_name, func_args_str)

        if func_name and func_name in M_TABLE_FUNCTIONS:
            step_type = M_TABLE_FUNCTIONS[func_name]
            step = {
                "name": step_name,
                "type": step_type,
                "function": func_name,
                "raw": expression,
            }
            # Parse type-specific details
            parser = getattr(self, f"_parse_{step_type}", None)
            if parser:
                step.update(parser(expression))
            return step

        # Check for navigation pattern: Source{[Schema="dbo", Item="Table"]}[Data]
        if self._is_navigation(expression):
            return self._parse_navigation(step_name, expression)

        return {
            "name": step_name,
            "type": "unknown",
            "function": func_name,
            "args": {},
            "raw": expression,
        }

    def _identify_function(self, expression: str) -> tuple:
        """Detect the M function name and its arguments string.

        Returns (function_name, args_string) or (None, None).
        """
        # Match patterns like Table.SelectRows(...) or Sql.Database(...)
        match = re.match(r"([A-Za-z]+\.[A-Za-z]+)\s*\(", expression)
        if match:
            func_name = match.group(1)
            # Extract the arguments (handling nested parentheses)
            paren_start = match.end() - 1
            args_str = self._extract_balanced(expression, paren_start, "(", ")")
            return func_name, args_str
        return None, None

    def _extract_balanced(self, text: str, start: int, open_ch: str, close_ch: str) -> str:
        """Extract content between balanced delimiters."""
        if start >= len(text) or text[start] != open_ch:
            return ""
        depth = 0
        in_string = False
        string_char = None
        i = start
        while i < len(text):
            ch = text[i]
            if in_string:
                if ch == string_char and (i + 1 >= len(text) or text[i + 1] != string_char):
                    in_string = False
                elif ch == string_char and i + 1 < len(text) and text[i + 1] == string_char:
                    i += 1  # skip escaped quote
            else:
                if ch == '"':
                    in_string = True
                    string_char = '"'
                elif ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0:
                        return text[start + 1:i]
            i += 1
        return text[start + 1:]

    def _is_navigation(self, expression: str) -> bool:
        """Check if expression is a table navigation pattern."""
        return bool(re.search(r'\{?\[.*?\]\}?\s*\[Data\]', expression))

    def _parse_navigation(self, step_name: str, expression: str) -> dict:
        """Parse navigation expressions like Source{[Schema="dbo", Item="Table"]}[Data]."""
        schema = None
        table = None
        item = None

        schema_match = re.search(r'Schema\s*=\s*"([^"]*)"', expression)
        if schema_match:
            schema = schema_match.group(1)

        item_match = re.search(r'Item\s*=\s*"([^"]*)"', expression)
        if item_match:
            item = item_match.group(1)

        table_match = re.search(r'Name\s*=\s*"([^"]*)"', expression)
        if table_match:
            table = table_match.group(1)

        return {
            "name": step_name,
            "type": "navigation",
            "function": None,
            "schema": schema,
            "table": item or table,
            "raw": expression,
        }

    def _parse_source_step(self, step_name: str, expression: str, func_name: str, args_str: str) -> dict:
        """Parse a data source step."""
        step = {
            "name": step_name,
            "type": "source",
            "function": func_name,
            "raw": expression,
            "args": {},
        }

        if func_name in ("Sql.Database", "Sql.Databases"):
            # Extract server and database from args
            strings = re.findall(r'"([^"]*)"', args_str or "")
            if len(strings) >= 2:
                step["args"]["server"] = strings[0]
                step["args"]["database"] = strings[1]
            elif len(strings) == 1:
                step["args"]["server"] = strings[0]

        elif func_name == "Csv.Document":
            step["args"]["format"] = "csv"

        elif func_name in ("Excel.Workbook", "Excel.CurrentWorkbook"):
            step["args"]["format"] = "excel"

        return step

    # --- Type-specific parsers ---

    def _parse_filter(self, expression: str) -> dict:
        """Parse Table.SelectRows condition."""
        # Extract the each clause
        each_match = re.search(r",\s*each\s+(.+?)\s*\)$", expression, re.DOTALL)
        condition = each_match.group(1).strip() if each_match else ""
        return {"condition": condition}

    def _parse_add_column(self, expression: str) -> dict:
        """Parse Table.AddColumn arguments."""
        args_str = self._extract_balanced(expression, expression.index("("), "(", ")")
        # Table.AddColumn(prev, "ColName", each [expr], type)
        parts = self._split_top_level(args_str)
        col_name = ""
        each_expr = ""
        col_type = None

        if len(parts) >= 2:
            col_name = parts[1].strip().strip('"')
        if len(parts) >= 3:
            each_expr = parts[2].strip()
            if each_expr.startswith("each "):
                each_expr = each_expr[5:].strip()
        if len(parts) >= 4:
            col_type = parts[3].strip()

        return {"column_name": col_name, "expression": each_expr, "column_type": col_type}

    def _parse_rename(self, expression: str) -> dict:
        """Parse Table.RenameColumns rename pairs."""
        # Extract the list of rename pairs {{old, new}, ...}
        pairs = []
        inner = re.findall(r'\{\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\}', expression)
        for old, new in inner:
            pairs.append((old, new))
        return {"renames": pairs}

    def _parse_remove_columns(self, expression: str) -> dict:
        """Parse Table.RemoveColumns column list."""
        columns = re.findall(r'"([^"]+)"', expression)
        # First match might be from the previous step reference, skip it if it matches a step name
        # The columns are inside a list {...}
        list_match = re.search(r'\{([^{}]+)\}', expression)
        if list_match:
            columns = re.findall(r'"([^"]+)"', list_match.group(1))
        return {"columns": columns}

    def _parse_select_columns(self, expression: str) -> dict:
        """Parse Table.SelectColumns column list."""
        list_match = re.search(r'\{([^{}]+)\}', expression)
        columns = []
        if list_match:
            columns = re.findall(r'"([^"]+)"', list_match.group(1))
        return {"columns": columns}

    def _parse_change_types(self, expression: str) -> dict:
        """Parse Table.TransformColumnTypes type pairs."""
        # {{"Col1", type text}, {"Col2", Int64.Type}}
        pairs = []
        type_pattern = re.findall(
            r'\{\s*"([^"]+)"\s*,\s*([^}]+)\}', expression
        )
        for col, m_type in type_pattern:
            pairs.append((col, m_type.strip()))
        return {"type_changes": pairs}

    def _parse_sort(self, expression: str) -> dict:
        """Parse Table.Sort sort specifications."""
        # {{"Col1", Order.Ascending}, {"Col2", Order.Descending}}
        sorts = []
        sort_pattern = re.findall(
            r'\{\s*"([^"]+)"\s*,\s*(Order\.\w+)\s*\}', expression
        )
        for col, order in sort_pattern:
            sorts.append((col, order))
        return {"sorts": sorts}

    def _parse_group_by(self, expression: str) -> dict:
        """Parse Table.Group arguments."""
        # Table.Group(prev, {"GroupCol1", ...}, {{"AggName", each List.Sum([Col]), type number}})
        args_str = self._extract_balanced(expression, expression.index("("), "(", ")")
        parts = self._split_top_level(args_str)

        group_cols = []
        aggregations = []

        if len(parts) >= 2:
            group_cols = re.findall(r'"([^"]+)"', parts[1])

        if len(parts) >= 3:
            # Parse aggregation definitions
            agg_pattern = re.findall(
                r'\{\s*"([^"]+)"\s*,\s*each\s+([^,}]+)', parts[2]
            )
            for agg_name, agg_expr in agg_pattern:
                aggregations.append({"name": agg_name, "expression": agg_expr.strip()})

        return {"group_columns": group_cols, "aggregations": aggregations}

    def _parse_join(self, expression: str) -> dict:
        """Parse Table.NestedJoin arguments."""
        args_str = self._extract_balanced(expression, expression.index("("), "(", ")")
        parts = self._split_top_level(args_str)

        left_key = []
        right_table = ""
        right_key = []
        join_kind = "JoinKind.LeftOuter"
        join_col_name = ""

        if len(parts) >= 2:
            # Left key columns
            left_key = re.findall(r'"([^"]+)"', parts[1])
            if not left_key:
                left_key = [parts[1].strip().strip('"')]

        if len(parts) >= 3:
            right_table = parts[2].strip().strip('"')
            # Handle #"Quoted Name"
            qt = re.match(r'#"([^"]+)"', right_table)
            if qt:
                right_table = qt.group(1)

        if len(parts) >= 4:
            right_key = re.findall(r'"([^"]+)"', parts[3])
            if not right_key:
                right_key = [parts[3].strip().strip('"')]

        if len(parts) >= 5:
            join_col_name = parts[4].strip().strip('"')

        if len(parts) >= 6:
            join_kind = parts[5].strip()

        return {
            "left_key": left_key,
            "right_table": right_table,
            "right_key": right_key,
            "join_kind": join_kind,
            "join_column_name": join_col_name,
        }

    def _parse_expand_join(self, expression: str) -> dict:
        """Parse Table.ExpandTableColumn columns to expand."""
        args_str = self._extract_balanced(expression, expression.index("("), "(", ")")
        parts = self._split_top_level(args_str)

        expand_column = ""
        columns = []
        aliases = []

        if len(parts) >= 2:
            expand_column = parts[1].strip().strip('"')

        if len(parts) >= 3:
            columns = re.findall(r'"([^"]+)"', parts[2])

        if len(parts) >= 4:
            aliases = re.findall(r'"([^"]+)"', parts[3])

        return {
            "expand_column": expand_column,
            "columns": columns,
            "aliases": aliases if aliases else columns,
        }

    def _parse_replace_value(self, expression: str) -> dict:
        """Parse Table.ReplaceValue arguments."""
        args_str = self._extract_balanced(expression, expression.index("("), "(", ")")
        parts = self._split_top_level(args_str)

        old_value = parts[1].strip().strip('"') if len(parts) >= 2 else ""
        new_value = parts[2].strip().strip('"') if len(parts) >= 3 else ""
        columns = []
        replacer = "text"

        if len(parts) >= 4:
            columns = re.findall(r'"([^"]+)"', parts[3])
        if len(parts) >= 5:
            replacer_str = parts[4].strip()
            if "ReplaceText" in replacer_str:
                replacer = "text"
            else:
                replacer = "value"

        return {
            "old_value": old_value,
            "new_value": new_value,
            "columns": columns,
            "replacer": replacer,
        }

    def _parse_distinct(self, expression: str) -> dict:
        return {}

    def _parse_union(self, expression: str) -> dict:
        """Parse Table.Combine table list."""
        list_match = re.search(r'\{([^{}]+)\}', expression)
        tables = []
        if list_match:
            tables = [t.strip().strip('"') for t in list_match.group(1).split(",")]
            # Clean #"Quoted Names"
            cleaned = []
            for t in tables:
                qt = re.match(r'#"([^"]+)"', t)
                cleaned.append(qt.group(1) if qt else t)
            tables = cleaned
        return {"tables": tables}

    def _parse_fill_down(self, expression: str) -> dict:
        list_match = re.search(r'\{([^{}]+)\}', expression)
        columns = []
        if list_match:
            columns = re.findall(r'"([^"]+)"', list_match.group(1))
        return {"columns": columns}

    def _parse_fill_up(self, expression: str) -> dict:
        return self._parse_fill_down(expression)

    def _parse_pivot(self, expression: str) -> dict:
        args_str = self._extract_balanced(expression, expression.index("("), "(", ")")
        parts = self._split_top_level(args_str)
        pivot_col = parts[1].strip().strip('"') if len(parts) >= 2 else ""
        value_col = parts[2].strip().strip('"') if len(parts) >= 3 else ""
        return {"pivot_column": pivot_col, "value_column": value_col}

    def _parse_unpivot(self, expression: str) -> dict:
        args_str = self._extract_balanced(expression, expression.index("("), "(", ")")
        parts = self._split_top_level(args_str)
        columns = []
        if len(parts) >= 2:
            columns = re.findall(r'"([^"]+)"', parts[1])
        attr_col = parts[2].strip().strip('"') if len(parts) >= 3 else "Attribute"
        val_col = parts[3].strip().strip('"') if len(parts) >= 4 else "Value"
        return {"columns": columns, "attribute_column": attr_col, "value_column": val_col}

    def _parse_unpivot_other(self, expression: str) -> dict:
        return self._parse_unpivot(expression)

    def _parse_cache(self, expression: str) -> dict:
        return {}

    def _parse_first_n(self, expression: str) -> dict:
        n_match = re.search(r',\s*(\d+)', expression)
        n = int(n_match.group(1)) if n_match else 1
        return {"n": n}

    def _parse_last_n(self, expression: str) -> dict:
        return self._parse_first_n(expression)

    def _parse_skip(self, expression: str) -> dict:
        return self._parse_first_n(expression)

    def _parse_transform_columns(self, expression: str) -> dict:
        return {}

    def _parse_duplicate_column(self, expression: str) -> dict:
        args_str = self._extract_balanced(expression, expression.index("("), "(", ")")
        parts = self._split_top_level(args_str)
        source_col = parts[1].strip().strip('"') if len(parts) >= 2 else ""
        new_col = parts[2].strip().strip('"') if len(parts) >= 3 else source_col + "_copy"
        return {"source_column": source_col, "new_column": new_col}

    def _parse_promote_headers(self, expression: str) -> dict:
        return {}

    def _parse_remove_last_n(self, expression: str) -> dict:
        return self._parse_first_n(expression)

    def _split_top_level(self, text: str) -> list:
        """Split text by commas at the top level (not inside braces/parens/strings)."""
        parts = []
        depth_paren = 0
        depth_brace = 0
        depth_bracket = 0
        in_string = False
        current = []

        for ch in text:
            if in_string:
                current.append(ch)
                if ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                current.append(ch)
            elif ch == '(':
                depth_paren += 1
                current.append(ch)
            elif ch == ')':
                depth_paren -= 1
                current.append(ch)
            elif ch == '{':
                depth_brace += 1
                current.append(ch)
            elif ch == '}':
                depth_brace -= 1
                current.append(ch)
            elif ch == '[':
                depth_bracket += 1
                current.append(ch)
            elif ch == ']':
                depth_bracket -= 1
                current.append(ch)
            elif ch == ',' and depth_paren == 0 and depth_brace == 0 and depth_bracket == 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(ch)

        if current:
            parts.append("".join(current))

        return parts

    def _extract_parameters(self, steps: list) -> list:
        """Extract Power Query parameters referenced in the steps."""
        params = []
        for step in steps:
            raw = step.get("raw", "")
            # Find parameter references like #"ParamName"
            param_refs = re.findall(r'#"([^"]+)"', raw)
            for ref in param_refs:
                if ref not in params and not any(s["name"] == ref for s in steps):
                    params.append(ref)
        return params
