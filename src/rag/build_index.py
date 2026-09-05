"""Build a local vulnerability knowledge index.

Chroma and transformer embeddings are used when installed.  A JSON token index
is always written as a deterministic, dependency-free fallback.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _chunks(text: str, size: int = 300) -> list[str]:
    words = text.split()
    return [" ".join(words[start : start + size]) for start in range(0, len(words), size)] or [text]


def _documents(knowledge_dir: str | Path) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in sorted(Path(knowledge_dir).glob("*.md")) + sorted(Path(knowledge_dir).glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        for number, chunk in enumerate(_chunks(text)):
            documents.append(
                {
                    "id": hashlib.sha1(f"{path}:{number}".encode()).hexdigest(),
                    "text": chunk,
                    "source": path.name,
                    "chunk": number,
                }
            )
    return documents


def build_index(
    knowledge_dir: str | Path = "knowledge_base",
    persist_directory: str | Path = "chroma_db",
    embedding_model: str = "all-MiniLM-L6-v2",
) -> int:
    """Index documents and return the number of chunks indexed."""
    documents = _documents(knowledge_dir)
    persist = Path(persist_directory)
    persist.mkdir(parents=True, exist_ok=True)
    (persist / "knowledge_index.json").write_text(
        json.dumps(documents, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    try:
        import chromadb  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore

        client = chromadb.PersistentClient(path=str(persist))
        collection = client.get_or_create_collection("vuln_knowledge")
        model = SentenceTransformer(embedding_model)
        collection.upsert(
            ids=[item["id"] for item in documents],
            documents=[item["text"] for item in documents],
            metadatas=[{"source": item["source"], "chunk": item["chunk"]} for item in documents],
            embeddings=model.encode([item["text"] for item in documents]).tolist(),
        )
    except (ImportError, ModuleNotFoundError):
        # The JSON index is sufficient for the standard-library retriever.
        pass
    except Exception as exc:
        # Preserve the usable fallback, but make setup problems actionable.
        print(f"Warning: Chroma embedding index unavailable ({exc}); using JSON fallback.")
    return len(documents)


if __name__ == "__main__":
    print(f"Indexed {build_index()} knowledge chunks.")
