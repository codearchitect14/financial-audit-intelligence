"""Aggregate API router.

Routers are mounted here rather than on the app directly, so that the version
prefix is applied in exactly one place.
"""

from fastapi import APIRouter

from fai.api.v1 import (
    auth,
    documents,
    health,
    insights,
    reports,
    search,
    statements,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(statements.router)
api_router.include_router(documents.router)
api_router.include_router(search.router)
api_router.include_router(insights.router)
api_router.include_router(reports.router)
