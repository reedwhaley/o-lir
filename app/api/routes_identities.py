from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.config import get_settings
from app.schemas.identity_api import EntrantIdentityPayload, EntrantIdentityResponse
from app.services.lightbringer_payload_service import LightbringerPayloadService

router = APIRouter(prefix="/identities", tags=["identities"])


def require_internal_auth(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected = f"Bearer {settings.olir_internal_api_token}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


@router.get(
    "/entrant/{entrant_id}",
    response_model=EntrantIdentityResponse,
    dependencies=[Depends(require_internal_auth)],
)
def get_entrant_identities(entrant_id: str) -> EntrantIdentityResponse:
    service = LightbringerPayloadService()
    payload = service.entrant_payload(entrant_id)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No identities found for entrant.",
        )

    return EntrantIdentityResponse(
        entrant_id=str(entrant_id),
        identities=[EntrantIdentityPayload(**row) for row in payload],
    )