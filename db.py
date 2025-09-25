import os
import re
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import pandas as pd

DB_PATH = os.environ.get("DB_PATH", "shared_data/titanic.db")
ALLOWED_TABLES = {"passengers"}


@contextmanager
def get_conn():
    dirpath = os.path.dirname(DB_PATH)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_titanic_db(force: bool = False) -> Dict[str, Any]:
    url = "https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv"
    with get_conn() as conn:
        cur = conn.cursor()
        if force:
            cur.execute("DROP TABLE IF EXISTS passengers")
            conn.commit()
        # If already exists, skip reload
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='passengers'")
        if cur.fetchone():
            return {"status": "exists", "db_path": DB_PATH}

        df = pd.read_csv(url)
        # Normalize column names (strip spaces)
        df.columns = [c.strip() for c in df.columns]
        # Persist
        df.to_sql("passengers", conn, index=False)
        # Helpful indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_passengers_survived ON passengers(Survived)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_passengers_pclass ON passengers(Pclass)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_passengers_sex ON passengers(Sex)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_passengers_embarked ON passengers(Embarked)")
        conn.commit()
        return {"status": "initialized", "rows": int(len(df)), "db_path": DB_PATH}


def list_tables() -> List[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [r[0] for r in cur.fetchall()]


def describe_table(table: str) -> Dict[str, Any]:
    if table not in ALLOWED_TABLES:
        return {"error": f"table '{table}' not allowed"}
    with get_conn() as conn:
        cur = conn.cursor()
        # Check if the table exists first
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if not cur.fetchone():
            return {"table": table, "exists": False, "columns": [], "rows": 0}
        cur.execute(f"PRAGMA table_info({table})")
        cols = [{"cid": r[0], "name": r[1], "type": r[2], "notnull": r[3], "default": r[4], "pk": r[5]} for r in cur.fetchall()]
        cur.execute(f"SELECT COUNT(1) FROM {table}")
        n = cur.fetchone()[0]
        return {"table": table, "exists": True, "columns": cols, "rows": int(n)}


def sample_rows(table: str, limit: int = 5) -> Dict[str, Any]:
    if table not in ALLOWED_TABLES:
        return {"error": f"table '{table}' not allowed"}
    limit = max(1, min(int(limit), 100))
    with get_conn() as conn:
        df = pd.read_sql_query(f"SELECT * FROM {table} LIMIT {limit}", conn)
        return {"table": table, "limit": limit, "rows": df.to_dict(orient="records")}


_SQL_BLOCKLIST = re.compile(r";|--|/\*|\bpragma\b|\battach\b|\bvacuum\b|\binsert\b|\bupdate\b|\bdelete\b|\bdrop\b|\balter\b", re.I)


def _sql_is_safe(sql: str) -> bool:
    if _SQL_BLOCKLIST.search(sql or ""):
        return False
    s = (sql or "").strip().lower()
    if not s.startswith("select"):
        return False
    # crude table whitelist
    if any(t in s for t in (" from ", " join ")):
        # require 'passengers' when selecting from tables
        if "passengers" not in s:
            return False
    return True


def run_sql(sql: str, limit: int = 500) -> Dict[str, Any]:
    if not _sql_is_safe(sql):
        return {"error": "Only single-statement SELECTs on allowed tables are permitted."}
    limit = max(1, min(int(limit), 5000))
    sql_limited = f"SELECT * FROM ({sql}) AS sub LIMIT {limit}"
    with get_conn() as conn:
        df = pd.read_sql_query(sql_limited, conn)
        return {
            "columns": list(df.columns),
            "row_count": int(len(df)),
            "rows": df.to_dict(orient="records"),
        }


def value_counts(table: str, column: str, limit: int = 50) -> Dict[str, Any]:
    if table not in ALLOWED_TABLES:
        return {"error": f"table '{table}' not allowed"}
    col = re.sub(r"[^A-Za-z0-9_]", "", column)
    limit = max(1, min(int(limit), 1000))
    q = f"""
      SELECT {col} AS value, COUNT(*) AS cnt
      FROM {table}
      GROUP BY {col}
      ORDER BY cnt DESC
      LIMIT {limit}
    """
    with get_conn() as conn:
        df = pd.read_sql_query(q, conn)
        return {"table": table, "column": col, "rows": df.to_dict(orient="records")}


def summary_stats(table: str, columns: Optional[List[str]] = None) -> Dict[str, Any]:
    if table not in ALLOWED_TABLES:
        return {"error": f"table '{table}' not allowed"}
    with get_conn() as conn:
        df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
    if columns:
        cols = [c for c in columns if c in df.columns]
        if not cols:
            return {"error": "no specified columns found"}
        df = df[cols]
    desc = df.describe(include="all", datetime_is_numeric=True).transpose().reset_index(names="column")
    return {"rows": desc.to_dict(orient="records")}


def survival_rate_by(column: str) -> Dict[str, Any]:
    col = re.sub(r"[^A-Za-z0-9_]", "", column)
    with get_conn() as conn:
        df = pd.read_sql_query("SELECT Survived, {} AS grp FROM passengers".format(col), conn)
    if "Survived" not in df.columns or "grp" not in df.columns:
        return {"error": "invalid column"}
    rates = (
        df.dropna(subset=["grp"])\
          .groupby("grp")["Survived"]
          .mean()
          .reset_index(name="survival_rate")
          .sort_values("survival_rate", ascending=False)
    )
    return {"by": col, "rows": rates.to_dict(orient="records")}


def load_local_csv(csv_path: str, force: bool = False) -> Dict[str, Any]:
    """
    Load a local CSV file into the SQLite database as the 'passengers' table.
    - csv_path: path to the Titanic CSV on disk (relative or absolute)
    - force: if True, replace any existing 'passengers' table
    """
    if not os.path.exists(csv_path):
        return {"error": f"file not found: {csv_path}"}
    with get_conn() as conn:
        cur = conn.cursor()
        if force:
            cur.execute("DROP TABLE IF EXISTS passengers")
            conn.commit()
        # If already exists and not forcing, skip reload
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='passengers'")
        if cur.fetchone() and not force:
            return {"status": "exists", "db_path": DB_PATH}
        df = pd.read_csv(csv_path)
        df.columns = [c.strip() for c in df.columns]
        df.to_sql("passengers", conn, index=False, if_exists="replace")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_passengers_survived ON passengers(Survived)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_passengers_pclass ON passengers(Pclass)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_passengers_sex ON passengers(Sex)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_passengers_embarked ON passengers(Embarked)")
        conn.commit()
        return {"status": "loaded", "rows": int(len(df)), "db_path": DB_PATH}
