"""
Static mapping dictionaries for M-to-PySpark conversion.

Maps Power Query M types, functions, operators, and join kinds
to their PySpark equivalents.
"""

# M data types → PySpark types (used with .cast())
M_TO_PYSPARK_TYPES = {
    "type text": "StringType()",
    "type number": "DoubleType()",
    "Int64.Type": "LongType()",
    "Int32.Type": "IntegerType()",
    "type date": "DateType()",
    "type datetime": "TimestampType()",
    "type datetimezone": "TimestampType()",
    "type logical": "BooleanType()",
    "type binary": "BinaryType()",
    "Decimal.Type": "DecimalType(38, 18)",
    "Currency.Type": "DecimalType(19, 4)",
    "Percentage.Type": "DoubleType()",
    "type time": "StringType()",
    "type duration": "LongType()",
    "type any": "StringType()",
}

# M JoinKind → PySpark join how parameter
M_TO_PYSPARK_JOIN = {
    "JoinKind.LeftOuter": "left",
    "JoinKind.Inner": "inner",
    "JoinKind.RightOuter": "right",
    "JoinKind.FullOuter": "outer",
    "JoinKind.LeftAnti": "left_anti",
    "JoinKind.RightAnti": "right_anti",
}

# M comparison/logical operators → PySpark equivalents
M_OPERATORS = {
    "<>": "!=",
    "=": "==",
    " and ": " & ",
    " or ": " | ",
    " not ": " ~",
    "&": "+",       # string concatenation
    "??": "|",      # null coalescing (approximate)
}

# M text functions → PySpark F.* functions
M_TO_PYSPARK_TEXT = {
    "Text.Upper": "F.upper",
    "Text.Lower": "F.lower",
    "Text.Trim": "F.trim",
    "Text.TrimStart": "F.ltrim",
    "Text.TrimEnd": "F.rtrim",
    "Text.Length": "F.length",
    "Text.Start": "F.substring",          # needs (col, 1, n)
    "Text.End": "F.substring",            # needs special handling
    "Text.Contains": "F.col({col}).contains({val})",
    "Text.StartsWith": "F.col({col}).startswith({val})",
    "Text.EndsWith": "F.col({col}).endswith({val})",
    "Text.Replace": "F.regexp_replace",
    "Text.Combine": "F.concat",
    "Text.Split": "F.split",
    "Text.PadStart": "F.lpad",
    "Text.PadEnd": "F.rpad",
    "Text.Reverse": "F.reverse",
    "Text.From": "F.col({col}).cast(StringType())",
}

# M date functions → PySpark F.* functions
M_TO_PYSPARK_DATE = {
    "Date.Year": "F.year",
    "Date.Month": "F.month",
    "Date.Day": "F.dayofmonth",
    "Date.DayOfWeek": "F.dayofweek",
    "Date.DayOfYear": "F.dayofyear",
    "Date.From": "F.to_date",
    "DateTime.From": "F.to_timestamp",
    "Date.AddDays": "F.date_add",
    "Date.AddMonths": "F.add_months",
    "Date.AddYears": "F.date_add",  # needs year * 365 approximation
    "DateTime.LocalNow": "F.current_timestamp",
    "Date.FromText": "F.to_date",
    "DateTime.FromText": "F.to_timestamp",
}

# M number functions → PySpark F.* functions
M_TO_PYSPARK_NUMBER = {
    "Number.Round": "F.round",
    "Number.RoundDown": "F.floor",
    "Number.RoundUp": "F.ceil",
    "Number.Abs": "F.abs",
    "Number.From": "F.col({col}).cast(DoubleType())",
    "Int64.From": "F.col({col}).cast(LongType())",
    "Number.IsEven": None,  # custom: F.col(x) % 2 == 0
    "Number.IsOdd": None,   # custom: F.col(x) % 2 != 0
}

# M aggregation functions → PySpark F.* aggregate functions
M_TO_PYSPARK_AGG = {
    "List.Sum": "F.sum",
    "List.Average": "F.avg",
    "List.Min": "F.min",
    "List.Max": "F.max",
    "List.Count": "F.count",
    "List.Distinct": "F.countDistinct",
    "List.First": "F.first",
    "List.Last": "F.last",
}

# M source functions → data source type identifiers
M_SOURCE_FUNCTIONS = {
    "Sql.Database",
    "Sql.Databases",
    "Oracle.Database",
    "Odbc.DataSource",
    "OleDb.DataSource",
    "Csv.Document",
    "Excel.Workbook",
    "Excel.CurrentWorkbook",
    "Json.Document",
    "Xml.Document",
    "Web.Contents",
    "SharePoint.Files",
    "SharePoint.Contents",
    "Folder.Files",
    "File.Contents",
    "AzureStorage.Blobs",
    "Sql.Server",
    "Lakehouse.Contents",
}

# M Table.* functions → step type classification
M_TABLE_FUNCTIONS = {
    "Table.SelectRows": "filter",
    "Table.AddColumn": "add_column",
    "Table.RenameColumns": "rename",
    "Table.RemoveColumns": "remove_columns",
    "Table.SelectColumns": "select_columns",
    "Table.TransformColumnTypes": "change_types",
    "Table.Sort": "sort",
    "Table.Group": "group_by",
    "Table.NestedJoin": "join",
    "Table.ExpandTableColumn": "expand_join",
    "Table.Distinct": "distinct",
    "Table.Combine": "union",
    "Table.ReplaceValue": "replace_value",
    "Table.FillDown": "fill_down",
    "Table.FillUp": "fill_up",
    "Table.Pivot": "pivot",
    "Table.Unpivot": "unpivot",
    "Table.UnpivotOtherColumns": "unpivot_other",
    "Table.DuplicateColumn": "duplicate_column",
    "Table.TransformColumns": "transform_columns",
    "Table.FirstN": "first_n",
    "Table.LastN": "last_n",
    "Table.Skip": "skip",
    "Table.Buffer": "cache",
    "Table.PromoteHeaders": "promote_headers",
    "Table.RemoveFirstN": "skip",
    "Table.RemoveLastN": "remove_last_n",
}

# M sort order → PySpark order
M_SORT_ORDER = {
    "Order.Ascending": "asc",
    "Order.Descending": "desc",
}

# M Replacer types
M_REPLACER = {
    "Replacer.ReplaceText": "text",
    "Replacer.ReplaceValue": "value",
}


def get_pyspark_type(m_type: str) -> str:
    """Convert M type string to PySpark type. Returns StringType() for unknown."""
    m_type = m_type.strip().strip('"').strip("'")
    return M_TO_PYSPARK_TYPES.get(m_type, "StringType()")


def get_step_type(function_name: str) -> str:
    """Get the step type classification for an M function."""
    return M_TABLE_FUNCTIONS.get(function_name, "unknown")


def is_source_function(function_name: str) -> bool:
    """Check if the M function is a data source function."""
    return function_name in M_SOURCE_FUNCTIONS


def get_join_type(m_join_kind: str) -> str:
    """Convert M JoinKind to PySpark join how parameter."""
    return M_TO_PYSPARK_JOIN.get(m_join_kind.strip(), "left")


def get_sort_order(m_order: str) -> str:
    """Convert M sort order to PySpark asc/desc."""
    return M_SORT_ORDER.get(m_order.strip(), "asc")


def get_agg_function(m_agg: str) -> str:
    """Convert M aggregation function to PySpark F.* function."""
    return M_TO_PYSPARK_AGG.get(m_agg, f"F.first")
