from __future__ import annotations

from sqlalchemy import select

from app.db.session import session_scope
from app.models.speedgaming_profile import SpeedGamingProfile


class SpeedGamingProfileService:
    def upsert_profile(
        self,
        *,
        discord_id: str,
        discord_username_snapshot: str,
        sg_display_name: str,
        sg_twitch_name: str,
    ) -> SpeedGamingProfile:
        with session_scope() as session:
            row = session.get(SpeedGamingProfile, str(discord_id))

            if row is None:
                row = SpeedGamingProfile(
                    discord_id=str(discord_id),
                    discord_username_snapshot=str(discord_username_snapshot),
                    sg_display_name=str(sg_display_name),
                    sg_twitch_name=str(sg_twitch_name),
                )
                session.add(row)
            else:
                row.discord_username_snapshot = str(discord_username_snapshot)
                row.sg_display_name = str(sg_display_name)
                row.sg_twitch_name = str(sg_twitch_name)

            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

    def get_profile_by_discord_id(self, discord_id: str) -> SpeedGamingProfile | None:
        with session_scope() as session:
            row = session.get(SpeedGamingProfile, str(discord_id))
            if row is not None:
                session.expunge(row)
            return row

    def clear_profile_by_discord_id(self, discord_id: str) -> bool:
        with session_scope() as session:
            row = session.get(SpeedGamingProfile, str(discord_id))
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True

    def list_profiles(self) -> list[SpeedGamingProfile]:
        with session_scope() as session:
            rows = list(
                session.execute(
                    select(SpeedGamingProfile).order_by(SpeedGamingProfile.sg_display_name.asc())
                ).scalars().all()
            )
            for row in rows:
                session.expunge(row)
            return rows