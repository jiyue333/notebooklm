from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.response import success_response
from app.modules.search.schemas import SearchSourcesRequest
from app.modules.search.service_search import get_search_session, start_search

router = APIRouter(tags=["search"])


@router.post("/notebooks/{notebook_id}/sources/search")
async def search_sources_endpoint(
    notebook_id: str,
    payload: SearchSourcesRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    result = await start_search(
        session,
        user=current_user,
        notebook_id=notebook_id,
        query=payload.query,
        mode=payload.mode,
        max_results=payload.maxResults,
        freshness_hours=payload.freshnessHours,
    )
    return success_response(
        item=result.get("item"),
        items=result.get("items"),
        message=result.get("message", ""),
        meta=result.get("meta"),
    )


@router.get("/notebooks/{notebook_id}/search-sessions/{search_session_id}")
async def get_search_session_endpoint(
    notebook_id: str,
    search_session_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    result = await get_search_session(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )
    return success_response(
        item=result.get("item"),
        items=result.get("items"),
        message=result.get("message", ""),
        meta=result.get("meta"),
    )
