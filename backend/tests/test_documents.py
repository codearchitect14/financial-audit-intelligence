"""Document upload tests.

Upload is the most exposed write path: payload, filename, and declared type are
all supplied by the caller. Each test here corresponds to a real vulnerability
class rather than to a line of code.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete, select

from fai.core.errors import ValidationError
from fai.db.models import Document, Organization, User
from fai.db.session import sync_session
from fai.services.documents import store_upload, validate_upload_headers

API = "/api/v1"

PDF_BYTES = b"%PDF-1.4\n" + b"x" * 512


# ---------------------------------------------------------------------------
# Unit level
# ---------------------------------------------------------------------------
class TestStoragePathSafety:
    """A generated path is the only defence that actually holds. Sanitising a
    user-supplied name is a game of whack-a-mole across platforms."""

    @pytest.mark.parametrize(
        "filename",
        [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config",
            "/absolute/path/payload.pdf",
            "C:\\Windows\\System32\\payload.pdf",
            "normal.pdf",
            "no-extension",
            "....//....//escape.pdf",
        ],
    )
    def test_stored_path_never_escapes_the_upload_root(self, tmp_path: Path, filename: str) -> None:
        org_id, doc_id = uuid.uuid4(), uuid.uuid4()

        relative, _, _ = store_upload(
            io.BytesIO(PDF_BYTES),
            organization_id=org_id,
            document_id=doc_id,
            content_type="application/pdf",
            filename=filename,
            upload_root=tmp_path,
        )

        resolved = (tmp_path / relative).resolve()
        assert resolved.is_relative_to(tmp_path.resolve())
        # The stored name is derived from the generated document id, never from
        # anything the caller supplied.
        assert str(doc_id) in resolved.name

    def test_files_are_sharded_by_organization(self, tmp_path: Path) -> None:
        org_id = uuid.uuid4()
        relative, _, _ = store_upload(
            io.BytesIO(PDF_BYTES),
            organization_id=org_id,
            document_id=uuid.uuid4(),
            content_type="application/pdf",
            filename="report.pdf",
            upload_root=tmp_path,
        )
        assert relative.parts[0] == str(org_id)


class TestSizeAndContentValidation:
    def test_oversize_upload_is_rejected_while_streaming(self, tmp_path: Path) -> None:
        """The cap is enforced against bytes actually read, not against the
        Content-Length header, which a client can simply lie about."""
        with pytest.raises(ValidationError, match="exceeds"):
            store_upload(
                io.BytesIO(b"%PDF-1.4\n" + b"x" * 5000),
                organization_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                content_type="application/pdf",
                filename="big.pdf",
                upload_root=tmp_path,
                max_bytes=1024,
            )

    def test_rejected_upload_leaves_no_file_behind(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError):
            store_upload(
                io.BytesIO(b"%PDF-1.4\n" + b"x" * 5000),
                organization_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                content_type="application/pdf",
                filename="big.pdf",
                upload_root=tmp_path,
                max_bytes=1024,
            )

        assert not any(tmp_path.rglob("*.partial"))
        assert not any(p for p in tmp_path.rglob("*") if p.is_file())

    def test_empty_upload_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="empty"):
            store_upload(
                io.BytesIO(b""),
                organization_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                content_type="text/plain",
                filename="empty.txt",
                upload_root=tmp_path,
            )

    def test_content_must_match_the_declared_type(self, tmp_path: Path) -> None:
        """A declared Content-Type is a claim by the uploader, not evidence."""
        with pytest.raises(ValidationError, match="does not match"):
            store_upload(
                io.BytesIO(b"MZ\x90\x00this is an executable"),
                organization_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                content_type="application/pdf",
                filename="actually-an-exe.pdf",
                upload_root=tmp_path,
            )

    def test_identical_content_produces_an_identical_digest(self, tmp_path: Path) -> None:
        _, _, first = store_upload(
            io.BytesIO(PDF_BYTES),
            organization_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            content_type="application/pdf",
            filename="a.pdf",
            upload_root=tmp_path,
        )
        _, _, second = store_upload(
            io.BytesIO(PDF_BYTES),
            organization_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            content_type="application/pdf",
            filename="b.pdf",
            upload_root=tmp_path,
        )
        assert first == second


class TestHeaderValidation:
    def test_disallowed_type_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Unsupported file type"):
            validate_upload_headers("application/x-msdownload", "payload.exe")

    def test_type_parameters_are_ignored(self) -> None:
        content_type, _ = validate_upload_headers("text/csv; charset=utf-8", "data.csv")
        assert content_type == "text/csv"

    def test_missing_filename_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="filename"):
            validate_upload_headers("application/pdf", None)

    def test_missing_content_type_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Content-Type"):
            validate_upload_headers(None, "report.pdf")


# ---------------------------------------------------------------------------
# Integration level
# ---------------------------------------------------------------------------
@pytest.mark.integration
class TestUploadEndpoint:
    @pytest.fixture(autouse=True)
    def _purge(self, require_database: None):
        def purge() -> None:
            with sync_session() as session:
                for org in session.execute(
                    select(Organization).where(Organization.name.like("DocTest%"))
                ).scalars():
                    session.delete(org)
                session.execute(delete(User).where(User.email.like("doc-%@example.com")))

        purge()
        yield
        purge()

    @pytest.fixture(autouse=True)
    def _upload_root(self, app, tmp_path: Path):
        """Point uploads at a temp directory.

        Through dependency_overrides rather than by mutating settings: the
        settings object is frozen on purpose, and overriding the dependency is
        what FastAPI provides for exactly this.
        """
        from fai.api.deps import get_upload_root

        app.dependency_overrides[get_upload_root] = lambda: tmp_path
        yield
        app.dependency_overrides.pop(get_upload_root, None)

    async def _register(self, client: httpx.AsyncClient) -> dict:
        response = await client.post(
            f"{API}/auth/register",
            json={
                "email": f"doc-{uuid.uuid4().hex[:12]}@example.com",
                "password": "a-sufficiently-long-password",
                "full_name": "Doc Test User",
                "organization_name": f"DocTest {uuid.uuid4().hex[:8]}",
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    def _auth(self, body: dict) -> dict[str, str]:
        return {"Authorization": f"Bearer {body['tokens']['access_token']}"}

    async def test_upload_creates_a_document(
        self, client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        body = await self._register(client)

        response = await client.post(
            f"{API}/documents",
            files={"file": ("filing.pdf", PDF_BYTES, "application/pdf")},
            headers=self._auth(body),
        )

        assert response.status_code == 201, response.text
        assert response.json()["original_filename"] == "filing.pdf"
        assert response.json()["size_bytes"] == len(PDF_BYTES)

    async def test_reupload_of_identical_content_is_deduplicated(
        self, client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        """Embedding is the expensive step downstream; paying for it twice on
        identical bytes is pure waste."""
        body = await self._register(client)

        first = await client.post(
            f"{API}/documents",
            files={"file": ("filing.pdf", PDF_BYTES, "application/pdf")},
            headers=self._auth(body),
        )
        second = await client.post(
            f"{API}/documents",
            files={"file": ("renamed.pdf", PDF_BYTES, "application/pdf")},
            headers=self._auth(body),
        )

        assert first.json()["id"] == second.json()["id"]

        with sync_session() as session:
            count = len(
                session.execute(
                    select(Document).where(
                        Document.organization_id == uuid.UUID(body["organization"]["id"])
                    )
                )
                .scalars()
                .all()
            )
        assert count == 1

    async def test_disallowed_type_is_rejected(
        self, client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        body = await self._register(client)

        response = await client.post(
            f"{API}/documents",
            files={"file": ("payload.exe", b"MZ\x90\x00", "application/x-msdownload")},
            headers=self._auth(body),
        )
        assert response.status_code == 422

    async def test_traversal_filename_does_not_escape_the_root(
        self, client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        body = await self._register(client)

        response = await client.post(
            f"{API}/documents",
            files={"file": ("../../escape.pdf", PDF_BYTES, "application/pdf")},
            headers=self._auth(body),
        )

        assert response.status_code == 201
        for path in tmp_path.rglob("*"):
            assert path.resolve().is_relative_to(tmp_path.resolve())

    async def test_viewer_role_cannot_upload(
        self, client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        from fai.core.security import create_access_token
        from fai.db.models import UserRole

        body = await self._register(client)

        with sync_session() as session:
            user = session.execute(
                select(User).where(User.id == uuid.UUID(body["user"]["id"]))
            ).scalar_one()
            user.role = UserRole.VIEWER

        token = create_access_token(
            user_id=uuid.UUID(body["user"]["id"]),
            organization_id=uuid.UUID(body["organization"]["id"]),
            role=UserRole.VIEWER.value,
        )
        response = await client.post(
            f"{API}/documents",
            files={"file": ("filing.pdf", PDF_BYTES, "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403

    async def test_documents_are_not_visible_across_tenants(
        self, client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        owner = await self._register(client)
        outsider = await self._register(client)

        uploaded = await client.post(
            f"{API}/documents",
            files={"file": ("private.pdf", PDF_BYTES, "application/pdf")},
            headers=self._auth(owner),
        )
        document_id = uploaded.json()["id"]

        assert (
            await client.get(f"{API}/documents/{document_id}", headers=self._auth(owner))
        ).status_code == 200
        assert (
            await client.get(f"{API}/documents/{document_id}", headers=self._auth(outsider))
        ).status_code == 404
