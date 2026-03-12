from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.modules.settings.defaults import SETTINGS_FIELDS, SETTINGS_SCOPE_FIELDS
from app.infra.security.credential_crypto import CredentialCrypto

SETTINGS_SCOPE_FLAGS = {
    "model": "useDefaultModelConfig",
    "search": "useDefaultSearchConfig",
    "embedding": "useDefaultEmbeddingConfig",
}
SETTINGS_FIELD_TO_SCOPE = {
    field: scope
    for scope, fields in SETTINGS_SCOPE_FIELDS.items()
    for field in fields
}


@dataclass(frozen=True, slots=True)
class CredentialUpdateSpec:
    use_default_flag: str
    clear_flag: str
    payload_field: str
    ciphertext_attr: str
    last4_attr: str
    updated_at_attr: str


CREDENTIAL_UPDATE_SPECS = (
    CredentialUpdateSpec(
        use_default_flag="useDefaultModelConfig",
        clear_flag="clearApiKey",
        payload_field="apiKey",
        ciphertext_attr="llm_api_key_ciphertext",
        last4_attr="llm_api_key_last4",
        updated_at_attr="llm_api_key_updated_at",
    ),
    CredentialUpdateSpec(
        use_default_flag="useDefaultSearchConfig",
        clear_flag="clearSearchApiKey",
        payload_field="searchApiKey",
        ciphertext_attr="exa_api_key_ciphertext",
        last4_attr="exa_api_key_last4",
        updated_at_attr="exa_api_key_updated_at",
    ),
    CredentialUpdateSpec(
        use_default_flag="useDefaultEmbeddingConfig",
        clear_flag="clearEmbeddingApiKey",
        payload_field="embeddingApiKey",
        ciphertext_attr="embedding_api_key_ciphertext",
        last4_attr="embedding_api_key_last4",
        updated_at_attr="embedding_api_key_updated_at",
    ),
)


def merge_settings_payload(
    *,
    stored_settings: dict,
    payload: dict,
    default_settings: dict,
) -> tuple[dict, dict]:
    settings_json = {**stored_settings}
    for field in SETTINGS_FIELDS:
        if _should_skip_settings_field(field=field, payload=payload):
            continue
        if field in payload and payload[field] is not None:
            settings_json[field] = payload[field]

    for scope, fields in SETTINGS_SCOPE_FIELDS.items():
        if payload.get(SETTINGS_SCOPE_FLAGS[scope]):
            drop_settings_fields(settings_json, fields)

    return settings_json, {**default_settings, **settings_json}


def _should_skip_settings_field(*, field: str, payload: dict) -> bool:
    scope = SETTINGS_FIELD_TO_SCOPE.get(field)
    return bool(scope and payload.get(SETTINGS_SCOPE_FLAGS[scope]))


def drop_settings_fields(settings_json: dict, fields: tuple[str, ...]) -> None:
    for field in fields:
        settings_json.pop(field, None)


def apply_credential_updates(*, user, payload: dict, crypto, now: datetime) -> None:
    for spec in CREDENTIAL_UPDATE_SPECS:
        _apply_credential_update(
            user=user,
            payload=payload,
            crypto=crypto,
            now=now,
            spec=spec,
        )


def _apply_credential_update(*, user, payload: dict, crypto: CredentialCrypto, now: datetime, spec: CredentialUpdateSpec) -> None:
    if payload.get(spec.use_default_flag) or payload.get(spec.clear_flag):
        setattr(user, spec.ciphertext_attr, None)
        setattr(user, spec.last4_attr, None)
        setattr(user, spec.updated_at_attr, now)
        return

    if not payload.get(spec.payload_field):
        return

    api_key = payload[spec.payload_field].strip()
    setattr(user, spec.ciphertext_attr, crypto.encrypt(api_key))
    setattr(user, spec.last4_attr, api_key[-4:])
    setattr(user, spec.updated_at_attr, now)
