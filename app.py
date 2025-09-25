from fastmcp import FastMCP  # user the FastMCP v2.0 implementation which is faster https://gofastmcp.com/getting-started/installation
import pandas as pd
from dotenv import load_dotenv
from logging_config import StreamingSafeRequestLoggingMiddleware, log_tool
from auth import TokenAuthMiddleware
from db import (
    init_titanic_db as _init_titanic_db,
    list_tables as _list_tables,
    describe_table as _describe_table,
    sample_rows as _sample_rows,
    run_sql as _run_sql,
    value_counts as _value_counts,
    summary_stats as _summary_stats,
    survival_rate_by as _survival_rate_by,
    load_local_csv as _load_local_csv,
)

# Load environment variables from a .env file if present
load_dotenv()

mcp = FastMCP(
    name="Titanic Dataset MCP",
    instructions="MCP server exposing tools for exploring the Titanic dataset"
)

# === Titanic dataset tools ===

@mcp.tool
@log_tool
def init_titanic_db(force: bool = False) -> dict:
    """
    Download and load the Titanic dataset into SQLite at DB_PATH (env, default shared_data/titanic.db).
    """
    return _init_titanic_db(force=force)

@mcp.tool
@log_tool
def list_tables() -> dict:
    """List available tables."""
    return {"tables": _list_tables()}

@mcp.tool
@log_tool
def describe_table(table: str) -> dict:
    """Describe columns and row count for a table."""
    return _describe_table(table)

@mcp.tool
@log_tool
def sample_rows(table: str, limit: int = 5) -> dict:
    """Return a small sample of rows."""
    return _sample_rows(table, limit)

@mcp.tool
@log_tool
def value_counts(table: str, column: str, limit: int = 50) -> dict:
    """Top values and counts for a categorical column."""
    return _value_counts(table, column, limit)

@mcp.tool
@log_tool
def summary_stats(table: str, columns: list[str] | None = None) -> dict:
    """Summary statistics for numeric columns or a subset."""
    return _summary_stats(table, columns)

@mcp.tool
@log_tool
def survival_rate_by(column: str) -> dict:
    """Survival rate grouped by a column (e.g., Sex, Pclass, Embarked)."""
    return _survival_rate_by(column)

@mcp.tool
@log_tool
def run_sql(sql: str, limit: int = 500) -> dict:
    """
    Run a guarded SELECT query (single statement) with a row limit.
    Only allowed on whitelisted tables.
    """
    return _run_sql(sql, limit)

@mcp.tool
@log_tool
def load_titanic_from_csv(csv_path: str, force: bool = False) -> dict:
    """
    Load Titanic data from a local CSV file into the SQLite database.
    csv_path can be relative to the project root or absolute.
    """
    return _load_local_csv(csv_path, force)

app = mcp.http_app(path="/mcp")
app.add_middleware(StreamingSafeRequestLoggingMiddleware)
app.add_middleware(TokenAuthMiddleware)