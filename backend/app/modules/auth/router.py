from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep, raw_token_dep
from app.api.response import success_response
from app.modules.auth.schemas import LoginRequest
from app.modules.auth.service import build_user_view, login, logout

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login_endpoint(
    payload: LoginRequest,
    session: AsyncSession = Depends(db_session_dep),
):
    token, user = await login(session, username=payload.username, password=payload.password)
    return {
        "success": True,
        "token": token,
        "user": user.model_dump(),
    }


@router.post("/logout")
async def logout_endpoint(
    token: str = Depends(raw_token_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    await logout(session, token)
    return {"success": True}


@router.get("/me")
async def me_endpoint(current_user=Depends(current_user_dep)):
    return {
        "success": True,
        "user": build_user_view(current_user).model_dump(),
    }
