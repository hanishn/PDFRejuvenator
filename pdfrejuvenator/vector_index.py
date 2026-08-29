from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


VECTOR_INDEX_SCHEMA_VERSION = "pdfrejuvenator.vector_index.v0.6"
VECTOR_CHUNK_SCHEMA_VERSION = "pdfrejuvenator.vector_chunk.v0.6"
DEFAULT_VECTOR_DIMENSIONS = 32
DEFAULT_CHUNK_MAX_CHARS = 1400
DEFAULT_CHUNK_OVERLAP_CHARS = 0
DEFAULT_EMBEDDING_PROVIDER = "deterministic-test"
DEFAULT_OLLAMA_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 120.0


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


@dataclass(frozen=True)
class VectorSearchResult:
    score: float
    chunk_id: str
    source_record_id: str
    record_type: str
    page: int
    artifact_path: str
    metadata: dict[str, Any]
    text: str = ""

    @property
    def source_id(self) -> str:
        return self.source_record_id

    def to_dict(self, *, hide_text: bool = False) -> dict[str, Any]:
        output = {
            "score": self.score,
            "chunk_id": self.chunk_id,
            "source_id": self.source_id,
            "source_record_id": self.source_record_id,
            "record_type": self.record_type,
            "page": self.page,
            "artifact_path": self.artifact_path,
            "metadata": self.metadata,
        }
        if not hide_text:
            output["text"] = self.text
        return output


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
            provider=DEFAULT_EMBEDDING_PROVIDER,
            model="blake2b-token-buckets",
            dimensions=dimensions,
            fingerprint=f"{DEFAULT_EMBEDDING_PROVIDER}:{dimensions}:v1",
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


class OllamaEmbeddingProvider:
    """Local Ollama embeddings for private on-machine retrieval indexes."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_OLLAMA_EMBEDDING_MODEL,
        base_url: str = DEFAULT_OLLAMA_URL,
        timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS,
        dimensions: int | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("ollama model must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("ollama timeout_seconds must be greater than zero")
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        resolved_dimensions = dimensions or len(self.embed("pdfrejuvenator embedding dimension probe"))
        if resolved_dimensions <= 0:
            raise ValueError("ollama embedding dimensions must be greater than zero")
        self._info = EmbeddingModelInfo(
            provider="ollama",
            model=self.model,
            dimensions=resolved_dimensions,
            fingerprint=f"ollama:{self.model}:{resolved_dimensions}:v1",
        )

    @property
    def info(self) -> EmbeddingModelInfo:
        return self._info

    def embed(self, text: str) -> list[float]:
        payload = json.dumps({"model": self.model, "input": text}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise ValueError(f"ollama embedding request failed for model {self.model}: {exc}") from exc
        embeddings = body.get("embeddings")
        if not isinstance(embeddings, list) or not embeddings:
            raise ValueError("ollama embedding response did not include embeddings")
        embedding = embeddings[0]
        if not isinstance(embedding, list) or not all(isinstance(value, int | float) for value in embedding):
            raise ValueError("ollama embedding response must be a numeric vector")
        return [float(value) for value in embedding]


def create_embedding_provider(
    name: str = DEFAULT_EMBEDDING_PROVIDER,
    *,
    dimensions: int = DEFAULT_VECTOR_DIMENSIONS,
    model: str | None = None,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    ollama_timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS,
) -> EmbeddingProvider:
    normalized = name.strip().lower().replace("_", "-")
    if normalized in {DEFAULT_EMBEDDING_PROVIDER, "deterministic-hash"}:
        return DeterministicHashEmbeddingProvider(dimensions=dimensions if dimensions > 0 else DEFAULT_VECTOR_DIMENSIONS)
    if normalized == "ollama":
        return OllamaEmbeddingProvider(
            model=model or DEFAULT_OLLAMA_EMBEDDING_MODEL,
            base_url=ollama_url,
            timeout_seconds=ollama_timeout_seconds,
            dimensions=dimensions if dimensions > 0 else None,
        )
    raise ValueError(f"unsupported embedding provider: {name}")


def list_embedding_providers() -> list[dict[str, Any]]:
    provider = DeterministicHashEmbeddingProvider()
    return [
        {
            "name": provider.info.provider,
            "model": provider.info.model,
            "dimensions": provider.info.dimensions,
            "fingerprint": provider.info.fingerprint,
            "network": "none",
            "intended_use": "public-safe validation and deterministic local smoke tests",
        },
        {
            "name": "ollama",
            "model": DEFAULT_OLLAMA_EMBEDDING_MODEL,
            "dimensions": "model-dependent",
            "fingerprint": "ollama:<model>:<dimensions>:v1",
            "network": "local-only",
            "intended_use": "private local semantic retrieval indexes",
        },
    ]


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


def chunk_text(
    text: str,
    *,
    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
) -> list[str]:
    clean = " ".join(text.split())
    if not clean:
        return []
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be zero or greater")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be less than max_chars")
    chunks: list[str] = []
    current = ""
    for token in clean.split(" "):
        next_value = token if not current else f"{current} {token}"
        if len(next_value) <= max_chars:
            current = next_value
            continue
        if current:
            chunks.append(current)
        if overlap_chars:
            overlap = current[-overlap_chars:].strip()
            current = f"{overlap} {token}".strip() if overlap else token
        else:
            current = token
    if current:
        chunks.append(current)
    return chunks


def search_record_to_vector_chunks(
    record: dict[str, Any],
    *,
    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
) -> list[dict[str, Any]]:
    record_id = str(record.get("record_id", ""))
    chunks = chunk_text(str(record.get("text", "")), max_chars=max_chars, overlap_chars=overlap_chars)
    vector_chunks: list[dict[str, Any]] = []
    for index, text in enumerate(chunks):
        chunk_id = "::".join(part for part in [record_id, f"chunk{index:04d}"] if part)
        vector_chunks.append(
            {
                "schema_version": VECTOR_CHUNK_SCHEMA_VERSION,
                "chunk_id": chunk_id,
                "chunk_index": index,
                "chunk_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
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
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
    include_text: bool = True,
) -> dict[str, Any]:
    source_records = load_search_index(search_index_path)
    embedding_provider = provider or DeterministicHashEmbeddingProvider()
    chunks: list[dict[str, Any]] = []
    for record in source_records:
        chunks.extend(search_record_to_vector_chunks(record, max_chars=max_chars, overlap_chars=overlap_chars))
    embedded_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        text = str(chunk.get("text", ""))
        embedded_chunk = {
            **chunk,
            "embedding": embedding_provider.embed(text),
            "text_redacted": not include_text,
        }
        if not include_text:
            embedded_chunk.pop("text", None)
        embedded_chunks.append(embedded_chunk)
    return {
        "schema_version": VECTOR_INDEX_SCHEMA_VERSION,
        "source_index": {
            "path": str(search_index_path),
            "sha256": file_sha256(search_index_path),
            "record_count": len(source_records),
        },
        "embedding_provider": embedding_provider.info.to_dict(),
        "chunking": {
            "strategy": "whitespace_max_chars_with_optional_overlap",
            "max_chars": max_chars,
            "overlap_chars": overlap_chars,
            "include_text": include_text,
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
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
    include_text: bool = True,
) -> int:
    payload = build_vector_index_payload(
        search_index_path,
        provider=provider,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        include_text=include_text,
    )
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
        text = chunk.get("text")
        text_redacted = chunk.get("text_redacted") is True
        if not chunk.get("chunk_sha256"):
            issues.append(f"chunks[{index}].chunk_sha256 is required")
        elif text and hashlib.sha256(str(text).encode("utf-8")).hexdigest() != chunk.get("chunk_sha256"):
            issues.append(f"chunks[{index}].chunk_sha256 must match text")
        if not chunk.get("source_record_id"):
            issues.append(f"chunks[{index}].source_record_id is required")
        if not text and not text_redacted:
            issues.append(f"chunks[{index}].text is required unless text_redacted is true")
        embedding = chunk.get("embedding")
        if not isinstance(embedding, list):
            issues.append(f"chunks[{index}].embedding must be a list")
            continue
        if dimensions is not None and len(embedding) != dimensions:
            issues.append(f"chunks[{index}].embedding length must match provider dimensions")
        if not all(isinstance(value, int | float) for value in embedding):
            issues.append(f"chunks[{index}].embedding values must be numeric")
    return issues


def validate_vector_index_provider(payload: dict[str, Any], provider: EmbeddingProvider) -> list[str]:
    stored = payload.get("embedding_provider")
    if not isinstance(stored, dict):
        return ["embedding_provider must be an object"]
    expected = provider.info.to_dict()
    issues: list[str] = []
    for field in ("provider", "model", "dimensions", "fingerprint"):
        if stored.get(field) != expected[field]:
            issues.append(f"embedding_provider.{field} does not match requested provider")
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
    min_score: float | None = None,
) -> list[VectorSearchResult]:
    payload = load_vector_index(vector_index_path)
    issues = validate_vector_index_payload(payload)
    if issues:
        raise ValueError("; ".join(issues))
    embedding_provider = provider or DeterministicHashEmbeddingProvider(
        dimensions=int(payload["embedding_provider"]["dimensions"])
    )
    provider_issues = validate_vector_index_provider(payload, embedding_provider)
    if provider_issues:
        raise ValueError("; ".join(provider_issues))
    query_embedding = embedding_provider.embed(query)
    results: list[VectorSearchResult] = []
    for chunk in payload["chunks"]:
        score = cosine_similarity(query_embedding, list(chunk["embedding"]))
        if min_score is not None and score < min_score:
            continue
        results.append(
            VectorSearchResult(
                score=score,
                chunk_id=str(chunk["chunk_id"]),
                source_record_id=str(chunk["source_record_id"]),
                record_type=str(chunk.get("record_type", "")),
                page=int(chunk.get("page", 0) or 0),
                artifact_path=str(chunk.get("artifact_path", "")),
                text=str(chunk.get("text", "")),
                metadata=dict(chunk.get("metadata", {})) if isinstance(chunk.get("metadata"), dict) else {},
            )
        )
    results.sort(key=lambda item: (-float(item.score), item.chunk_id))
    return results[:limit]


def serialize_vector_search_results(results: list[VectorSearchResult], *, hide_text: bool = False) -> list[dict[str, Any]]:
    return [result.to_dict(hide_text=hide_text) for result in results]


def inspect_vector_index_payload(payload: dict[str, Any]) -> dict[str, Any]:
    issues = validate_vector_index_payload(payload)
    source_issues = validate_vector_index_source(payload)
    provider = payload.get("embedding_provider", {})
    chunking = payload.get("chunking", {})
    chunks = payload.get("chunks", [])
    return {
        "schema_version": payload.get("schema_version", ""),
        "chunk_count": len(chunks) if isinstance(chunks, list) else 0,
        "declared_chunk_count": payload.get("chunk_count", 0),
        "source_index": payload.get("source_index", {}),
        "embedding_provider": provider if isinstance(provider, dict) else {},
        "chunking": chunking if isinstance(chunking, dict) else {},
        "validation_issue_count": len(issues) + len(source_issues),
        "validation_issues": [*issues, *source_issues],
    }
