from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.response import success_response
from app.modules.auth.account_service import update_avatar, update_password, update_profile
from app.modules.settings.schemas import (
    ModelConnectionTestRequest,
    PasswordUpdateRequest,
    ProfileUpdateRequest,
    SettingsUpdateRequest,
)
from app.modules.settings.service import get_settings, test_model_connection, update_settings

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def get_settings_endpoint(current_user=Depends(current_user_dep)):
    item = await get_settings(current_user)
    return success_response(item=item)


@router.put("/settings")
async def update_settings_endpoint(
    payload: SettingsUpdateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await update_settings(
        session,
        user=current_user,
        payload=payload.model_dump(exclude_unset=True),
    )
    return success_response(item=item)


@router.post("/settings/model/test")
async def test_model_connection_endpoint(
    payload: ModelConnectionTestRequest,
    current_user=Depends(current_user_dep),
):
    item = await test_model_connection(user=current_user, payload=payload.model_dump(exclude_unset=True))
    return success_response(item=item)


@router.patch("/account/profile")
async def update_profile_endpoint(
    payload: ProfileUpdateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await update_profile(session, user=current_user, username=payload.username)
    if payload.avatarUrl is not None:
        item = await update_avatar(session, user=current_user, avatar_url=payload.avatarUrl)
    return success_response(item=item)


@router.post("/account/password")
async def update_password_endpoint(
    payload: PasswordUpdateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    await update_password(
        session,
        user=current_user,
        old_password=payload.oldPassword,
        new_password=payload.newPassword,
        confirm_password=payload.confirmPassword,
    )
    return {"success": True}
