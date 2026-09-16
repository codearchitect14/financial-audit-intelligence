"""Text embedding.

Uses ``fastembed``, which runs ``BAAI/bge-small-en-v1.5`` through ONNX Runtime.
The project plan specified ``sentence-transformers``, which pulls in torch at
roughly 800MB installed; free-tier hosting gives the API instance about 512MB of
memory, so that install cannot run there at all. The ONNX build produces the
same 384-dimension vectors at roughly a tenth of the footprint, so the schema
and every stored vector are unaffected.

The model is loaded lazily and once. Loading it costs a few seconds and around
100MB, which must not be paid during application start-up on a platform that
counts boot time against a health-check deadline.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Sequence
from functools import lru_cache
from typing import Protocol

from fai.core.config import settings
from fai.core.logging import get_logger

log = get_logger(__name__)

# Guards the one-time model load. Two requests arriving together would otherwise
# each construct a model and double the memory footprint on a box that has none
# to spare.
_load_lock = threading.Lock()


class Embedder(Protocol):
    """Minimal embedding interface.

    A protocol rather than a concrete class so the search layer can be tested
    without loading a real model, and so the backend can be swapped without
    touching callers.
    """

    @property
    def dimensions(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """ONNX-backed embedder."""

    def __init__(self, model_name: str | None = None, dimensions: int | None = None):
        self._model_name = model_name or settings.embedding_model
        self._dimensions = dimensions or settings.embedding_dimensions
        self._model: object | None = None

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _ensure_model(self) -> object:
        if self._model is None:
            with _load_lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    log.info("embedding_model_loading", model=self._model_name)
                    self._model = TextEmbedding(model_name=self._model_name)
                    log.info("embedding_model_loaded", model=self._model_name)
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of passages."""
        if not texts:
            return []
        model = self._ensure_model()
        vectors = [list(map(float, vector)) for vector in model.embed(list(texts))]  # type: ignore[attr-defined]

        for vector in vectors:
            if len(vector) != self._dimensions:
                # A width mismatch would be written into a vector(384) column
                # and rejected by Postgres, or worse, silently indexed wrong.
                raise ValueError(
                    f"Embedding model returned {len(vector)} dimensions but the schema "
                    f"expects {self._dimensions}. Changing the model requires a "
                    f"migration and a full re-embed."
                )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query.

        bge models are trained with an instruction prefix on the query side but
        not on the passage side. Omitting it measurably degrades retrieval, and
        it is the single easiest thing to get wrong with this model family.
        """
        prefixed = f"Represent this sentence for searching relevant passages: {text}"
        return self.embed([prefixed])[0]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    """Return the process-wide embedder."""
    return FastEmbedEmbedder()


def chunk_text(
    text: str,
    *,
    target_tokens: int = 320,
    overlap_tokens: int = 48,
) -> list[str]:
    """Split long text into overlapping passages.

    Splits on paragraph boundaries where it can, because a chunk that begins
    mid-sentence embeds poorly and reads badly when shown to a user as a search
    result.

    The overlap exists so that a passage spanning a chunk boundary is still
    retrievable: without it, the one sentence that answers a question can fall
    exactly on the split and become invisible to search.

    Token counts are approximated at four characters per token. Running the real
    tokeniser here would be more accurate and would cost a model load during
    ingestion for a gain that does not change which chunks are retrieved.
    """
    if not text or not text.strip():
        return []

    chars_per_token = 4
    target_chars = target_tokens * chars_per_token
    overlap_chars = overlap_tokens * chars_per_token

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > target_chars:
            # A single oversized paragraph (a dense footnote, a table dumped as
            # text) is split on length; there is no better boundary available.
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(paragraph), target_chars - overlap_chars):
                piece = paragraph[start : start + target_chars].strip()
                if piece:
                    chunks.append(piece)
            continue

        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= target_chars:
            current = candidate
        else:
            chunks.append(current)
            # Carry the tail of the previous chunk forward as context.
            tail = current[-overlap_chars:] if overlap_chars else ""
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph

    if current:
        chunks.append(current)

    return [chunk for chunk in chunks if chunk.strip()]


def batched(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    """Yield fixed-size batches, so a large document never embeds all at once."""
    for start in range(0, len(items), size):
        yield items[start : start + size]
