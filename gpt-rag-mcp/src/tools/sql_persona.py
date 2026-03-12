"""
MCP Tool: Azure SQL DB — Query customer persona data.

Provides structured persona lookup by customer ID (unikey3).
Uses parameterised queries to prevent SQL injection.
"""

import json
import logging
import os

import pyodbc

logger = logging.getLogger(__name__)

# ── Connection config (env vars with defaults for dev) ─────────────
SQL_SERVER = os.getenv("SQL_SERVER", "ehs-sales-sqlserver.database.windows.net")
SQL_DATABASE = os.getenv("SQL_DATABASE", "salesagent")
SQL_USERNAME = os.getenv("SQL_USERNAME", "sqladmin")
SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")
SQL_TABLE = os.getenv("SQL_TABLE", "customer_persona_raw")
SQL_DRIVER = os.getenv("SQL_DRIVER", "{SQL Server}")


def _get_connection() -> pyodbc.Connection:
    conn_str = (
        f"DRIVER={SQL_DRIVER};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        f"UID={SQL_USERNAME};"
        f"PWD={SQL_PASSWORD};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str)


def get_customer_persona(customer_id: str) -> str:
    """
    Retrieve the full persona record for a customer from Azure SQL DB.

    Args:
        customer_id: The customer's unikey3 identifier.

    Returns:
        A JSON string containing all non-empty persona fields,
        or an error message if the customer is not found.
    """
    logger.info(f"[sql] Querying persona for customer_id={customer_id}")
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM [{SQL_TABLE}] WHERE unikey3 = ?",
            customer_id,
        )
        cols = [desc[0] for desc in cur.description]
        row = cur.fetchone()
        conn.close()

        if not row:
            return json.dumps({"error": f"Customer {customer_id} not found"}, ensure_ascii=False)

        record = {}
        for col, val in zip(cols, row):
            if col == "row_id":
                continue
            if val is not None and str(val).strip():
                record[col] = val if not isinstance(val, float) else round(val, 2)
        return json.dumps(record, ensure_ascii=False, default=str)

    except Exception as exc:
        logger.exception("[sql] Query failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def search_customers(field: str, value: str, limit: int = 10) -> str:
    """
    Search customers by a specific persona field (e.g. city, OB level).

    Only the following fields are allowed for search:
    性別, 縣市, OB等級, 星座

    Args:
        field: The column name to filter on.
        value: The value to match.
        limit: Maximum number of results (default 10, max 50).

    Returns:
        A JSON array of matching customer summaries.
    """
    allowed_fields = {"性別", "縣市", "OB等級", "星座"}
    if field not in allowed_fields:
        return json.dumps(
            {"error": f"Field '{field}' not allowed. Use one of: {sorted(allowed_fields)}"},
            ensure_ascii=False,
        )
    limit = min(max(1, limit), 50)

    logger.info(f"[sql] Searching {field}={value} limit={limit}")
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            f"SELECT TOP (?) unikey3, 性別, 年齡, 縣市, [OB等級], "
            f"全通路歷史累積消費金額, 全通路近一年累積消費金額 "
            f"FROM [{SQL_TABLE}] WHERE [{field}] = ?",
            limit,
            value,
        )
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        conn.close()

        results = []
        for row in rows:
            results.append({c: (round(v, 2) if isinstance(v, float) else v) for c, v in zip(cols, row)})
        return json.dumps(results, ensure_ascii=False, default=str)

    except Exception as exc:
        logger.exception("[sql] Search failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
