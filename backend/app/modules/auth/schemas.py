from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class EmailLookupRequest(BaseModel):
    email: str = Field(min_length=1, max_length=255)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=255)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=1, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=255)
    newPassword: str = Field(min_length=8, max_length=255)
    confirmPassword: str = Field(min_length=8, max_length=255)


class OAuthStartRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)


class UserView(BaseModel):
    id: str
    name: str
    email: str
    avatar: str | None = None
