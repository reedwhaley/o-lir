from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status

from app.config import get_settings
from app.schemas.speedgaming_profile_api import SpeedGamingProfileResponse
from app.services.speedgaming_profile_service import SpeedGamingProfileService

router = APIRouter(prefix="/speedgaming_profiles", tags=["speedgaming_profiles"])


def _require_internal_auth(authorization: str | None) -> None:
    settings = get_settings()
    expected = f"Bearer {settings.olir_internal_api_token}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


@router.get("/{discord_id}", response_model=SpeedGamingProfileResponse)
def get_speedgaming_profile(discord_id: str, authorization: str | None = Header(default=None)):
    _require_internal_auth(authorization)

    service = SpeedGamingProfileService()
    row = service.get_profile_by_discord_id(discord_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SpeedGaming profile not found.",
        )

    return SpeedGamingProfileResponse(
        discord_id=str(row.discord_id),
        discord_username_snapshot=str(row.discord_username_snapshot),
        sg_display_name=str(row.sg_display_name),
        sg_twitch_name=str(row.sg_twitch_name),
    )