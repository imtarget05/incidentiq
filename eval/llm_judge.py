#!/usr/bin/env python3
"""LLM-Judge Evaluation cho IncidentIQ (Option B).

Dùng LLM làm judge để chấm đáp án RAG về incident triage.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Dict, List


@dataclass
class JudgeScore:
    score: float
    explanation: str
    metric: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JudgeResult:
    question_id: str
    question: str
    answer: str
    scores: List[JudgeScore]
    overall: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "answer": self.answer,
            "scores": [s.to_dict() for s in self.scores],
            "overall": self.overall,
        }


def _call_llm(prompt: str, base_url: str, model: str = "llama-3") -> str:
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


def judge_answer(question: str, answer: str, context: str, base_url: str) -> JudgeResult:
    prompt = (
        "Bạn là LLM-Judge. Chấm đáp án RAG về incident triage thang 0-1 theo: "
        "faithfulness, relevance, completeness. Trả về JSON:\n"
        '{"faithfulness": {"score": 0.0, "explanation": ""}, ...}\n'
        f"Câu hỏi: {question}\nNgữ cảnh: {context}\nĐáp án: {answer}"
    )
    raw = _call_llm(prompt, base_url)
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {"faithfulness": {"score": 0.5, "explanation": "parse failed"}}
    scores = [JudgeScore(m, v.get("score", 0.0), v.get("explanation", "")) for m, v in parsed.items()]
    overall = sum(s.score for s in scores) / len(scores) if scores else 0.0
    return JudgeResult(question_id="", question=question, answer=answer, scores=scores, overall=overall)
