"""Read-only bounded source adapters. Credentials are supplied only via env."""
from datetime import datetime, timezone
import time
from zoneinfo import ZoneInfo
import httpx
import psycopg
from psycopg.rows import dict_row
from pipeline import Event


def enterprise_documents(dsn, start, until, source_timezone):
    ZoneInfo(source_timezone)  # Reject unknown deployment timezone, don't guess.
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        with conn.cursor(name="analytics_document_export") as cursor:
            cursor.execute("""
                SELECT id, owner_username, version_number, workflow_status,
                 created_at AT TIME ZONE %s AS occurred,
                 coalesce(updated_at,created_at) AT TIME ZONE %s AS changed
                FROM documents
                WHERE coalesce(updated_at,created_at) AT TIME ZONE %s >= %s
                  AND coalesce(updated_at,created_at) AT TIME ZONE %s <= %s
                ORDER BY coalesce(updated_at,created_at),id
            """, (source_timezone,source_timezone,source_timezone,start,source_timezone,until))
            cursor.itersize = 500
            for row in cursor:
                # Enterprise is owner-scoped, not tenant-scoped: keep that exact
                # identity namespace instead of inventing organization membership.
                yield Event(f"document:{row['id']}:v{row['version_number']}",
                            "owner:"+row["owner_username"], "ingestion", row["occurred"],
                            row["changed"], str(row["id"]), status=row["workflow_status"])


D1_QUERY = """
SELECT * FROM (
 SELECT 'incident:'||id AS event_id,tenant_id,'incident' AS event_type,
 created_at AS occurred,updated_at AS changed,id AS entity_id,status,
 service,NULL AS tokens,NULL AS latency_ms,NULL AS citations FROM incidents
 UNION ALL
 SELECT 'triage:'||m.id,m.tenant_id,'triage',m.created_at,m.created_at,m.incident_id,
 m.status,i.service,m.tokens_used,m.latency_ms,m.citations
 FROM triage_metrics m JOIN incidents i ON i.id=m.incident_id AND i.tenant_id=m.tenant_id
 UNION ALL
 SELECT 'etl:'||id||':v'||version,tenant_id,'etl',uploaded_at,
 coalesce(processed_at,uploaded_at),id,status,NULL,NULL,NULL,NULL FROM documents
) WHERE changed >= ? AND changed <= ? AND (changed > ? OR (changed = ? AND event_id > ?))
ORDER BY changed,event_id LIMIT 500
"""


def d1_events(account, database, token, start, until, *, client=None):
    # IDs are path segments, never SQL text; only fixed SELECT and bind params.
    if not all(value and all(c.isalnum() or c in '-_' for c in value) for value in (account,database)):
        raise ValueError("Invalid D1 account/database identifier")
    lower, upper = int(start.timestamp()*1000), int(until.timestamp()*1000)
    changed, last = lower-1, ""
    owned = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30), follow_redirects=False)
    try:
        while True:
            for attempt in range(3):
                try:
                    response=client.post(f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{database}/query",
                                         headers={"Authorization":"Bearer "+token},
                                         json={"sql":D1_QUERY,"params":[lower,upper,changed,changed,last]})
                    if response.status_code == 429 or response.status_code >= 500:
                        raise httpx.TransportError("D1 transient failure")
                    response.raise_for_status()
                    payload=response.json()
                    if not payload.get("success") or not payload.get("result") or not payload["result"][0].get("success", True):
                        raise ValueError("D1 read query failed")
                    rows=payload["result"][0]["results"]
                    break
                except (httpx.TransportError,httpx.TimeoutException):
                    if attempt == 2:
                        raise RuntimeError("D1 read unavailable") from None
                    time.sleep(0.25*(2**attempt))
            for row in rows:
                yield Event(row["event_id"],row["tenant_id"],row["event_type"],
                            datetime.fromtimestamp(row["occurred"]/1000,timezone.utc),
                            datetime.fromtimestamp(row["changed"]/1000,timezone.utc),row["entity_id"],
                            status=row["status"],service=row["service"],tokens=row["tokens"],
                            latency_ms=row["latency_ms"],citations=row["citations"])
                changed,last=row["changed"],row["event_id"]
            if len(rows)<500:
                return
    finally:
        if owned:
            client.close()
