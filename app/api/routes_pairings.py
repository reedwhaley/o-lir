from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.config import get_settings
from app.schemas.pairing_api import (
    LinkLightbringerMatchRequest,
    LinkLightbringerMatchResponse,
    PairingLookupResponse,
    ReportLightbringerResultRequest,
    ReportLightbringerResultResponse,
)
from app.services.pairing_service import PairingService

router = APIRouter(prefix="/pairings", tags=["pairings"])


def require_internal_auth(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected = f"Bearer {settings.olir_internal_api_token}"
    if authorization != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@router.get(
    "/by-thread/{thread_id}",
    response_model=PairingLookupResponse,
    dependencies=[Depends(require_internal_auth)],
)
def get_pairing_by_thread(thread_id: str):
    service = PairingService()
    pairing = service.get_pairing_by_thread_id(thread_id)
    if pairing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pairing not found")
    return service.build_lookup_response(pairing)


@router.post(
    "/{pairing_id}/link-lightbringer-match",
    response_model=LinkLightbringerMatchResponse,
    dependencies=[Depends(require_internal_auth)],
)
def link_lightbringer_match(pairing_id: str, payload: LinkLightbringerMatchRequest):
    service = PairingService()
    try:
        pairing = service.link_lightbringer_match(
            pairing_id=pairing_id,
            lightbringer_match_id=payload.lightbringer_match_id,
            scheduled_start_at_utc=payload.start_at_utc,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return LinkLightbringerMatchResponse(
        pairing_id=pairing.id,
        status=pairing.status,
        lightbringer_match_id=pairing.lightbringer_match_id or payload.lightbringer_match_id,
        scheduled_start_at_utc=payload.start_at_utc,
    )


@router.post(
    "/report-lightbringer-result",
    response_model=ReportLightbringerResultResponse,
    dependencies=[Depends(require_internal_auth)],
)
def report_lightbringer_result(payload: ReportLightbringerResultRequest):
    service = PairingService()
    try:
        pairing = service.record_lightbringer_result(payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ReportLightbringerResultResponse(
        pairing_id=pairing.id,
        status=pairing.status,
        lightbringer_match_id=payload.lightbringer_match_id,
        winner_entrant_id=pairing.winner_entrant_id,
    )
