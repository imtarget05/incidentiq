"""Minimal SQLite-backed D1 adapter for constraint and API regression tests."""
import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

class SqliteD1:
    def __init__(self, barrier=False):
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        for migration in sorted((Path(__file__).parents[2] / "migrations").glob("*.sql")):
            self.connection.executescript(migration.read_text())
        self.connection.execute("INSERT INTO tenants VALUES ('t1','Tenant',0,1)")
        self.connection.execute("INSERT INTO tenants VALUES ('t2','Tenant 2',0,1)")
        self.barrier = barrier
        self.arrived = 0
        self.release = asyncio.Event()

    def prepare(self, sql):
        db = self

        class Statement:
            args: tuple = ()

            def bind(self, *args):
                self.args = args
                return self

            async def first(self):
                row = db.connection.execute(sql, self.args).fetchone()
                if db.barrier and "idempotency_key = ?" in sql and db.arrived < 2:
                    db.arrived += 1
                    if db.arrived == 2:
                        db.release.set()
                    await db.release.wait()
                return dict(row) if row else None

            async def all(self):
                rows = db.connection.execute(sql, self.args).fetchall()
                return [dict(r) for r in rows]

            async def run(self):
                db.connection.execute(sql, self.args)
                db.connection.commit()
                return SimpleNamespace()

        return Statement()

