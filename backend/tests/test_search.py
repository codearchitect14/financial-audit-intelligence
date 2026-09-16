"""Embedding, chunking, and semantic search tests.

The integration tests use a deterministic fake embedder rather than the real
ONNX model. Loading the real model costs seconds and ~100MB per run and would
make the suite dependent on a model download, while testing nothing about this
code: what matters here is that vectors round-trip through pgvector, that
ordering follows cosine distance, and that results never cross a tenant
boundary.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence

import httpx
import pytest
from sqlalchemy import delete, select

from fai.db.models import Document, DocumentChunk, Organization, User
from fai.db.models.enums import DocumentStatus, DocumentType
from fai.db.session import sync_session
from fai.search.embeddings import batched, chunk_text
from fai.search.service import index_document

API = "/api/v1"


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
class TestChunking:
    def test_empty_text_yields_no_chunks(self) -> None:
        assert chunk_text("") == []
        assert chunk_text("   \n\n  ") == []

    def test_short_text_is_a_single_chunk(self) -> None:
        assert chunk_text("A short passage.") == ["A short passage."]

    def test_long_text_is_split(self) -> None:
        text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(20))
        chunks = chunk_text(text, target_tokens=100, overlap_tokens=10)
        assert len(chunks) > 1

    def test_chunks_respect_the_target_size(self) -> None:
        text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(20))
        chunks = chunk_text(text, target_tokens=100, overlap_tokens=10)
        # Four characters per token is the approximation the splitter uses.
        assert all(len(chunk) <= 100 * 4 + 1 for chunk in chunks)

    def test_oversized_paragraph_is_split_on_length(self) -> None:
        """A dense footnote or a table dumped as text has no paragraph
        boundary to split on, so length is the only option left."""
        chunks = chunk_text("x" * 5000, target_tokens=100, overlap_tokens=10)
        assert len(chunks) > 1

    def test_chunks_overlap(self) -> None:
        """Without overlap, the one sentence that answers a question can land
        exactly on a split and become unreachable by search."""
        paragraphs = [f"Paragraph number {i} with some content here." for i in range(30)]
        chunks = chunk_text("\n\n".join(paragraphs), target_tokens=40, overlap_tokens=10)

        assert len(chunks) > 1
        # Some text from the end of one chunk reappears at the start of the next.
        assert any(
            chunks[i][-20:].strip() and chunks[i][-20:].strip()[:10] in chunks[i + 1]
            for i in range(len(chunks) - 1)
        )

    def test_no_chunk_is_blank(self) -> None:
        text = "\n\n\n\nFirst.\n\n\n\nSecond.\n\n\n\n"
        assert all(chunk.strip() for chunk in chunk_text(text))


class TestBatching:
    def test_splits_into_fixed_sizes(self) -> None:
        assert [list(b) for b in batched(["a", "b", "c", "d", "e"], 2)] == [
            ["a", "b"],
            ["c", "d"],
            ["e"],
        ]

    def test_empty_input_yields_nothing(self) -> None:
        assert list(batched([], 10)) == []


# ---------------------------------------------------------------------------
# Deterministic test embedder
# ---------------------------------------------------------------------------
class FakeEmbedder:
    """A deterministic embedder with real cosine geometry.

    Hashes each token into a fixed bucket and L2-normalises, so texts sharing
    vocabulary genuinely sit closer together. That is enough to verify ordering
    without loading a 100MB model.
    """

    def __init__(self, dimensions: int = 384):
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in text.lower().split():
            vector[hash(token) % self._dimensions] += 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            # A zero vector has no direction, so cosine distance is undefined.
            vector[0] = 1.0
            norm = 1.0
        return [v / norm for v in vector]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


class TestFakeEmbedderSanity:
    """The fake must have real cosine geometry or the tests using it prove
    nothing about ordering."""

    def test_identical_text_is_identical(self, embedder: FakeEmbedder) -> None:
        assert embedder.embed(["hello world"]) == embedder.embed(["hello world"])

    def test_vectors_are_normalised(self, embedder: FakeEmbedder) -> None:
        vector = embedder.embed(["revenue recognition policy"])[0]
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-9)

    def test_shared_vocabulary_is_closer(self, embedder: FakeEmbedder) -> None:
        a = embedder.embed(["revenue recognition policy"])[0]
        b = embedder.embed(["revenue recognition standard"])[0]
        c = embedder.embed(["completely unrelated aviation topic"])[0]

        assert sum(x * y for x, y in zip(a, b, strict=True)) > sum(
            x * y for x, y in zip(a, c, strict=True)
        )


# ---------------------------------------------------------------------------
# Indexing and search
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestIndexingAndSearch:
    @pytest.fixture(autouse=True)
    def _purge(self, require_database: None):
        def purge() -> None:
            with sync_session() as session:
                for org in session.execute(
                    select(Organization).where(Organization.name.like("SearchTest%"))
                ).scalars():
                    session.delete(org)
                session.execute(delete(User).where(User.email.like("search-%@example.com")))

        purge()
        yield
        purge()

    def _make_document(self, organization_id: uuid.UUID, name: str) -> uuid.UUID:
        with sync_session() as session:
            document = Document(
                organization_id=organization_id,
                uploaded_by=None,
                file_path=f"{organization_id}/{uuid.uuid4()}.txt",
                original_filename=name,
                content_type="text/plain",
                size_bytes=100,
                sha256=uuid.uuid4().hex * 2,
                doc_type=DocumentType.FILING,
                status=DocumentStatus.UPLOADED,
            )
            session.add(document)
            session.flush()
            return document.id

    def _index(self, document_id: uuid.UUID, text: str, embedder: FakeEmbedder) -> int:
        with sync_session() as session:
            document = session.get(Document, document_id)
            assert document is not None
            return index_document(session, document, text, embedder=embedder)

    async def _register(self, client: httpx.AsyncClient) -> dict:
        response = await client.post(
            f"{API}/auth/register",
            json={
                "email": f"search-{uuid.uuid4().hex[:12]}@example.com",
                "password": "a-sufficiently-long-password",
                "full_name": "Search Test User",
                "organization_name": f"SearchTest {uuid.uuid4().hex[:8]}",
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    def _auth(self, body: dict) -> dict[str, str]:
        return {"Authorization": f"Bearer {body['tokens']['access_token']}"}

    async def test_indexing_writes_chunks_with_vectors(
        self, client: httpx.AsyncClient, embedder: FakeEmbedder
    ) -> None:
        body = await self._register(client)
        org_id = uuid.UUID(body["organization"]["id"])
        document_id = self._make_document(org_id, "policy.txt")

        written = self._index(
            document_id,
            "\n\n".join(f"Paragraph {i} about revenue recognition." for i in range(10)),
            embedder,
        )

        assert written > 0
        with sync_session() as session:
            chunks = (
                session.execute(
                    select(DocumentChunk).where(DocumentChunk.document_id == document_id)
                )
                .scalars()
                .all()
            )
        assert len(chunks) == written
        assert all(chunk.embedding is not None for chunk in chunks)
        assert all(len(chunk.embedding) == 384 for chunk in chunks)

    async def test_indexing_marks_the_document_indexed(
        self, client: httpx.AsyncClient, embedder: FakeEmbedder
    ) -> None:
        body = await self._register(client)
        document_id = self._make_document(uuid.UUID(body["organization"]["id"]), "notes.txt")
        self._index(document_id, "Some content about audit procedures.", embedder)

        with sync_session() as session:
            document = session.get(Document, document_id)
            assert document is not None
            assert document.status is DocumentStatus.INDEXED

    async def test_reindexing_replaces_rather_than_duplicates(
        self, client: httpx.AsyncClient, embedder: FakeEmbedder
    ) -> None:
        """Two overlapping generations of vectors would both match the same
        query and return the document twice."""
        body = await self._register(client)
        document_id = self._make_document(uuid.UUID(body["organization"]["id"]), "notes.txt")
        text = "\n\n".join(f"Paragraph {i}." for i in range(10))

        first = self._index(document_id, text, embedder)
        second = self._index(document_id, text, embedder)

        assert first == second
        with sync_session() as session:
            count = len(
                session.execute(
                    select(DocumentChunk).where(DocumentChunk.document_id == document_id)
                )
                .scalars()
                .all()
            )
        assert count == first

    async def test_search_ranks_by_similarity(
        self, client: httpx.AsyncClient, embedder: FakeEmbedder, app
    ) -> None:
        from fai.search import service

        body = await self._register(client)
        org_id = uuid.UUID(body["organization"]["id"])
        document_id = self._make_document(org_id, "filing.txt")

        self._index(
            document_id,
            "The company recognises revenue when control transfers.\n\n"
            "Aviation fuel hedging contracts are settled quarterly.\n\n"
            "Inventory is measured at the lower of cost and net realisable value.",
            embedder,
        )

        # The endpoint builds its own embedder; substitute the deterministic one.
        original = service.get_embedder
        service.get_embedder = lambda: embedder  # type: ignore[assignment]
        try:
            response = await client.get(
                f"{API}/search",
                params={"q": "revenue recognises control transfers", "limit": 3},
                headers=self._auth(body),
            )
        finally:
            service.get_embedder = original  # type: ignore[assignment]

        assert response.status_code == 200, response.text
        results = response.json()["results"]
        assert results
        assert "revenue" in results[0]["text"].lower()

    async def test_similarity_is_reported_higher_is_better(
        self, client: httpx.AsyncClient, embedder: FakeEmbedder
    ) -> None:
        """pgvector returns distance; every user reading a score expects the
        opposite direction, so the API converts it."""
        from fai.search import service

        body = await self._register(client)
        document_id = self._make_document(uuid.UUID(body["organization"]["id"]), "filing.txt")
        self._index(document_id, "Revenue recognition policy details.", embedder)

        original = service.get_embedder
        service.get_embedder = lambda: embedder  # type: ignore[assignment]
        try:
            close = await client.get(
                f"{API}/search",
                params={"q": "revenue recognition policy"},
                headers=self._auth(body),
            )
            distant = await client.get(
                f"{API}/search",
                params={"q": "unrelated aviation turbine maintenance"},
                headers=self._auth(body),
            )
        finally:
            service.get_embedder = original  # type: ignore[assignment]

        close_score = close.json()["results"][0]["similarity"]
        distant_score = distant.json()["results"][0]["similarity"]

        # The direction is the contract: a better match scores higher. pgvector
        # natively returns distance, where the opposite is true.
        assert close_score > distant_score
        assert 0.0 <= distant_score <= close_score <= 1.0

    async def test_search_never_crosses_a_tenant_boundary(
        self, client: httpx.AsyncClient, embedder: FakeEmbedder
    ) -> None:
        from fai.search import service

        owner = await self._register(client)
        outsider = await self._register(client)

        document_id = self._make_document(
            uuid.UUID(owner["organization"]["id"]), "confidential.txt"
        )
        self._index(document_id, "Confidential revenue recognition details.", embedder)

        original = service.get_embedder
        service.get_embedder = lambda: embedder  # type: ignore[assignment]
        try:
            owner_results = await client.get(
                f"{API}/search",
                params={"q": "confidential revenue"},
                headers=self._auth(owner),
            )
            outsider_results = await client.get(
                f"{API}/search",
                params={"q": "confidential revenue"},
                headers=self._auth(outsider),
            )
        finally:
            service.get_embedder = original  # type: ignore[assignment]

        assert owner_results.json()["count"] >= 1
        assert outsider_results.json()["count"] == 0

    async def test_search_requires_authentication(self, client: httpx.AsyncClient) -> None:
        response = await client.get(f"{API}/search", params={"q": "anything"})
        assert response.status_code == 401

    async def test_empty_query_is_rejected(self, client: httpx.AsyncClient) -> None:
        body = await self._register(client)
        response = await client.get(f"{API}/search", params={"q": ""}, headers=self._auth(body))
        assert response.status_code == 422

    async def test_oversized_query_is_rejected(self, client: httpx.AsyncClient) -> None:
        body = await self._register(client)
        response = await client.get(
            f"{API}/search", params={"q": "x" * 2000}, headers=self._auth(body)
        )
        assert response.status_code == 422

    async def test_result_limit_is_capped(self, client: httpx.AsyncClient) -> None:
        body = await self._register(client)
        response = await client.get(
            f"{API}/search",
            params={"q": "anything", "limit": 10000},
            headers=self._auth(body),
        )
        assert response.status_code == 422
