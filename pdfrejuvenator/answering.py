from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from pdfrejuvenator.vector_index import VectorSearchResult


ANSWER_SCHEMA_VERSION = "pdfrejuvenator.answer_query.v0.7"
DEFAULT_OLLAMA_CHAT_MODEL = "llama3.1"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 120.0
CONFIDENCE_VALUES = {"low", "medium", "high"}
GROUNDING_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}
ANSWER_META_TOKENS = {
    "enabled",
    "evidence",
    "generation",
    "insufficient",
    "provider",
    "records",
    "retrieved",
}


@dataclass(frozen=True)
class AnswerCitation:
    claim: str
    source_id: str
    chunk_id: str
    score: float
    page: int | None = None
    record_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "claim": self.claim,
            "source_id": self.source_id,
            "chunk_id": self.chunk_id,
            "score": self.score,
            "record_type": self.record_type,
        }
        if self.page is not None:
            payload["page"] = self.page
        return payload


def evidence_records_to_jsonl(records: list[VectorSearchResult], *, hide_text: bool = False) -> str:
    return "\n".join(json.dumps(record.to_dict(hide_text=hide_text), sort_keys=True) for record in records)


def build_no_generate_answer(question: str, records: list[VectorSearchResult], *, hide_evidence_text: bool = False) -> dict[str, Any]:
    citations = [
        AnswerCitation(
            claim=(
                "retrieved evidence record"
                if hide_evidence_text
                else (record.text[:180] if record.text else "retrieved evidence record")
            ),
            source_id=record.source_id,
            chunk_id=record.chunk_id,
            score=round(float(record.score), 6),
            page=record.page,
            record_type=record.record_type,
        ).to_dict()
        for record in records
    ]
    return {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "question": question,
        "answer": (
            f"Retrieved {len(records)} evidence records. Generation provider not enabled."
            if records
            else "Insufficient evidence. Generation provider not enabled."
        ),
        "confidence": "low",
        "citations": citations,
        "unsupported_claims": [],
        "evidence_count": len(records),
        "insufficient_evidence": len(records) == 0,
        "evidence_redacted": hide_evidence_text,
    }


def build_answer_prompt(question: str, records: list[VectorSearchResult]) -> str:
    evidence_lines = []
    for index, record in enumerate(records, start=1):
        evidence_lines.append(
            json.dumps(
                {
                    "index": index,
                    "source_id": record.source_id,
                    "chunk_id": record.chunk_id,
                    "record_type": record.record_type,
                    "page": record.page,
                    "score": round(float(record.score), 6),
                    "text": record.text,
                },
                sort_keys=True,
            )
        )
    evidence_block = "\n".join(evidence_lines)
    return (
        "Answer the user question only from the evidence records below. "
        "Return one JSON object with schema_version, question, answer, confidence, citations, "
        "unsupported_claims, evidence_count, and insufficient_evidence. "
        "Every factual claim in answer must have a citation using an evidence chunk_id. "
        "If the evidence does not support an answer, set insufficient_evidence true.\n\n"
        f"Question: {question}\n\nEvidence JSONL:\n{evidence_block}"
    )


def request_ollama_answer(
    question: str,
    records: list[VectorSearchResult],
    *,
    model: str = DEFAULT_OLLAMA_CHAT_MODEL,
    base_url: str = DEFAULT_OLLAMA_URL,
    timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if not model.strip():
        raise ValueError("answer model must not be empty")
    if timeout_seconds <= 0:
        raise ValueError("answer timeout_seconds must be greater than zero")
    payload = json.dumps(
        {
            "model": model.strip(),
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": "You produce citation-grounded JSON only. Do not use knowledge outside the supplied evidence.",
                },
                {"role": "user", "content": build_answer_prompt(question, records)},
            ],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise ValueError(f"ollama answer request failed for model {model}: {exc}") from exc
    message = body.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ValueError("ollama answer response did not include message.content")
    return parse_answer_json(message["content"])


def parse_answer_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("answer payload must be a JSON object")
    return payload


def _meaningful_tokens(value: str) -> set[str]:
    normalized = "".join(character.lower() if character.isalnum() else " " for character in value)
    return {token for token in normalized.split() if len(token) >= 4 and token not in GROUNDING_STOP_WORDS}


def _evidence_by_chunk_id(evidence_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(record.get("chunk_id", "")): record for record in evidence_records if record.get("chunk_id")}


def validate_answer_payload(payload: dict[str, Any], evidence_records: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    if payload.get("schema_version") != ANSWER_SCHEMA_VERSION:
        issues.append("unsupported answer schema_version")
    if not isinstance(payload.get("question"), str) or not payload.get("question", "").strip():
        issues.append("question must be a non-empty string")
    if not isinstance(payload.get("answer"), str) or not payload.get("answer", "").strip():
        issues.append("answer must be a non-empty string")
    if payload.get("confidence") not in CONFIDENCE_VALUES:
        issues.append("confidence must be low, medium, or high")
    citations = payload.get("citations")
    if not isinstance(citations, list):
        issues.append("citations must be a list")
        citations = []
    unsupported_claims = payload.get("unsupported_claims")
    if not isinstance(unsupported_claims, list):
        issues.append("unsupported_claims must be a list")
    evidence_count = payload.get("evidence_count")
    if not isinstance(evidence_count, int) or evidence_count < 0:
        issues.append("evidence_count must be a non-negative integer")
    elif evidence_count != len(evidence_records):
        issues.append("evidence_count must match retrieved evidence record count")
    if not isinstance(payload.get("insufficient_evidence"), bool):
        issues.append("insufficient_evidence must be a boolean")

    evidence_by_chunk_id = _evidence_by_chunk_id(evidence_records)
    evidence_chunk_ids = set(evidence_by_chunk_id)
    if citations and not evidence_chunk_ids:
        issues.append("citations require retrieved evidence records")
    for index, citation in enumerate(citations):
        if not isinstance(citation, dict):
            issues.append(f"citations[{index}] must be an object")
            continue
        for field in ("claim", "source_id", "chunk_id"):
            if not isinstance(citation.get(field), str) or not citation.get(field, "").strip():
                issues.append(f"citations[{index}].{field} must be a non-empty string")
        if citation.get("chunk_id") not in evidence_chunk_ids:
            issues.append(f"citations[{index}].chunk_id does not reference retrieved evidence")
        if not isinstance(citation.get("score"), int | float):
            issues.append(f"citations[{index}].score must be numeric")
        evidence = evidence_by_chunk_id.get(str(citation.get("chunk_id", "")))
        evidence_text = str(evidence.get("text", "")) if isinstance(evidence, dict) else ""
        claim_tokens = _meaningful_tokens(str(citation.get("claim", "")))
        evidence_tokens = _meaningful_tokens(evidence_text)
        if claim_tokens and evidence_text and claim_tokens.isdisjoint(evidence_tokens):
            issues.append(f"citations[{index}].claim does not share grounded terms with cited evidence text")
    if payload.get("insufficient_evidence") is False and evidence_records and not citations:
        issues.append("sufficient-evidence answers require at least one citation")
    if payload.get("insufficient_evidence") is False and not evidence_records:
        issues.append("answer cannot claim sufficient evidence when retrieval is empty")
    if payload.get("insufficient_evidence") is False and evidence_records:
        answer_tokens = _meaningful_tokens(str(payload.get("answer", "")))
        evidence_tokens: set[str] = set()
        for record in evidence_records:
            evidence_tokens.update(_meaningful_tokens(str(record.get("text", ""))))
        unsupported_answer_tokens = sorted(answer_tokens - evidence_tokens - ANSWER_META_TOKENS)
        if len(unsupported_answer_tokens) >= 2:
            issues.append(f"answer contains unsupported terms not found in retrieved evidence: {', '.join(unsupported_answer_tokens[:5])}")
    return issues


def ensure_valid_answer(payload: dict[str, Any], evidence_records: list[dict[str, Any]]) -> dict[str, Any]:
    issues = validate_answer_payload(payload, evidence_records)
    if issues:
        raise ValueError("; ".join(issues))
    return payload
