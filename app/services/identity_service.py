from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import select

from app.db.session import session_scope
from app.models.entrant_identity import EntrantIdentity


@dataclass
class IdentityRow:
    entrant_id: str
    tournament_id: str
    member_slot: int
    discord_id: str
    discord_username_snapshot: str
    submitted_display_name: str
    twitch_name: str
    is_captain: bool


class IdentityService:
    def _new_id(self) -> str:
        return secrets.token_hex(16)

    def upsert_single_identity(
        self,
        *,
        entrant_id: str,
        tournament_id: str,
        discord_id: str,
        discord_username_snapshot: str,
        submitted_display_name: str,
        twitch_name: str,
    ) -> EntrantIdentity:
        with session_scope() as session:
            row = session.execute(
                select(EntrantIdentity).where(
                    EntrantIdentity.entrant_id == str(entrant_id),
                    EntrantIdentity.member_slot == 1,
                )
            ).scalar_one_or_none()

            if row is None:
                row = EntrantIdentity(
                    id=self._new_id(),
                    entrant_id=str(entrant_id),
                    tournament_id=str(tournament_id),
                    member_slot=1,
                    discord_id=str(discord_id),
                    discord_username_snapshot=str(discord_username_snapshot),
                    submitted_display_name=str(submitted_display_name),
                    twitch_name=str(twitch_name),
                    is_captain=True,
                )
                session.add(row)
            else:
                row.discord_id = str(discord_id)
                row.discord_username_snapshot = str(discord_username_snapshot)
                row.submitted_display_name = str(submitted_display_name)
                row.twitch_name = str(twitch_name)
                row.is_captain = True

            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

    def replace_team_identities(
        self,
        *,
        entrant_id: str,
        tournament_id: str,
        members: list[IdentityRow],
    ) -> list[EntrantIdentity]:
        if len(members) != 2:
            raise ValueError("Team identity replacement expects exactly two members.")

        with session_scope() as session:
            existing = list(
                session.execute(
                    select(EntrantIdentity).where(EntrantIdentity.entrant_id == str(entrant_id))
                ).scalars().all()
            )
            for row in existing:
                session.delete(row)
            session.flush()

            created: list[EntrantIdentity] = []
            for member in members:
                row = EntrantIdentity(
                    id=self._new_id(),
                    entrant_id=str(member.entrant_id),
                    tournament_id=str(member.tournament_id),
                    member_slot=int(member.member_slot),
                    discord_id=str(member.discord_id),
                    discord_username_snapshot=str(member.discord_username_snapshot),
                    submitted_display_name=str(member.submitted_display_name),
                    twitch_name=str(member.twitch_name),
                    is_captain=bool(member.is_captain),
                )
                session.add(row)
                created.append(row)

            session.flush()
            for row in created:
                session.refresh(row)
                session.expunge(row)
            return created

    def list_identities_for_entrant(self, entrant_id: str) -> list[EntrantIdentity]:
        with session_scope() as session:
            rows = list(
                session.execute(
                    select(EntrantIdentity)
                    .where(EntrantIdentity.entrant_id == str(entrant_id))
                    .order_by(EntrantIdentity.member_slot.asc())
                ).scalars().all()
            )
            for row in rows:
                session.expunge(row)
            return rows