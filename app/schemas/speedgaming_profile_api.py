from __future__ import annotations

from pydantic import BaseModel


class SpeedGamingProfileResponse(BaseModel):
    discord_id: str
    discord_username_snapshot: str
    sg_display_name: str
    sg_twitch_name: str