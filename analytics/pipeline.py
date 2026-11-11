"""Incremental warehouse loader. No document/question contents are exported."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable
import math
import psycopg

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def window_start(checkpoint: datetime | None) -> datetime:
    return checkpoint - timedelta(hours=48) if checkpoint else EPOCH


@dataclass(frozen=True)
class Event:
    event_id: str
    tenant_id: str
    event_type: str
    occurred_at: datetime
    updated_at: datetime
    entity_id: str
    status: str | None = None
    model: str | None = None
    service: str | None = None
    tokens: int | None = None
    latency_ms: int | None = None
    cost_usd: Decimal | None = None
    citations: int | None = None

    def __post_init__(self):
        if not all(isinstance(v, str) and v.strip() for v in (self.event_id, self.tenant_id, self.event_type, self.entity_id)):
            raise ValueError("Event identity and tenant must be non-empty strings")
        if self.event_type not in {"ingestion", "retrieval", "llm_request", "incident", "triage", "etl"}:
            raise ValueError("Unknown event type")
        for value in (self.occurred_at, self.updated_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Event timestamps must have explicit timezone")
        for value in (self.tokens, self.latency_ms, self.citations):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise ValueError("Counters must be non-negative integers or absent")
        if self.cost_usd is not None and (not math.isfinite(self.cost_usd) or self.cost_usd < 0):
            raise ValueError("Cost must be finite and non-negative or absent")


class Warehouse:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def connect(self):
        return psycopg.connect(self.dsn, options="-c timezone=UTC")

    def initialize(self):
        with self.connect() as conn:
            conn.execute((Path(__file__).parent / "schema.sql").read_text())

    def checkpoint(self, source: str):
        with self.connect() as conn:
            row = conn.execute("SELECT watermark FROM raw.checkpoints WHERE source=%s", (source,)).fetchone()
            return row[0] if row else None

    def load(self, source: str, events: Iterable[Event], until: datetime,
             *, backfill: bool = False, fail_before_commit: bool = False) -> int:
        if until.tzinfo is None:
            raise ValueError("Watermark must have explicit timezone")
        count = 0
        with self.connect() as conn:
            # Serialize the same source, including concurrent first runs. All raw
            # writes AND its watermark commit atomically; failure rolls both back.
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (source,))
            current = conn.execute("SELECT watermark FROM raw.checkpoints WHERE source=%s", (source,)).fetchone()
            for event in events:
                if event.updated_at > until:
                    raise ValueError("Source returned an event beyond the captured export boundary")
                values = (source, *event.__dict__.values())
                conn.execute("""
                    INSERT INTO raw.events
                    (source,event_id,tenant_id,event_type,occurred_at,updated_at,entity_id,
                     status,model,service,tokens,latency_ms,cost_usd,citations)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(source,event_id) DO UPDATE SET
                      tenant_id=excluded.tenant_id,event_type=excluded.event_type,
                      occurred_at=excluded.occurred_at,updated_at=excluded.updated_at,
                      entity_id=excluded.entity_id,status=excluded.status,
                      model=excluded.model,service=excluded.service,tokens=excluded.tokens,
                      latency_ms=excluded.latency_ms,cost_usd=excluded.cost_usd,
                      citations=excluded.citations,loaded_at=now()
                    WHERE excluded.updated_at >= raw.events.updated_at
                """, values)
                count += 1
            if fail_before_commit:
                raise RuntimeError("Injected pre-commit failure")
            if not backfill:
                watermark = max(until, current[0]) if current else until
                conn.execute("INSERT INTO raw.checkpoints VALUES (%s,%s) ON CONFLICT(source) DO UPDATE SET watermark=excluded.watermark", (source, watermark))
        return count

    def secure_reads(self):
        with self.connect() as conn:
            conn.execute((Path(__file__).parent / "secure_reads.sql").read_text())

    def provision_reader(self, role: str, tenant: str):
        """Provision a NOLOGIN tenant role; DBA grants it only to its matching LOGIN.

        Never grant analytics_reader directly to untrusted clients and never grant
        membership in a different tenant role. Login credentials are DBA-owned.
        """
        from psycopg import sql
        if not role.startswith("analytics_tenant_") or not tenant.strip():
            raise ValueError("Use analytics_tenant_ prefix and nonempty tenant")
        with self.connect() as conn:
            existing=conn.execute("SELECT tenant_id FROM raw.tenant_readers WHERE role_name=%s",(role,)).fetchone()
            if existing and existing[0] != tenant:
                raise ValueError("Role already bound to another tenant")
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s",(role,)).fetchone():
                conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(sql.Identifier(role)))
            conn.execute(sql.SQL("GRANT analytics_reader TO {}").format(sql.Identifier(role)))
            conn.execute("INSERT INTO raw.tenant_readers VALUES (%s,%s) ON CONFLICT(role_name) DO NOTHING",(role,tenant))
