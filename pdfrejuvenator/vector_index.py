from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


VECTOR_INDEX_SCHEMA_VERSION = "pdfrejuvenator.vector_index.v0.5"
VECTOR_CHUNK_SCHEMA_VERSION = "pdfrejuvenator.vector_chunk.v0.5"
DEFAULT_VECTOR_DIMENSIONS = 32
DEFAULT_CHUNK_MAX_CHARS = 1400


@dataclass(frozen=True)
class EmbeddingModelInfo:
    provider: str
    model: str
    dimensions: int
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
            "fingerprint": self.fingerprint,
        }


class EmbeddingProvider(Protocol):
    @property
    def info(self) -> EmbeddingModelInfo:
        ...

    def embed(self, text: str) -> list[float]:
        ...


class DeterministicHashEmbeddingProvider:
    """Public-safe deterministic embeddings for validation and offline smoke tests."""

    def __init__(self, *, dimensions: int = DEFAULT_VECTOR_DIMENSIONS) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be greater than zero")
        self._info = EmbeddingModelInfo(
            provider="deterministic_hash",
            model="blake2b-token-buckets",
            dimensions=dimensions,
            fingerprint=f"deterministic_hash:{dimensions}:v1",
        )

    @property
    def info(self) -> EmbeddingModelInfo:
        return self._info

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.info.dimensions
        tokens = [token for token in text.lower().replace("\n", " ").split(" ") if token]
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], byteorder="big") % self.info.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_search_index(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"search index line {line_number} must be a JSON object")
        records.append(payload)
    return records


def chunk_text(text: str, *, max_chars: int = DEFAULT_CHUNK_MAX_CHARS) -> list[str]:
    clean = " ".join(text.split())
    if not clean:
        return []
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")
    chunks: list[str] = []
    current = ""
    for token in clean.split(" "):
        next_value = token if not current else f"{current} {token}"
        if len(next_value) <= max_chars:
            current = next_value
            continue
        if current:
            chunks.append(current)
        current = token
    if current:
        chunks.append(current)
    return chunks


def search_record_to_vector_chunks(
    record: dict[str, Any],
    *,
    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
) -> list[dict[str, Any]]:
    record_id = str(record.get("record_id", ""))
    chunks = chunk_text(str(record.get("text", "")), max_chars=max_chars)
    vector_chunks: list[dict[str, Any]] = []
    for index, text in enumerate(chunks):
        vector_chunks.append(
            {
                "schema_version": VECTOR_CHUNK_SCHEMA_VERSION,
                "chunk_id": "::".join(part for part in [record_id, f"chunk{index:04d}"] if part),
                "chunk_index": index,
                "source_record_id": record_id,
                "source_schema_version": record.get("schema_version", ""),
                "record_type": record.get("record_type", ""),
                "text": text,
                "page": record.get("page", 0),
                "artifact_path": record.get("artifact_path", ""),
                "metadata": dict(record.get("metadata", {})) if isinstance(record.get("metadata"), dict) else {},
            }
        )
    return vector_chunks


def build_vector_index_payload(
    search_index_path: Path,
    *,
    provider: EmbeddingProvider | None = None,
    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
) -> dict[str, Any]:
    source_records = load_search_index(search_index_path)
    embedding_provider = provider or DeterministicHashEmbeddingProvider()
    chunks: list[dict[str, Any]] = []
    for record in source_records:
        chunks.extend(search_record_to_vector_chunks(record, max_chars=max_chars))
    embedded_chunks = [
        {
            **chunk,
            "embedding": embedding_provider.embed(str(chunk.get("text", ""))),
        }
        for chunk in chunks
    ]
    return {
        "schema_version": VECTOR_INDEX_SCHEMA_VERSION,
        "source_index": {
            "path": str(search_index_path),
            "sha256": file_sha256(search_index_path),
            "record_count": len(source_records),
        },
        "embedding_provider": embedding_provider.info.to_dict(),
        "chunking": {
            "strategy": "whitespace_max_chars",
            "max_chars": max_chars,
        },
        "chunk_count": len(embedded_chunks),
        "chunks": embedded_chunks,
    }


def write_vector_index(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_vector_index(
    search_index_path: Path,
    output_path: Path,
    *,
    provider: EmbeddingProvider | None = None,
    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
) -> int:
    payload = build_vector_index_payload(search_index_path, provider=provider, max_chars=max_chars)
    write_vector_index(output_path, payload)
    return int(payload["chunk_count"])


def load_vector_index(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("vector index must be a JSON object")
    return payload


def validate_vector_index_payload(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if payload.get("schema_version") != VECTOR_INDEX_SCHEMA_VERSION:
        issues.append("unsupported vector index schema_version")
    provider = payload.get("embedding_provider")
    if not isinstance(provider, dict):
        issues.append("embedding_provider must be an object")
        dimensions = None
    else:
        dimensions = provider.get("dimensions")
        if not isinstance(dimensions, int) or dimensions <= 0:
            issues.append("embedding_provider.dimensions must be a positive integer")
        for field in ("provider", "model", "fingerprint"):
            if not provider.get(field):
                issues.append(f"embedding_provider.{field} is required")
    chunks = payload.get("chunks")
    if not isinstance(chunks, list):
        issues.append("chunks must be a list")
        return issues
    if payload.get("chunk_count") != len(chunks):
        issues.append("chunk_count must match chunks length")
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            issues.append(f"chunks[{index}] must be an object")
            continue
        if chunk.get("schema_version") != VECTOR_CHUNK_SCHEMA_VERSION:
            issues.append(f"chunks[{index}].schema_version is unsupported")
        if not chunk.get("chunk_id"):
            issues.append(f"chunks[{index}].chunk_id is required")
        if not chunk.get("source_record_id"):
            issues.append(f"chunks[{index}].source_record_id is required")
        if not chunk.get("text"):
            issues.append(f"chunks[{index}].text is required")
        embedding = chunk.get("embedding")
        if not isinstance(embedding, list):
            issues.append(f"chunks[{index}].embedding must be a list")
            continue
        if dimensions is not None and len(embedding) != dimensions:
            issues.append(f"chunks[{index}].embedding length must match provider dimensions")
        if not all(isinstance(value, int | float) for value in embedding):
            issues.append(f"chunks[{index}].embedding values must be numeric")
    return issues


def validate_vector_index_source(payload: dict[str, Any]) -> list[str]:
    source_index = payload.get("source_index")
    if not isinstance(source_index, dict):
        return ["source_index must be an object"]
    source_path_value = source_index.get("path")
    expected_sha = source_index.get("sha256")
    if not source_path_value or not expected_sha:
        return ["source_index.path and source_index.sha256 are required"]
    source_path = Path(str(source_path_value))
    if not source_path.exists():
        return []
    actual_sha = file_sha256(source_path)
    if actual_sha != expected_sha:
        return ["source index SHA-256 does not match vector index metadata; rebuild the vector index"]
    return []


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have matching dimensions")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True)) / (left_norm * right_norm)


def search_vector_index(
    vector_index_path: Path,
    query: str,
    *,
    provider: EmbeddingProvider | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    payload = load_vector_index(vector_index_path)
    issues = validate_vector_index_payload(payload)
    if issues:
        raise ValueError("; ".join(issues))
    embedding_provider = provider or DeterministicHashEmbeddingProvider(
        dimensions=int(payload["embedding_provider"]["dimensions"])
    )
    query_embedding = embedding_provider.embed(query)
    results: list[dict[str, Any]] = []
    for chunk in payload["chunks"]:
        score = cosine_similarity(query_embedding, list(chunk["embedding"]))
        results.append(
            {
                "score": score,
                "chunk_id": chunk["chunk_id"],
                "source_record_id": chunk["source_record_id"],
                "record_type": chunk.get("record_type", ""),
                "page": chunk.get("page", 0),
                "artifact_path": chunk.get("artifact_path", ""),
                "text": chunk.get("text", ""),
                "metadata": chunk.get("metadata", {}),
            }
        )
    results.sort(key=lambda item: (-float(item["score"]), str(item["chunk_id"])))
    return results[:limit]
