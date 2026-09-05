"""Retrieve vulnerability context from Chroma or a deterministic token index."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_'-]+", value.lower()))


def _fallback(query: str, index_path: Path, k: int) -> list[str]:
    if not index_path.is_file():
        return []
    try:
        records: list[dict[str, Any]] = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    query_tokens = _tokens(query)
    scored = []
    for record in records:
        text_tokens = _tokens(str(record.get("text", "")))
        overlap = len(query_tokens & text_tokens)
        score = overlap / math.sqrt(max(1, len(query_tokens) * len(text_tokens)))
        scored.append((score, str(record.get("text", ""))))
    return [text for score, text in sorted(scored, key=lambda item: item[0], reverse=True)[:k] if text]


def retrieve(
    query: str,
    k: int = 3,
    persist_directory: str | Path = "chroma_db",
    embedding_model: str = "all-MiniLM-L6-v2",
) -> list[str]:
    """Return up to *k* relevant knowledge chunks; never requires optional packages."""
    if k <= 0:
        return []
    persist = Path(persist_directory)
    try:
        import chromadb  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore

        collection = chromadb.PersistentClient(path=str(persist)).get_collection("vuln_knowledge")
        embedding = SentenceTransformer(embedding_model).encode([query]).tolist()
        result = collection.query(query_embeddings=embedding, n_results=k)
        return [str(item) for item in (result.get("documents") or [[]])[0]]
    except Exception:
        return _fallback(query, persist / "knowledge_index.json", k)
