"""Rate-limited downloader for SEC hosted files.

The SEC refuses automated requests that do not identify themselves, and
throttles clients that exceed roughly ten requests per second. Both failures
surface as opaque HTTP errors that are easy to misdiagnose as network trouble,
so both are handled explicitly here rather than being discovered in production.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from fai.core.config import settings
from fai.core.errors import UpstreamError
from fai.core.logging import get_logger

log = get_logger(__name__)

DERA_BASE_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets"


class SecDownloader:
    """Fetches SEC files while respecting the published access policy."""

    def __init__(self, *, user_agent: str | None = None, requests_per_second: float | None = None):
        self.user_agent = user_agent or settings.sec_user_agent
        rate = requests_per_second or settings.sec_requests_per_second
        self._min_interval = 1.0 / rate if rate > 0 else 0.0
        self._last_request_at = 0.0

        if "@" not in self.user_agent:
            # The SEC requires a contact address. Failing here is far kinder
            # than a 403 twenty minutes into a download.
            raise ValueError(
                "SEC_USER_AGENT must include a contact email address, for example "
                "'CompanyName name@example.com'. The SEC rejects requests without one."
            )

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def download(self, url: str, destination: Path, *, overwrite: bool = False) -> Path:
        """Download a URL to a local path, streaming to disk.

        Downloads are resumable in the sense that an already-complete file is
        not fetched again: quarterly archives are tens of megabytes and the
        ingestion job is expected to be interrupted and re-run.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not overwrite:
            log.info("download_skipped_present", url=url, path=str(destination))
            return destination

        self._throttle()
        log.info("download_started", url=url, path=str(destination))

        # Written to a temporary name and renamed on success, so an interrupted
        # download can never be mistaken for a complete one on the next run.
        partial = destination.with_suffix(destination.suffix + ".partial")
        try:
            with httpx.stream(
                "GET",
                url,
                headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
                timeout=httpx.Timeout(30.0, read=300.0),
                follow_redirects=True,
            ) as response:
                if response.status_code == 403:
                    raise UpstreamError(
                        "The SEC refused the request. This almost always means the "
                        "User-Agent header is missing or does not carry a real contact "
                        "address. Check SEC_USER_AGENT."
                    )
                if response.status_code == 429:
                    raise UpstreamError(
                        "The SEC rate-limited the request. Lower SEC_REQUESTS_PER_SECOND."
                    )
                response.raise_for_status()

                with partial.open("wb") as handle:
                    for block in response.iter_bytes(chunk_size=1 << 16):
                        handle.write(block)
        except httpx.HTTPError as exc:
            partial.unlink(missing_ok=True)
            raise UpstreamError(f"Download failed for {url}: {exc}") from exc

        partial.replace(destination)
        log.info("download_complete", url=url, bytes=destination.stat().st_size)
        return destination

    def download_quarter(self, year: int, quarter: int, data_dir: Path) -> Path:
        """Download one DERA quarterly archive, for example 2023 Q1."""
        if quarter not in (1, 2, 3, 4):
            raise ValueError(f"quarter must be 1-4, got {quarter}")
        name = f"{year}q{quarter}.zip"
        return self.download(f"{DERA_BASE_URL}/{name}", data_dir / "sec_dera" / name)
