from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep, raw_token_dep
from app.modules.auth.schemas import EmailLookupRequest, LoginRequest, RegisterRequest
from app.modules.auth.service import build_user_view, login, lookup_email, logout, register

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


@router.post("/lookup-email")
async def lookup_email_endpoint(
    payload: EmailLookupRequest,
    session: AsyncSession = Depends(db_session_dep),
):
    exists = await lookup_email(session, email=payload.email)
    return {
        "success": True,
        "item": {
            "email": payload.email.strip().lower(),
            "exists": exists,
        },
    }


@router.post("/register")
async def register_endpoint(
    payload: RegisterRequest,
    session: AsyncSession = Depends(db_session_dep),
):
    token, user = await register(
        session,
        username=payload.username,
        email=payload.email,
        password=payload.password,
    )
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
