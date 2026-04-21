from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class PairingLookupResponse(BaseModel):
    pairing_id: str
    tournament_id: str
    round_number: int
    stage: str
    status: str
    entrant1_name: str
    entrant2_name: str
    is_team_match: bool = False
    lightbringer_match_id: str | None = None


class LinkLightbringerMatchRequest(BaseModel):
    lightbringer_match_id: str
    start_at_utc: datetime
    category_slug: str
    subcategory: str
    match_name: str


class LinkLightbringerMatchResponse(BaseModel):
    pairing_id: str
    status: str
    lightbringer_match_id: str
    scheduled_start_at_utc: datetime


class ResultSidePayload(BaseModel):
    name: str
    finish_time_seconds: float | None = None
    finish_time_text: str | None = None
    placement: int | None = None
    status: str | None = None
    member_names: list[str] | None = None


class ReportLightbringerResultRequest(BaseModel):
    lightbringer_match_id: str
    race_room_url: str | None = None
    completed_at_utc: datetime | None = None
    result_source: str = "lightbringer"
    status: str = "finished"
    winner_side: str | None = None
    team1: ResultSidePayload
    team2: ResultSidePayload
    raw_result_json: dict[str, Any] | None = None


class ReportLightbringerResultResponse(BaseModel):
    pairing_id: str
    status: str
    lightbringer_match_id: str
    winner_entrant_id: str | None = None
