"""
MCP Tool: Azure SQL DB — Query customer persona data.

Provides structured persona lookup by customer ID (customerid).
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
    conn = pyodbc.connect(conn_str)
    # DATETIMEOFFSET (type -155) → str converter
    conn.add_output_converter(-155, lambda val: str(val))
    return conn


def get_customer_persona(customer_id: str) -> str:
    """
    Retrieve the full persona record for a customer from Azure SQL DB.

    Args:
        customer_id: The customer's customerid identifier.

    Returns:
        A JSON string containing all non-empty persona fields,
        or an error message if the customer is not found.
    """
    logger.info(f"[sql] Querying persona for customer_id={customer_id}")
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM [{SQL_TABLE}] WHERE customerid = ?",
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
            f"SELECT TOP (?) customerid, 性別, 年齡, 縣市, [OB等級], "
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


def update_customer_persona(customer_id: str, persona_text: str, source: str) -> str:
    """
    Update a customer's persona text and tracking columns.

    Args:
        customer_id: The customer's customerid identifier.
        persona_text: The new persona text to write.
        source: Description of the update source (e.g. 'transcript_ingest:<call_id>').

    Returns:
        A JSON object with status, or an error if the customer is not found.
    """
    logger.info(f"[sql] Updating persona for customer_id={customer_id} source={source}")
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            f"UPDATE [{SQL_TABLE}] "
            "SET persona = ?, persona_updated_at = SYSDATETIMEOFFSET(), persona_update_source = ? "
            "WHERE customerid = ?",
            persona_text,
            source,
            customer_id,
        )
        conn.commit()
        updated = cur.rowcount > 0
        conn.close()

        if not updated:
            return json.dumps({"error": f"Customer {customer_id} not found"}, ensure_ascii=False)
        return json.dumps({"status": "ok", "customer_id": customer_id, "source": source}, ensure_ascii=False)

    except Exception as exc:
        logger.exception("[sql] Update persona failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def get_persona_update_info(customer_id: str) -> str:
    """
    Retrieve persona and tags update tracking info for a customer.

    Args:
        customer_id: The customer's customerid identifier.

    Returns:
        A JSON object containing persona_updated_at, persona_update_source,
        tags_updated_at, tags_update_source, or an error.
    """
    logger.info(f"[sql] Querying persona update info for customer_id={customer_id}")
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            f"SELECT persona_updated_at, persona_update_source, "
            f"tags_updated_at, tags_update_source "
            f"FROM [{SQL_TABLE}] WHERE customerid = ?",
            customer_id,
        )
        cols = [desc[0] for desc in cur.description]
        row = cur.fetchone()
        conn.close()

        if not row:
            return json.dumps({"error": f"Customer {customer_id} not found"}, ensure_ascii=False)

        record = {}
        for col, val in zip(cols, row):
            if val is not None:
                record[col] = val
            else:
                record[col] = None
        return json.dumps(record, ensure_ascii=False, default=str)

    except Exception as exc:
        logger.exception("[sql] Query update info failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def update_tags_tracking(customer_id: str, source: str) -> str:
    """
    Update the tags tracking columns (tags_updated_at, tags_update_source)
    for a customer. Called by external tag-processing programs.

    Args:
        customer_id: The customer's customerid identifier.
        source: Description of the update source (e.g. 'tag_program_v2').

    Returns:
        A JSON object with status and updated timestamp.
    """
    logger.info(f"[sql] Updating tags tracking for customer_id={customer_id} source={source}")
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            f"UPDATE [{SQL_TABLE}] "
            "SET tags_updated_at = SYSDATETIMEOFFSET(), tags_update_source = ? "
            "WHERE customerid = ?",
            source,
            customer_id,
        )
        conn.commit()
        updated = cur.rowcount > 0
        conn.close()

        if not updated:
            return json.dumps({"error": f"Customer {customer_id} not found"}, ensure_ascii=False)
        return json.dumps({"status": "ok", "customer_id": customer_id, "source": source}, ensure_ascii=False)

    except Exception as exc:
        logger.exception("[sql] Update tags tracking failed")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
