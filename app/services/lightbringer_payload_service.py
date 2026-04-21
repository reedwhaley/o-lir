from __future__ import annotations

from dataclasses import asdict, dataclass

from app.services.identity_service import IdentityService


@dataclass
class OLirEntrantIdentityPayload:
    entrant_id: str
    member_slot: int
    discord_id: str
    discord_username_snapshot: str
    submitted_display_name: str
    twitch_name: str
    is_captain: bool


class LightbringerPayloadService:
    def __init__(self) -> None:
        self.identity_service = IdentityService()

    def entrant_payload(self, entrant_id: str) -> list[dict]:
        rows = self.identity_service.list_identities_for_entrant(entrant_id)

        payload: list[dict] = []
        for row in rows:
            payload.append(
                asdict(
                    OLirEntrantIdentityPayload(
                        entrant_id=str(row.entrant_id),
                        member_slot=int(row.member_slot),
                        discord_id=str(row.discord_id),
                        discord_username_snapshot=str(row.discord_username_snapshot),
                        submitted_display_name=str(row.submitted_display_name),
                        twitch_name=str(row.twitch_name),
                        is_captain=bool(row.is_captain),
                    )
                )
            )

        return payload