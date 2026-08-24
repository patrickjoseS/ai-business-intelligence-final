"""
database.py
Thin, read-only-oriented data access layer around the SQLite database.
"""

import os
import sqlite3
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "novashop.db")

# Cached schema description string (schema doesn't change at runtime)
_SCHEMA_CACHE = None
_TABLE_COLUMNS_CACHE = None


def connect_database(read_only: bool = True) -> sqlite3.Connection:
    """
    Open a connection to the NovaShop SQLite database.
    When read_only=True, opens the file in SQLite's URI read-only mode so
    that even a bug in calling code cannot accidentally write to the DB.
    """
    db_path = os.path.abspath(DB_PATH)
    if read_only:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(db_path)
    return conn


def execute_query(query: str, params: tuple = ()) -> pd.DataFrame:
    """
    Execute a (validated, read-only) SQL query and return the result as a
    pandas DataFrame. Raises the underlying sqlite3 error on failure so
    callers can decide how to surface it.
    """
    conn = connect_database(read_only=True)
    try:
        df = pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()
    return df


def get_schema(force_refresh: bool = False) -> str:
    """
    Return a human/LLM-readable description of the database schema:
    tables, columns, types, and foreign keys. This is what gets injected
    into the LLM prompt for text-to-SQL generation.
    """
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None and not force_refresh:
        return _SCHEMA_CACHE

    conn = connect_database(read_only=True)
    try:
        cur = conn.cursor()
        tables = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )]

        lines = []
        for table in tables:
            lines.append(f"TABLE {table}")
            for col in cur.execute(f"PRAGMA table_info({table})"):
                # col: (cid, name, type, notnull, dflt_value, pk)
                _, name, ctype, notnull, _, pk = col
                flag = " PRIMARY KEY" if pk else ""
                lines.append(f"  - {name} {ctype}{flag}")
            fks = cur.execute(f"PRAGMA foreign_key_list({table})").fetchall()
            for fk in fks:
                # fk: (id, seq, table, from, to, ...)
                lines.append(f"  FOREIGN KEY {fk[3]} -> {fk[2]}({fk[4]})")
            lines.append("")
    finally:
        conn.close()

    _SCHEMA_CACHE = "\n".join(lines)
    return _SCHEMA_CACHE


def get_table_columns(force_refresh: bool = False) -> dict:
    """
    Return {table_name: {column_name, ...}} for every real table in the
    database. Used by ai.validate_sql() as an allowlist so AI-generated
    SQL cannot reference a hallucinated table, independent of the
    keyword-blocklist safety check. Column validity is still enforced by SQLite.
    """
    global _TABLE_COLUMNS_CACHE
    if _TABLE_COLUMNS_CACHE is not None and not force_refresh:
        return _TABLE_COLUMNS_CACHE

    conn = connect_database(read_only=True)
    try:
        cur = conn.cursor()
        tables = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )]
        result = {}
        for table in tables:
            cols = {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}
            result[table.lower()] = cols
    finally:
        conn.close()

    _TABLE_COLUMNS_CACHE = result
    return result


def get_kpis() -> dict:
    """High-level KPIs for the dashboard header."""
    q_revenue = """
        SELECT COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS revenue
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.order_id
        WHERE o.order_status = 'Completed'
    """
    q_profit = """
        SELECT COALESCE(SUM(oi.quantity * (oi.unit_price - p.purchase_price)), 0) AS profit
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.order_id
        JOIN products p ON oi.product_id = p.product_id
        WHERE o.order_status = 'Completed'
    """
    q_orders = "SELECT COUNT(*) AS n FROM orders WHERE order_status = 'Completed'"
    q_customers = "SELECT COUNT(*) AS n FROM customers"

    revenue = execute_query(q_revenue).iloc[0]["revenue"]
    profit = execute_query(q_profit).iloc[0]["profit"]
    orders = execute_query(q_orders).iloc[0]["n"]
    customers = execute_query(q_customers).iloc[0]["n"]

    return {
        "revenue": float(revenue),
        "profit": float(profit),
        "orders": int(orders),
        "customers": int(customers),
    }
