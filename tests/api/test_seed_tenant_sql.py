import importlib.util
import sqlite3
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "seed_tenant", Path(__file__).resolve().parents[2] / "scripts/seed_tenant.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_seed_name_with_apostrophe_remains_one_sql_value():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE tenants (name TEXT)")
    name = "O'Brien'); DROP TABLE tenants; --"

    connection.executescript(f"INSERT INTO tenants VALUES ({MODULE._sql_literal(name)});")

    assert connection.execute("SELECT name FROM tenants").fetchone() == (name,)
    assert connection.execute("SELECT count(*) FROM tenants").fetchone() == (1,)


@pytest.mark.parametrize("name", ["", "bad\nname", "x" * 201])
def test_seed_rejects_invalid_tenant_name(name):
    with pytest.raises(ValueError):
        MODULE._sql_literal(name)
