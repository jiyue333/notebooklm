from __future__ import annotations

from pydantic import BaseModel, Field


class SettingsUpdateRequest(BaseModel):
    outputLanguage: str | None = Field(default=None, max_length=64)
    themeColor: str | None = Field(default=None, max_length=64)
    colorMode: str | None = Field(default=None, max_length=32)
    useDefaultModelConfig: bool | None = None
    modelProvider: str | None = Field(default=None, max_length=64)
    modelName: str | None = Field(default=None, max_length=128)
    apiUrl: str | None = Field(default=None, max_length=1024)
    apiKey: str | None = None
    clearApiKey: bool | None = None
    useDefaultSearchConfig: bool | None = None
    searchProvider: str | None = Field(default=None, max_length=32)
    searchApiKey: str | None = None
    clearSearchApiKey: bool | None = None
    preferredSites: list[str] | None = None
    useDefaultEmbeddingConfig: bool | None = None
    embeddingProvider: str | None = Field(default=None, max_length=64)
    embeddingModel: str | None = Field(default=None, max_length=128)
    embeddingApiUrl: str | None = Field(default=None, max_length=1024)
    embeddingApiKey: str | None = None
    clearEmbeddingApiKey: bool | None = None
    confirmEmbeddingReindex: bool | None = None


class ProfileUpdateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)


class PasswordUpdateRequest(BaseModel):
    oldPassword: str = Field(min_length=1, max_length=255)
    newPassword: str = Field(min_length=1, max_length=255)
    confirmPassword: str = Field(min_length=1, max_length=255)
