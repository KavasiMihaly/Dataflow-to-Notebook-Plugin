#!/usr/bin/env python3
"""
Fabric Lakehouse Reader Skill
Query Fabric lakehouse SQL analytics endpoints with read-only access.
Exports results to CSV in "7 - Data Exports" folder.
"""

import argparse
import sys
import os
import re
import struct
from datetime import datetime
from pathlib import Path
from typing import Optional


def _load_plugin_userconfig_env():
    """Map Claude Code plugin userConfig values to FABRIC_* env vars.

    When this script is invoked from inside the fabric-dataflow-migration-toolkit
    plugin, Claude Code exports userConfig values as CLAUDE_PLUGIN_OPTION_<key>.
    The script's argparse defaults read FABRIC_* / AZURE_* names. Without this
    remap the defaults silently fall back to None.
    """
    mapping = {
        'FABRIC_TENANT_ID': 'azure_tenant_id',
        'FABRIC_CLIENT_ID': 'azure_client_id',
        'FABRIC_CLIENT_SECRET': 'azure_client_secret',
        'FABRIC_SQL_ENDPOINT': 'fabric_sql_endpoint',
        'FABRIC_DATABASE': 'fabric_workspace_name',
    }
    for key, plugin_key in mapping.items():
        if not os.environ.get(key):
            fallback = os.environ.get(f'CLAUDE_PLUGIN_OPTION_{plugin_key}')
            if fallback:
                os.environ[key] = fallback


_load_plugin_userconfig_env()


try:
    import pyodbc
except ImportError:
    print("ERROR: pyodbc not installed. Run: pip install pyodbc")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas not installed. Run: pip install pandas")
    sys.exit(1)


class FabricLakehouseReader:
    """Read-only Fabric lakehouse query executor with CSV export."""

    # SQL keywords that indicate write operations (blocked)
    WRITE_OPERATIONS = [
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER',
        'CREATE', 'TRUNCATE', 'EXECUTE', 'EXEC', 'MERGE',
        'GRANT', 'REVOKE', 'DENY'
    ]

    def __init__(
        self,
        endpoint: str,
        database: str,
        auth_method: str = 'azure_cli',
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        timeout: int = 30,
        verbose: bool = False
    ):
        """Initialize Fabric lakehouse connection parameters."""
        self.endpoint = endpoint
        self.database = database
        self.auth_method = auth_method
        self.tenant_id = tenant_id or os.environ.get('FABRIC_TENANT_ID')
        self.client_id = client_id or os.environ.get('FABRIC_CLIENT_ID')
        self.client_secret = client_secret or os.environ.get('FABRIC_CLIENT_SECRET')
        self.timeout = timeout
        self.verbose = verbose
        self.connection = None

        # Set up export directory
        self.export_dir = self._find_export_dir()
        self.export_dir.mkdir(exist_ok=True)

    def _find_export_dir(self) -> Path:
        """Find or create the export directory."""
        # Walk up from CWD to find project root (has 7 - Data Exports)
        current = Path.cwd()
        for path in [current] + list(current.parents):
            export_dir = path / '7 - Data Exports'
            if export_dir.exists():
                return export_dir

        # Default: create in CWD
        return Path.cwd() / '7 - Data Exports'

    def _log(self, message: str):
        """Print message if verbose mode enabled."""
        if self.verbose:
            print(f"[INFO] {message}")

    def connect(self) -> bool:
        """Establish connection to Fabric SQL analytics endpoint."""
        try:
            if self.auth_method == 'service_principal':
                return self._connect_service_principal()
            else:
                return self._connect_azure_cli()

        except Exception as e:
            print(f"ERROR: Connection failed: {e}", file=sys.stderr)
            return False

    def _connect_service_principal(self) -> bool:
        """Connect using service principal credentials."""
        if not all([self.tenant_id, self.client_id, self.client_secret]):
            print("ERROR: Service principal requires --tenant-id, --client-id, --client-secret", file=sys.stderr)
            print("Or set FABRIC_TENANT_ID, FABRIC_CLIENT_ID, FABRIC_CLIENT_SECRET env vars", file=sys.stderr)
            return False

        connection_string = (
            "Driver={ODBC Driver 18 for SQL Server};"
            f"Server={self.endpoint},1433;"
            f"Database={self.database};"
            f"UID={self.client_id}@{self.tenant_id};"
            f"PWD={self.client_secret};"
            "Authentication=ActiveDirectoryServicePrincipal;"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
            f"Connection Timeout={self.timeout};"
        )

        self._log(f"Connecting to {self.endpoint}/{self.database} (service principal)...")
        self.connection = pyodbc.connect(connection_string)
        self._log("Connected successfully")
        return True

    def _connect_azure_cli(self) -> bool:
        """Connect using Azure CLI / DefaultAzureCredential token."""
        try:
            from azure.identity import DefaultAzureCredential
        except ImportError:
            print("ERROR: azure-identity not installed. Run: pip install azure-identity", file=sys.stderr)
            return False

        self._log(f"Connecting to {self.endpoint}/{self.database} (Azure CLI)...")

        # Get access token
        credential = DefaultAzureCredential()
        token = credential.get_token("https://database.windows.net/.default")

        # Convert token to ODBC access token struct
        token_bytes = token.token.encode("UTF-16-LE")
        token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

        # Build connection string (no UID/PWD - token-based)
        connection_string = (
            "Driver={ODBC Driver 18 for SQL Server};"
            f"Server={self.endpoint},1433;"
            f"Database={self.database};"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
            f"Connection Timeout={self.timeout};"
        )

        # SQL_COPT_SS_ACCESS_TOKEN = 1256
        self.connection = pyodbc.connect(connection_string, attrs_before={1256: token_struct})
        self._log("Connected successfully")
        return True

    def disconnect(self):
        """Close database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None
        self._log("Disconnected")

    def validate_query(self, query: str) -> tuple:
        """
        Validate query is read-only (SELECT statements only).

        Returns:
            (is_valid, error_message)
        """
        query_upper = query.upper()

        # Check for write operations
        for operation in self.WRITE_OPERATIONS:
            pattern = r'\b' + operation + r'\b'
            if re.search(pattern, query_upper):
                return False, f"Query contains prohibited operation: {operation}"

        # Must contain SELECT (or WITH for CTEs)
        if 'SELECT' not in query_upper and 'WITH' not in query_upper:
            return False, "Query must be a SELECT statement"

        return True, ""

    def list_tables(self) -> pd.DataFrame:
        """List all tables in the lakehouse."""
        query = """
        SELECT
            TABLE_SCHEMA as [Schema],
            TABLE_NAME as [Table],
            TABLE_TYPE as [Type]
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW')
        ORDER BY TABLE_SCHEMA, TABLE_NAME
        """

        self._log("Fetching table list...")
        df = pd.read_sql(query, self.connection)

        # Save to CSV
        output_file = self.export_dir / 'table_list.csv'
        df.to_csv(output_file, index=False)
        self._log(f"Saved to {output_file}")

        return df

    def get_table_schema(self, table_name: str) -> pd.DataFrame:
        """Get schema information for a specific table."""
        query = """
        SELECT
            COLUMN_NAME as [Column],
            DATA_TYPE as [Type],
            CHARACTER_MAXIMUM_LENGTH as [Max_Length],
            IS_NULLABLE as [Nullable],
            COLUMN_DEFAULT as [Default]
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """

        self._log(f"Fetching schema for table: {table_name}")
        cursor = self.connection.cursor()
        cursor.execute(query, table_name)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

        df = pd.DataFrame.from_records(rows, columns=columns)

        if df.empty:
            print(f"WARNING: Table '{table_name}' not found", file=sys.stderr)
            return df

        # Save to CSV
        output_file = self.export_dir / f'schema_{table_name}.csv'
        df.to_csv(output_file, index=False)
        self._log(f"Saved to {output_file}")

        return df

    def execute_query(
        self,
        query: str,
        limit: Optional[int] = None,
        output_filename: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Execute SELECT query and return results.

        Args:
            query: SQL SELECT statement
            limit: Maximum rows to return (adds TOP clause)
            output_filename: Custom filename for CSV export
        """
        # Validate query is read-only
        is_valid, error_msg = self.validate_query(query)
        if not is_valid:
            print(f"ERROR: Invalid query: {error_msg}", file=sys.stderr)
            print("Only SELECT statements are allowed.", file=sys.stderr)
            sys.exit(1)

        # Add limit if specified
        if limit:
            query = f"SELECT TOP {limit} * FROM ({query}) AS limited_query"

        self._log("Executing query...")
        start_time = datetime.now()

        try:
            df = pd.read_sql(query, self.connection)
            elapsed = (datetime.now() - start_time).total_seconds()

            self._log(f"Query executed in {elapsed:.2f}s")
            self._log(f"Returned {len(df)} rows, {len(df.columns)} columns")

            # Save to CSV
            if output_filename:
                output_file = self.export_dir / output_filename
            else:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_file = self.export_dir / f'query_results_{timestamp}.csv'

            df.to_csv(output_file, index=False)
            self._log(f"Saved to {output_file}")

            # Warn if result set is large
            if len(df) >= 10000:
                print(f"WARNING: Large result set: {len(df)} rows. Consider adding --limit")

            return df

        except pyodbc.Error as e:
            print(f"ERROR: Query execution failed: {e}", file=sys.stderr)
            sys.exit(1)

    def export_table(
        self,
        table_name: str,
        limit: Optional[int] = None,
        output_filename: Optional[str] = None
    ) -> pd.DataFrame:
        """Export entire table to CSV."""
        query = f"SELECT * FROM {table_name}"

        if not output_filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_filename = f'{table_name}_{timestamp}.csv'

        return self.execute_query(query, limit=limit, output_filename=output_filename)

    def test_connection(self) -> bool:
        """Test database connection and print diagnostics."""
        print("Testing Fabric SQL analytics endpoint connection...")
        print(f"Endpoint: {self.endpoint}")
        print(f"Database: {self.database}")
        print(f"Auth method: {self.auth_method}")
        print(f"Driver: ODBC Driver 18 for SQL Server")
        print()

        if not self.connect():
            return False

        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT @@VERSION as Version, DB_NAME() as DatabaseName")
            row = cursor.fetchone()

            print("Connection successful!")
            print(f"Database: {row.DatabaseName}")
            print(f"Server: {row.Version[:100]}...")

            # List available tables
            df_tables = self.list_tables()
            print(f"\nFound {len(df_tables)} tables/views")

            return True

        except pyodbc.Error as e:
            print(f"ERROR: Connection test failed: {e}", file=sys.stderr)
            return False


def find_project_config():
    """
    Find project-config.yml and extract SQL endpoint and database defaults.
    Returns (endpoint, database) or (None, None).
    """
    current = Path.cwd()

    for path in [current] + list(current.parents):
        config_file = path / "0 - Architecture Setup" / "project-config.yml"
        if config_file.exists():
            endpoint = None
            database = None
            try:
                with open(config_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("sql_endpoint:"):
                            endpoint = line.split(":", 1)[1].strip().strip('"').strip("'")
                        elif line.startswith("bronze_lakehouse:"):
                            # Default to bronze lakehouse
                            database = line.split(":", 1)[1].strip().strip('"').strip("'")
            except Exception:
                pass
            return endpoint, database

    return None, None


def main():
    """Main CLI entry point."""
    # Check for project config defaults
    default_endpoint, default_database = find_project_config()

    parser = argparse.ArgumentParser(
        description='Query Fabric lakehouse SQL analytics endpoint (read-only)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test connection
  python query_fabric_lakehouse.py --test-connection --endpoint EP --database DB

  # List all tables
  python query_fabric_lakehouse.py --list-tables --endpoint EP --database DB

  # Get table schema
  python query_fabric_lakehouse.py --schema bronze_customers --endpoint EP --database DB

  # Execute query
  python query_fabric_lakehouse.py --query "SELECT TOP 10 * FROM bronze_customers" --endpoint EP --database DB

  # Export table
  python query_fabric_lakehouse.py --export bronze_customers --limit 1000 --endpoint EP --database DB

  # Query from file
  python query_fabric_lakehouse.py --query-file analysis.sql --endpoint EP --database DB
        """
    )

    # Connection parameters
    parser.add_argument(
        '--endpoint',
        default=default_endpoint or os.environ.get('FABRIC_SQL_ENDPOINT'),
        help='Fabric SQL analytics endpoint (e.g., xxx.datawarehouse.fabric.microsoft.com)'
    )
    parser.add_argument(
        '--database',
        default=default_database or os.environ.get('FABRIC_DATABASE'),
        help='Lakehouse database name (e.g., lh_bronze)'
    )
    parser.add_argument(
        '--auth-method',
        choices=['azure_cli', 'service_principal'],
        default='azure_cli',
        help='Authentication method (default: azure_cli)'
    )
    parser.add_argument('--tenant-id', help='Azure tenant ID (service principal auth)')
    parser.add_argument('--client-id', help='Azure client ID (service principal auth)')
    parser.add_argument('--client-secret', help='Azure client secret (service principal auth)')
    parser.add_argument('--timeout', type=int, default=30, help='Connection timeout in seconds')

    # Operations
    parser.add_argument('--list-tables', action='store_true', help='List all tables')
    parser.add_argument('--schema', metavar='TABLE', help='Get table schema')
    parser.add_argument('--query', metavar='SQL', help='Execute SELECT query')
    parser.add_argument('--query-file', metavar='FILE', help='Execute query from file')
    parser.add_argument('--export', metavar='TABLE', help='Export table to CSV')
    parser.add_argument('--test-connection', action='store_true', help='Test endpoint connection')

    # Options
    parser.add_argument('--limit', type=int, help='Limit number of rows returned')
    parser.add_argument('--output', metavar='FILE', help='Custom output filename')
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')

    args = parser.parse_args()

    # Validate connection parameters
    if not args.test_connection and not any([
        args.list_tables, args.schema, args.query, args.query_file, args.export
    ]):
        parser.print_help()
        return 0

    if not args.endpoint:
        print("ERROR: --endpoint is required (or set FABRIC_SQL_ENDPOINT env var)", file=sys.stderr)
        print("Find your SQL endpoint in Fabric portal: Lakehouse > SQL analytics endpoint", file=sys.stderr)
        return 1

    if not args.database:
        print("ERROR: --database is required (or set FABRIC_DATABASE env var)", file=sys.stderr)
        return 1

    # Create reader instance
    reader = FabricLakehouseReader(
        endpoint=args.endpoint,
        database=args.database,
        auth_method=args.auth_method,
        tenant_id=args.tenant_id,
        client_id=args.client_id,
        client_secret=args.client_secret,
        timeout=args.timeout,
        verbose=args.verbose
    )

    # Test connection mode
    if args.test_connection:
        success = reader.test_connection()
        reader.disconnect()
        return 0 if success else 1

    # Connect to endpoint
    if not reader.connect():
        return 1

    try:
        # Execute requested operation
        if args.list_tables:
            df = reader.list_tables()
            print("\n" + df.to_string(index=False))
            print(f"\nTotal: {len(df)} tables/views")
            print(f"Saved to: 7 - Data Exports/table_list.csv")

        elif args.schema:
            df = reader.get_table_schema(args.schema)
            if not df.empty:
                print("\n" + df.to_string(index=False))
                print(f"\nSaved to: 7 - Data Exports/schema_{args.schema}.csv")

        elif args.query:
            df = reader.execute_query(args.query, limit=args.limit, output_filename=args.output)
            print("\n" + df.to_string(index=False, max_rows=20))
            if len(df) > 20:
                print(f"... ({len(df) - 20} more rows)")

        elif args.query_file:
            query_path = Path(args.query_file)
            if not query_path.exists():
                print(f"ERROR: Query file not found: {args.query_file}", file=sys.stderr)
                return 1

            query = query_path.read_text()
            df = reader.execute_query(query, limit=args.limit, output_filename=args.output)
            print("\n" + df.to_string(index=False, max_rows=20))
            if len(df) > 20:
                print(f"... ({len(df) - 20} more rows)")

        elif args.export:
            df = reader.export_table(args.export, limit=args.limit, output_filename=args.output)
            print(f"Exported {len(df)} rows from '{args.export}'")
            print(f"Columns: {', '.join(df.columns.tolist())}")

    finally:
        reader.disconnect()

    return 0


if __name__ == '__main__':
    sys.exit(main())
