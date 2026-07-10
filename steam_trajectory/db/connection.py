"""
Shared connection helper. Every part of the ingestion pipeline
should get its database connection from here, so foreign key
enforcement is guaranteed to be on every time — instead of every
script remembering to run the PRAGMA itself.
"""
import sqlite3
from pathlib import Path


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """
    Open a connection to the project's SQLite database with
    foreign key constraints enforced (SQLite has this off by
    default — see schema.sql notes).
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
