"""Database helpers. SQLite for the scaffold; the schema is plain SQL so it ports to Postgres."""
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent


def connect(path: str = "hockeysim.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript((HERE / "schema.sql").read_text())
    conn.commit()
