"""Configuration parsing tests.

These cover the env-parsing edge cases that are easy to get wrong and that fail
only at deploy time, where the feedback loop is slowest.
"""

from __future__ import annotations

from fai.core.config import Settings


class TestDatabaseUrlDerivation:
    """One DSN is configured; both driver variants are derived from it, so they
    can never drift apart between the app and its migrations."""

    def test_async_variant_uses_asyncpg(self) -> None:
        settings = Settings(database_url="postgresql://u:p@host:5432/db")
        assert settings.async_database_url == "postgresql+asyncpg://u:p@host:5432/db"

    def test_sync_variant_uses_psycopg(self) -> None:
        settings = Settings(database_url="postgresql://u:p@host:5432/db")
        assert settings.sync_database_url == "postgresql+psycopg://u:p@host:5432/db"

    def test_both_variants_describe_the_same_target(self) -> None:
        settings = Settings(database_url="postgresql://u:p@host:5432/db")
        assert (
            settings.async_database_url.split("://", 1)[1]
            == (settings.sync_database_url.split("://", 1)[1])
        )


class TestListParsing:
    """Hosting platforms supply env vars as plain strings, so a comma-separated
    value must work as well as a JSON list."""

    def test_comma_separated_string(self) -> None:
        settings = Settings(cors_origins="https://a.example.com,https://b.example.com")
        assert settings.cors_origins == ["https://a.example.com", "https://b.example.com"]

    def test_surrounding_whitespace_is_stripped(self) -> None:
        settings = Settings(cors_origins=" https://a.example.com , https://b.example.com ")
        assert settings.cors_origins == ["https://a.example.com", "https://b.example.com"]

    def test_json_list_string(self) -> None:
        settings = Settings(cors_origins='["https://a.example.com"]')
        assert settings.cors_origins == ["https://a.example.com"]

    def test_native_list_is_untouched(self) -> None:
        settings = Settings(cors_origins=["https://a.example.com"])
        assert settings.cors_origins == ["https://a.example.com"]

    def test_empty_segments_are_dropped(self) -> None:
        settings = Settings(cors_origins="https://a.example.com,,")
        assert settings.cors_origins == ["https://a.example.com"]


class TestSecretHandling:
    def test_secret_is_not_exposed_by_repr(self) -> None:
        """A settings object reaches log lines and crash reports. The signing
        key must not be readable in either."""
        settings = Settings(jwt_secret_key="super-secret-value")
        assert "super-secret-value" not in repr(settings)
        assert settings.jwt_secret_key.get_secret_value() == "super-secret-value"


class TestEnvironmentFlags:
    def test_is_production_is_true_only_for_production(self) -> None:
        assert Settings(environment="production").is_production is True
        for env in ("local", "ci", "staging"):
            assert Settings(environment=env).is_production is False
