"""security-platform — Cybersecurity Dashboard backend on PostgreSQL.

Database module: connection pool, schema migration runner, and query helpers.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from psycopg2 import pool
from psycopg2.extras import RealDictCursor

_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://security:security@localhost:5432/security_dashboard",
)

_pool: Optional[pool.ThreadedConnectionPool] = None


def get_pool() -> pool.ThreadedConnectionPool:
    """Return a lazily-created thread-safe connection pool."""
    global _pool
    if _pool is None:
        _pool = pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=_DSN)
    return _pool


def get_conn():
    """Borrow a connection from the pool (caller must return via put_conn)."""
    return get_pool().getconn()


def put_conn(conn) -> None:
    """Return a connection to the pool."""
    try:
        get_pool().putconn(conn)
    except Exception:
        pass


def run_migration(sql_path: str) -> None:
    """Execute a migration SQL file against the database."""
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                with open(sql_path, "r", encoding="utf-8") as f:
                    cur.execute(f.read())
    finally:
        put_conn(conn)


def fetch_all(
    sql: str, params: Optional[tuple] = None, commit: bool = False
) -> List[Dict[str, Any]]:
    """Execute a query and return rows as dicts.

    Set commit=True for write queries (e.g. INSERT ... RETURNING) so the
    transaction is persisted before the connection returns to the pool.
    """
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or ())
            rows = [dict(r) for r in cur.fetchall()]
        if commit:
            conn.commit()
        return rows
    finally:
        put_conn(conn)


def fetch_one(
    sql: str, params: Optional[tuple] = None, commit: bool = False
) -> Optional[Dict[str, Any]]:
    """Execute a query and return a single row as a dict.

    Set commit=True for write queries (e.g. INSERT ... RETURNING) so the
    transaction is persisted before the connection returns to the pool.
    """
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
        if commit:
            conn.commit()
        return dict(row) if row else None
    finally:
        put_conn(conn)


def execute(sql: str, params: Optional[tuple] = None) -> int:
    """Execute INSERT/UPDATE/DELETE and return rowcount."""
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                return cur.rowcount
    finally:
        put_conn(conn)
