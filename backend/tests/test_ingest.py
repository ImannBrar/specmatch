import sqlite3

from app.services.ingest import run_ingest


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_reingest_does_not_duplicate_records():
    """Issue #1: re-running ingest (e.g. on app restart) must not grow the
    record set."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        run_ingest(conn)
        records_first = _count(conn, "records")
        catalog_first = _count(conn, "catalog")

        run_ingest(conn)

        assert _count(conn, "records") == records_first
        assert _count(conn, "catalog") == catalog_first
    finally:
        conn.close()
