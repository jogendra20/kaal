"""
nse_cache.py

Local SQLite cache for NSE announcement lists, PDF text extraction, and
price lookups - the three calls that are (a) slow, (b) identical across
every backtest rerun since historical data doesn't change, and (c) the
actual source of the connection-reset failures we've been hitting.

Deliberately does NOT cache LLM verdicts - those must stay live every run
so a prompt fix (like today's guidance_upgrade patch) actually takes
effect instead of silently serving stale answers from before the fix.

Usage: wrap the three functions instead of calling fy27_backtest's
versions directly:

    import nse_cache
    anns = nse_cache.get_announcements(session, symbol, from_date, to_date)
    pdf_text = nse_cache.get_pdf_text(pdf_url)
    pre_move = nse_cache.get_pre_move(symbol, result_date)
    fwd = nse_cache.get_forward_returns(symbol, result_date)
"""

import sqlite3
import json
import os
from datetime import datetime

import fy27_backtest as base

DB_PATH = "nse_cache.db"


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            symbol TEXT, from_date TEXT, to_date TEXT,
            fetched_at TEXT, data TEXT,
            PRIMARY KEY (symbol, from_date, to_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pdf_text (
            url TEXT PRIMARY KEY, fetched_at TEXT, text TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pre_move (
            symbol TEXT, result_date TEXT, fetched_at TEXT, value TEXT,
            PRIMARY KEY (symbol, result_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forward_returns (
            symbol TEXT, result_date TEXT, fetched_at TEXT, data TEXT,
            PRIMARY KEY (symbol, result_date)
        )
    """)
    return conn


def get_announcements(session, symbol, from_date, to_date):
    fd, td = from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d")
    conn = _conn()
    row = conn.execute(
        "SELECT data FROM announcements WHERE symbol=? AND from_date=? AND to_date=?",
        (symbol, fd, td)
    ).fetchone()
    if row:
        conn.close()
        return json.loads(row[0])

    result = base.fetch_results_announcements(session, symbol, from_date, to_date)
    conn.execute(
        "INSERT OR REPLACE INTO announcements VALUES (?,?,?,?,?)",
        (symbol, fd, td, datetime.now().isoformat(), json.dumps(result or []))
    )
    conn.commit()
    conn.close()
    return result


def get_pdf_text(pdf_url):
    conn = _conn()
    row = conn.execute("SELECT text FROM pdf_text WHERE url=?", (pdf_url,)).fetchone()
    if row:
        conn.close()
        return row[0]

    text = base.download_pdf_text(pdf_url)
    conn.execute(
        "INSERT OR REPLACE INTO pdf_text VALUES (?,?,?)",
        (pdf_url, datetime.now().isoformat(), text or "")
    )
    conn.commit()
    conn.close()
    return text


def get_pre_move(symbol, result_date):
    rd = result_date.strftime("%Y-%m-%d")
    conn = _conn()
    row = conn.execute(
        "SELECT value FROM pre_move WHERE symbol=? AND result_date=?",
        (symbol, rd)
    ).fetchone()
    if row:
        conn.close()
        return None if row[0] == "null" else json.loads(row[0])

    val = base.pre_result_move_pct(symbol, result_date)
    conn.execute(
        "INSERT OR REPLACE INTO pre_move VALUES (?,?,?,?)",
        (symbol, rd, datetime.now().isoformat(), json.dumps(val) if val is not None else "null")
    )
    conn.commit()
    conn.close()
    return val


def get_forward_returns(symbol, result_date):
    rd = result_date.strftime("%Y-%m-%d")
    conn = _conn()
    row = conn.execute(
        "SELECT data FROM forward_returns WHERE symbol=? AND result_date=?",
        (symbol, rd)
    ).fetchone()
    if row:
        conn.close()
        return None if row[0] == "null" else json.loads(row[0])

    val = base.forward_returns(symbol, result_date)
    conn.execute(
        "INSERT OR REPLACE INTO forward_returns VALUES (?,?,?,?)",
        (symbol, rd, datetime.now().isoformat(), json.dumps(val) if val is not None else "null")
    )
    conn.commit()
    conn.close()
    return val


def stats():
    conn = _conn()
    for table in ("announcements", "pdf_text", "pre_move", "forward_returns"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {n} cached rows")
    conn.close()


if __name__ == "__main__":
    stats()
