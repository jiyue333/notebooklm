from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.response import success_response
from app.modules.notebooks.schemas import NotebookCreateRequest, NotebookUpdateRequest
from app.modules.notebooks.service import (
    create_notebook,
    delete_notebook,
    get_notebook_detail,
    list_notebooks,
    update_notebook,
)

router = APIRouter(prefix="/notebooks", tags=["notebooks"])


@router.get("")
async def list_notebooks_endpoint(
    query: str = Query(default=""),
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    items = await list_notebooks(session, user_id=current_user.id, query=query.strip() or None)
    return success_response(items=items)


@router.post("")
async def create_notebook_endpoint(
    payload: NotebookCreateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await create_notebook(
        session,
        user_id=current_user.id,
        title=payload.title,
        emoji=payload.emoji,
        color=payload.color,
    )
    return success_response(item=item)


@router.get("/{notebook_id}")
async def get_notebook_detail_endpoint(
    notebook_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
    return success_response(item=item)


@router.patch("/{notebook_id}")
async def update_notebook_endpoint(
    notebook_id: str,
    payload: NotebookUpdateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await update_notebook(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        title=payload.title,
        emoji=payload.emoji,
        color=payload.color,
    )
    return success_response(item=item)


@router.delete("/{notebook_id}")
async def delete_notebook_endpoint(
    notebook_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    await delete_notebook(session, user_id=current_user.id, notebook_id=notebook_id)
    return {"success": True}
