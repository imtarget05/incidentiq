#!/usr/bin/env python3
"""Live retrieval & LLM benchmark cho IncidentIQ (Option B).

Tính Hit@K và MRR cho retrieval trên golden dataset incident.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List


def retrieval_metrics(retrieved_chunks: List[Dict[str, Any]], expected_keywords: List[str], top_k: int = 5) -> Dict[str, Any]:
    top_chunks = retrieved_chunks[:top_k]
    sources = " ".join(str(c.get("content", "")) for c in top_chunks).lower()
    hits = [k for k in expected_keywords if k.lower() in sources]
    hit = len(hits) > 0 if sources else False
    recall = len(hits) / len(expected_keywords) if expected_keywords else 0.0
    matched_rank = None
    for i, c in enumerate(top_chunks, start=1):
        content = str(c.get("content", "")).lower()
        if any(k.lower() in content for k in expected_keywords):
            matched_rank = i
            break
    mrr = (1.0 / matched_rank) if matched_rank else 0.0
    return {"hit": hit, "recall": recall, "mrr": mrr, "source_hits": hits}


def run(base_url: str, questions_path: str, output: str, top_k: int = 5) -> dict:
    questions = json.loads(Path(questions_path).read_text(encoding="utf-8"))
    scored = []
    for q in questions:
        qid = q.get("id", "unknown")
        question = q.get("question", "")
        expected_keywords = q.get("expected_source_keywords", [])
        retrieved_chunks: List[Dict[str, Any]] = []
        try:
            payload = {"question": question, "top_k": top_k}
            req = urllib.request.Request(
                f"{base_url}/api/v1/retrieve",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            retrieved_chunks = data.get("chunks", [])
        except Exception:
            retrieved_chunks = []
        rm = retrieval_metrics(retrieved_chunks, expected_keywords, top_k=top_k)
        scored.append({"question_id": qid, "question": question, **rm})
        time.sleep(0.1)

    summary = {
        "total": len(scored),
        "hit_rate_at_k": sum(s["hit"] for s in scored) / len(scored) if scored else 0.0,
        "mean_recall_at_k": sum(s["recall"] for s in scored) / len(scored) if scored else 0.0,
        "mean_reciprocal_rank": sum(s["mrr"] for s in scored) / len(scored) if scored else 0.0,
        "top_k": top_k,
    }
    result = {"summary": summary, "results": scored}
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--questions", default="eval/golden_dataset.json")
    parser.add_argument("--output", default="eval/results/live_benchmark.json")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    run(args.base_url, args.questions, args.output, args.top_k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
