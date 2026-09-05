from .retriever import retrieve


def build_index(*args, **kwargs):
    """Build the index without importing setup dependencies during package import."""
    from .build_index import build_index as _build_index

    return _build_index(*args, **kwargs)


__all__ = ["build_index", "retrieve"]