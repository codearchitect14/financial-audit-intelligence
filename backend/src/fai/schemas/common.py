"""Shared request and response shapes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, Field

# An upper bound on page size is a denial-of-service control, not a style
# choice: without it a caller can request the entire table in one query.
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


class PageParams(BaseModel):
    """Offset pagination parameters.

    Offset rather than cursor pagination: the dashboard needs a total count and
    jump-to-page, and the page depths involved here are shallow enough that the
    usual deep-offset cost does not bite.
    """

    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE
    offset: Annotated[int, Query(ge=0)] = 0


class Page[T](BaseModel):
    """One page of results plus enough metadata to render a pager."""

    items: list[T]
    total: int = Field(description="Total rows matching the filter, ignoring pagination.")
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class MessageResponse(BaseModel):
    message: str
