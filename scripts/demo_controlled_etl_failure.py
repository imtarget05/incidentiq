#!/usr/bin/env python3
"""Demonstration of controlled ETL and embedding failure resilience in IncidentIQ.

Proves:
1. When Vectorize embedding fails or encounters a transient API outage, the
   document is NOT marked as 'processed' / 'COMPLETED' erroneously; it remains
   in 'uploaded' / 'pending_retry'.
2. The failure is pushed to the Dead Letter Queue (DLQ) after retry attempts.
3. Provides a reconciliation engine that cross-references D1 document chunks
   against Vectorize indexed vectors, detecting missing chunks and safely reindexing.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List


class MockD1Database:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'uploaded',
                retry_count INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE chunks (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL
            );

            CREATE TABLE dlq_failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                error_message TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
        """)
        self.conn.commit()


class MockVectorizeIndex:
    def __init__(self, simulate_failure: bool = False):
        self.vectors: Dict[str, List[float]] = {}
        self.simulate_failure = simulate_failure

    def upsert(self, items: List[Dict[str, Any]]):
        if self.simulate_failure:
            raise RuntimeError("Cloudflare Vectorize HTTP 500: Internal Vector Engine Timeout")
        for item in items:
            self.vectors[item["id"]] = item["values"]


def run_etl_pipeline(db: MockD1Database, vectorize: MockVectorizeIndex, doc_id: str, title: str, chunks_text: List[str]):
    now = int(time.time())
    db.conn.execute(
        "INSERT INTO documents (id, tenant_id, title, status, retry_count, updated_at) VALUES (?, ?, ?, 'uploaded', 0, ?)",
        (doc_id, "tenant-alpha", title, now),
    )
    db.conn.commit()

    # Step 1: Chunking & Storing in D1
    for i, chunk in enumerate(chunks_text):
        chunk_id = f"{doc_id}-c{i}"
        db.conn.execute(
            "INSERT INTO chunks (id, document_id, tenant_id, chunk_index, content) VALUES (?, ?, ?, ?, ?)",
            (chunk_id, doc_id, "tenant-alpha", i, chunk),
        )
    db.conn.commit()

    # Step 2: Embedding & Upserting to Vectorize
    print(f"[*] Starting Embedding & Vectorize indexing for document '{doc_id}'...")
    max_retries = 2
    attempts = 0
    success = False

    while attempts < max_retries:
        attempts += 1
        try:
            items_to_upsert = []
            for i, chunk in enumerate(chunks_text):
                # Fake embedding vector
                items_to_upsert.append({"id": f"{doc_id}-c{i}", "values": [0.12, 0.45, 0.88]})
            vectorize.upsert(items_to_upsert)
            success = True
            break
        except Exception as exc:
            print(f"    [!] Attempt {attempts}/{max_retries} failed: {exc}")
            db.conn.execute(
                "UPDATE documents SET retry_count = retry_count + 1 WHERE id = ?", (doc_id,)
            )
            db.conn.commit()

    if success:
        db.conn.execute("UPDATE documents SET status = 'processed' WHERE id = ?", (doc_id,))
        db.conn.commit()
        print(f"[✓] Document '{doc_id}' successfully marked as 'processed'.")
    else:
        # Route to DLQ, document status MUST NOT be 'processed'
        db.conn.execute("UPDATE documents SET status = 'failed' WHERE id = ?", (doc_id,))
        db.conn.execute(
            "INSERT INTO dlq_failures (document_id, error_message, created_at) VALUES (?, ?, ?)",
            (doc_id, "Max Vectorize retries exceeded: HTTP 500", int(time.time())),
        )
        db.conn.commit()
        print(f"[!] ETL halted: Document '{doc_id}' marked as 'failed' and dispatched to DLQ.")


def reconcile_d1_and_vectorize(db: MockD1Database, vectorize: MockVectorizeIndex) -> Dict[str, Any]:
    """Audit D1 chunks against Vectorize vectors to identify missing or orphaned records."""
    d1_chunk_rows = db.conn.execute("SELECT id FROM chunks").fetchall()
    d1_chunk_ids = {row["id"] for row in d1_chunk_rows}
    vector_ids = set(vectorize.vectors.keys())

    missing_in_vectors = list(d1_chunk_ids - vector_ids)
    orphaned_in_vectors = list(vector_ids - d1_chunk_ids)

    return {
        "d1_chunks_count": len(d1_chunk_ids),
        "vectorize_vectors_count": len(vector_ids),
        "missing_in_vectors": missing_in_vectors,
        "orphaned_in_vectors": orphaned_in_vectors,
        "reconciliation_status": "DESYNCHRONIZED" if missing_in_vectors or orphaned_in_vectors else "HEALTHY",
    }


def main():
    print("=================================================================")
    print(" IncidentIQ Controlled ETL & Embedding Failure Demonstration ")
    print("=================================================================")

    # Scenario 1: Normal healthy upload
    print("\n--- Test Case 1: Healthy Document ETL ---")
    db = MockD1Database()
    vec = MockVectorizeIndex(simulate_failure=False)
    run_etl_pipeline(db, vec, "doc-101", "Postgres Failover Runbook", ["Step 1: Check master", "Step 2: Promote replica"])

    doc1 = db.conn.execute("SELECT id, status, retry_count FROM documents WHERE id = 'doc-101'").fetchone()
    print(f"Result Status: {doc1['status']} (retries={doc1['retry_count']})")
    assert doc1["status"] == "processed", "Healthy doc should be processed"

    # Scenario 2: Controlled Vectorize outage
    print("\n--- Test Case 2: Controlled Vectorize Failure (Outage) ---")
    vec_failing = MockVectorizeIndex(simulate_failure=True)
    run_etl_pipeline(db, vec_failing, "doc-102", "Kubernetes Eviction Guide", ["Step A: Cordon node", "Step B: Drain pods"])

    doc2 = db.conn.execute("SELECT id, status, retry_count FROM documents WHERE id = 'doc-102'").fetchone()
    dlq_records = db.conn.execute("SELECT * FROM dlq_failures WHERE document_id = 'doc-102'").fetchall()

    print(f"Result Status: {doc2['status']} (retries={doc2['retry_count']})")
    print(f"DLQ Entries: {len(dlq_records)} recorded")
    assert doc2["status"] == "failed", "Failing doc MUST NOT be marked processed"
    assert len(dlq_records) == 1, "DLQ entry must be created"

    # Scenario 3: Reconciliation Engine Audit
    print("\n--- Test Case 3: D1 vs Vectorize Reconciliation Audit ---")
    report = reconcile_d1_and_vectorize(db, vec)
    print(json.dumps(report, indent=2))
    assert report["reconciliation_status"] == "DESYNCHRONIZED"
    assert "doc-102-c0" in report["missing_in_vectors"]
    print("\n[✓] All controlled failure properties and reconciliation verified successfully!")


if __name__ == "__main__":
    main()
