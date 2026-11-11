"""Contract + PostgreSQL integration checks, using synthetic records only."""
from datetime import datetime, timedelta, timezone
import os
import pytest
from pipeline import Event, Warehouse, window_start

NOW = datetime(2026, 11, 10, 0, tzinfo=timezone.utc)

def event(key="a", tenant="tenant-a", changed=NOW):
    return Event(key, tenant, "etl", NOW, changed, "document-1", status="processed")

def test_overlap_and_invalid_events():
    assert window_start(NOW) == NOW - timedelta(hours=48)
    with pytest.raises(ValueError):
        Event("a", "", "etl", NOW, NOW, "doc")
    with pytest.raises(ValueError):
        Event("a", "tenant", "etl", NOW.replace(tzinfo=None), NOW, "doc")

@pytest.fixture
def warehouse():
    dsn = os.environ.get("ANALYTICS_TEST_DSN")
    if not dsn:
        pytest.skip("Set ANALYTICS_TEST_DSN for a disposable PostgreSQL database")
    wh = Warehouse(dsn)
    wh.initialize()
    with wh.connect() as conn:
        conn.execute("TRUNCATE raw.events, raw.checkpoints")
    return wh

def test_replay_backfill_and_failure_do_not_advance_checkpoint(warehouse):
    warehouse.load("test-source", [event()], NOW)
    warehouse.load("test-source", [event()], NOW)
    with warehouse.connect() as conn:
        assert conn.execute("SELECT count(*) FROM raw.events").fetchone()[0] == 1
    with pytest.raises(RuntimeError):
        warehouse.load("test-source", [event("b", changed=NOW+timedelta(hours=1))], NOW+timedelta(hours=1), fail_before_commit=True)
    assert warehouse.checkpoint("test-source") == NOW
    with warehouse.connect() as conn:
        assert conn.execute("SELECT count(*) FROM raw.events").fetchone()[0] == 1
    warehouse.load("test-source", [event("b", changed=NOW-timedelta(hours=3))], NOW, backfill=True)
    assert warehouse.checkpoint("test-source") == NOW
    with warehouse.connect() as conn:
        assert conn.execute("SELECT count(*) FROM raw.events").fetchone()[0] == 2

def test_tenant_read_role_isolated_and_cannot_change_identity(warehouse):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    warehouse.load("rls", [event(), event("b", "tenant-b")], NOW)
    warehouse.secure_reads()
    warehouse.provision_reader("analytics_tenant_a", "tenant-a")
    warehouse.provision_reader("analytics_tenant_b", "tenant-b")
    with warehouse.connect() as conn:
        conn.execute("ALTER ROLE analytics_tenant_a LOGIN PASSWORD 'local-test-only'")
    config=conninfo_to_dict(warehouse.dsn)
    config.update(user="analytics_tenant_a",password="local-test-only")
    with psycopg.connect(**config) as conn:
        assert conn.execute("SELECT tenant_id FROM raw.events").fetchall()==[("tenant-a",)]
        conn.execute("SELECT set_config('app.tenant_id','tenant-b',true)")
        assert conn.execute("SELECT tenant_id FROM raw.events").fetchall()==[("tenant-a",)]
        conn.commit()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SET ROLE analytics_tenant_b")
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE raw.tenant_readers SET tenant_id='tenant-b'")
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO raw.checkpoints VALUES ('evil',now())")
