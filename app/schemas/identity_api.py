from __future__ import annotations

from pydantic import BaseModel


class EntrantIdentityPayload(BaseModel):
    entrant_id: str
    member_slot: int
    discord_id: str
    discord_username_snapshot: str
    submitted_display_name: str
    twitch_name: str
    is_captain: bool


class EntrantIdentityResponse(BaseModel):
    entrant_id: str
    identities: list[EntrantIdentityPayload]