"""Ingest documents into ChromaDB + search them. Owner: A. Shapes: docs/CONTRACT.md section 2."""


def ingest_file(path: str, meta: dict) -> dict:
    """Load PDF -> split by section/page -> embed -> Chroma (metadata = Annex B fields + section + page)."""
    raise NotImplementedError("A: build me")


def search(query: str, k: int) -> list[dict]:
    """Top-k chunks with metadata and similarity score."""
    return []  # fake until A lands the real one


def list_sources() -> list[dict]:
    return []
