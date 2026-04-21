from __future__ import annotations

import secrets

from sqlalchemy import select

from app.db.session import session_scope
from app.models.entrant import Entrant
from app.models.entrant_member import EntrantMember
from app.models.tournament import Tournament
from app.models.speedgaming_profile import SpeedGamingProfile


class TournamentService:
    def _new_id(self) -> str:
        return secrets.token_hex(16)

    def _detach(self, session, obj):
        if obj is not None:
            session.expunge(obj)
        return obj

    def _detach_many(self, session, objs):
        for obj in objs:
            session.expunge(obj)
        return objs

    def create_tournament(
        self,
        *,
        guild_id: str,
        name: str,
        category_slug: str,
        created_by_discord_id: str,
        entrant_type: str = "player",
        seeding_race_count: int = 1,
        seeding_method: str = "baja_special",
        seeding_drop_count: int = 1,
        standings_tiebreak_method: str = "buchholz_then_sonneborn_berger",
        swiss_round_count: int = 5,
        top_cut_size: int = 8,
    ) -> Tournament:
        with session_scope() as session:
            if int(seeding_drop_count) < 0:
                raise ValueError("Seeding drop count cannot be negative.")

            if int(seeding_drop_count) >= int(seeding_race_count):
                raise ValueError("Seeding drop count must be lower than the total number of seeding races.")

            tournament = Tournament(
                id=self._new_id(),
                guild_id=str(guild_id),
                name=name.strip(),
                category_slug=category_slug.strip(),
                entrant_type=entrant_type.strip().lower(),
                seeding_race_count=int(seeding_race_count),
                seeding_method=str(seeding_method).strip().lower(),
                seeding_drop_count=int(seeding_drop_count),
                standings_tiebreak_method=str(standings_tiebreak_method).strip().lower(),
                swiss_round_count=int(swiss_round_count),
                top_cut_size=int(top_cut_size),
                created_by_discord_id=str(created_by_discord_id),
                signup_open=True,
                status="registration_open",
            )
            session.add(tournament)
            session.flush()
            session.refresh(tournament)
            return self._detach(session, tournament)

    def get_tournament(self, tournament_id: str) -> Tournament | None:
        with session_scope() as session:
            tournament = session.get(Tournament, tournament_id)
            if tournament is None:
                return None
            return self._detach(session, tournament)

    def get_entrant(self, entrant_id: str) -> Entrant | None:
        with session_scope() as session:
            entrant = session.get(Entrant, entrant_id)
            if entrant is None:
                return None
            return self._detach(session, entrant)

    def get_entrant_members(self, entrant_id: str) -> list[EntrantMember]:
        with session_scope() as session:
            members = list(
                session.execute(
                    select(EntrantMember).where(EntrantMember.entrant_id == entrant_id)
                ).scalars().all()
            )
            return self._detach_many(session, members)

    def list_entrants(self, tournament_id: str, *, active_only: bool = True) -> list[Entrant]:
        with session_scope() as session:
            stmt = select(Entrant).where(Entrant.tournament_id == tournament_id)
            if active_only:
                stmt = stmt.where(Entrant.is_active.is_(True))
            stmt = stmt.order_by(Entrant.seed.asc().nullslast(), Entrant.display_name.asc())
            entrants = list(session.execute(stmt).scalars().all())
            return self._detach_many(session, entrants)

    def _user_has_active_entry(self, session, tournament_id: str, discord_id: str) -> bool:
        direct = session.execute(
            select(Entrant).where(
                Entrant.tournament_id == tournament_id,
                Entrant.is_active.is_(True),
                Entrant.discord_id == str(discord_id),
            )
        ).scalar_one_or_none()
        if direct:
            return True

        team_entry = session.execute(
            select(Entrant).join(
                EntrantMember,
                EntrantMember.entrant_id == Entrant.id,
            ).where(
                Entrant.tournament_id == tournament_id,
                Entrant.is_active.is_(True),
                EntrantMember.discord_id == str(discord_id),
            )
        ).scalar_one_or_none()

        return team_entry is not None

    def _find_active_entry_for_user(self, session, tournament_id: str, discord_id: str) -> Entrant | None:
        direct = session.execute(
            select(Entrant).where(
                Entrant.tournament_id == tournament_id,
                Entrant.is_active.is_(True),
                Entrant.discord_id == str(discord_id),
            )
        ).scalar_one_or_none()
        if direct:
            return direct

        return session.execute(
            select(Entrant).join(
                EntrantMember,
                EntrantMember.entrant_id == Entrant.id,
            ).where(
                Entrant.tournament_id == tournament_id,
                Entrant.is_active.is_(True),
                EntrantMember.discord_id == str(discord_id),
            )
        ).scalar_one_or_none()


    def _has_speedgaming_profile(self, session, discord_id: str) -> bool:
        row = session.get(SpeedGamingProfile, str(discord_id))
        return row is not None

    def can_user_submit_for_entrant(self, entrant_id: str, user_id: str) -> bool:
        with session_scope() as session:
            entrant = session.get(Entrant, entrant_id)
            if not entrant or not entrant.is_active:
                return False

            if entrant.discord_id and str(entrant.discord_id) == str(user_id):
                return True

            if entrant.captain_discord_id and str(entrant.captain_discord_id) == str(user_id):
                return True

            member = session.execute(
                select(EntrantMember).where(
                    EntrantMember.entrant_id == entrant.id,
                    EntrantMember.discord_id == str(user_id),
                )
            ).scalar_one_or_none()

            return member is not None

    def add_entrant(
        self,
        *,
        tournament_id: str,
        display_name: str,
        discord_id: str | None = None,
    ) -> Entrant:
        with session_scope() as session:
            tournament = session.get(Tournament, tournament_id)
            if not tournament:
                raise ValueError("Tournament not found.")

            if discord_id and self._user_has_active_entry(session, tournament_id, str(discord_id)):
                raise ValueError("That user is already on an active entrant in this tournament.")
            if discord_id and not self._has_speedgaming_profile(session, str(discord_id)):
                raise ValueError("That user must complete /tournament setup speedgaming first.")

            entrant = Entrant(
                id=self._new_id(),
                tournament_id=tournament_id,
                display_name=display_name.strip(),
                discord_id=str(discord_id) if discord_id else None,
                captain_discord_id=str(discord_id) if discord_id else None,
                is_team=False,
                is_active=True,
            )
            session.add(entrant)
            session.flush()
            session.refresh(entrant)
            return self._detach(session, entrant)

    def add_team(
        self,
        *,
        tournament_id: str,
        display_name: str,
        members: list[tuple[str, str]],
        captain_discord_id: str | None = None,
    ) -> Entrant:
        if len(members) != 2:
            raise ValueError("Teams must have exactly two members.")

        member_ids = [str(member_id) for member_id, _ in members]
        if member_ids[0] == member_ids[1]:
            raise ValueError("A team cannot contain the same Discord user twice.")

        with session_scope() as session:
            tournament = session.get(Tournament, tournament_id)
            if not tournament:
                raise ValueError("Tournament not found.")

            for member_id in member_ids:
                if self._user_has_active_entry(session, tournament_id, member_id):
                    raise ValueError("One of those users is already on an active entrant in this tournament.")
                if not self._has_speedgaming_profile(session, member_id):
                    raise ValueError("One of those users must complete /tournament setup speedgaming first.")

            captain_id = str(captain_discord_id) if captain_discord_id else member_ids[0]

            entrant = Entrant(
                id=self._new_id(),
                tournament_id=tournament_id,
                display_name=display_name.strip(),
                discord_id=None,
                captain_discord_id=captain_id,
                is_team=True,
                is_active=True,
            )
            session.add(entrant)
            session.flush()

            for sort_order, (member_id, member_name) in enumerate(members, start=1):
                session.add(
                    EntrantMember(
                        id=self._new_id(),
                        entrant_id=entrant.id,
                        discord_id=str(member_id),
                        display_name=member_name,
                        sort_order=sort_order,
                    )
                )

            session.flush()
            session.refresh(entrant)
            return self._detach(session, entrant)

    def signup_player(
        self,
        *,
        tournament_id: str,
        discord_id: str,
        display_name: str,
    ) -> Entrant:
        with session_scope() as session:
            tournament = session.get(Tournament, tournament_id)
            if not tournament:
                raise ValueError("Tournament not found.")
            if not tournament.signup_open:
                raise ValueError("Signup is closed for this tournament.")
            if tournament.entrant_type != "player":
                raise ValueError("This tournament is not configured for singles signup.")
            if self._user_has_active_entry(session, tournament_id, str(discord_id)):
                raise ValueError("You are already signed up in this tournament.")
            if not self._has_speedgaming_profile(session, str(discord_id)):
                raise ValueError("You must complete /tournament setup speedgaming before signing up.")

            entrant = Entrant(
                id=self._new_id(),
                tournament_id=tournament_id,
                display_name=display_name.strip(),
                discord_id=str(discord_id),
                captain_discord_id=str(discord_id),
                is_team=False,
                is_active=True,
            )
            session.add(entrant)
            session.flush()
            session.refresh(entrant)
            return self._detach(session, entrant)

    def signup_team(
        self,
        *,
        tournament_id: str,
        team_name: str,
        captain_discord_id: str,
        member1_id: str,
        member1_name: str,
        member2_id: str,
        member2_name: str,
    ) -> Entrant:
        if str(member1_id) == str(member2_id):
            raise ValueError("A team cannot contain the same Discord user twice.")

        if str(captain_discord_id) not in {str(member1_id), str(member2_id)}:
            raise ValueError("The user creating the team must be one of the two team members.")

        with session_scope() as session:
            tournament = session.get(Tournament, tournament_id)
            if not tournament:
                raise ValueError("Tournament not found.")
            if not tournament.signup_open:
                raise ValueError("Signup is closed for this tournament.")
            if tournament.entrant_type != "team":
                raise ValueError("This tournament is not configured for team signup.")

            if self._user_has_active_entry(session, tournament_id, str(member1_id)):
                raise ValueError("The first team member is already signed up in this tournament.")
            if self._user_has_active_entry(session, tournament_id, str(member2_id)):
                raise ValueError("The second team member is already signed up in this tournament.")
            if not self._has_speedgaming_profile(session, str(member1_id)):
                raise ValueError("The first team member must complete /tournament setup speedgaming before signup.")
            if not self._has_speedgaming_profile(session, str(member2_id)):
                raise ValueError("The second team member must complete /tournament setup speedgaming before signup.")

            entrant = Entrant(
                id=self._new_id(),
                tournament_id=tournament_id,
                display_name=team_name.strip(),
                discord_id=None,
                captain_discord_id=str(captain_discord_id),
                is_team=True,
                is_active=True,
            )
            session.add(entrant)
            session.flush()

            session.add(
                EntrantMember(
                    id=self._new_id(),
                    entrant_id=entrant.id,
                    discord_id=str(member1_id),
                    display_name=member1_name,
                    sort_order=1,
                )
            )
            session.add(
                EntrantMember(
                    id=self._new_id(),
                    entrant_id=entrant.id,
                    discord_id=str(member2_id),
                    display_name=member2_name,
                    sort_order=2,
                )
            )

            session.flush()
            session.refresh(entrant)
            return self._detach(session, entrant)

    def withdraw_user_entry(self, *, tournament_id: str, discord_id: str) -> Entrant:
        with session_scope() as session:
            tournament = session.get(Tournament, tournament_id)
            if not tournament:
                raise ValueError("Tournament not found.")
            if not tournament.signup_open:
                raise ValueError("Signup is closed. Public withdrawal is no longer available.")

            entrant = self._find_active_entry_for_user(session, tournament_id, str(discord_id))
            if not entrant:
                raise ValueError("You do not have an active entry in this tournament.")

            entrant.is_active = False
            session.flush()
            session.refresh(entrant)
            return self._detach(session, entrant)

    def remove_entrant(self, *, entrant_id: str) -> Entrant:
        with session_scope() as session:
            entrant = session.get(Entrant, entrant_id)
            if not entrant:
                raise ValueError("Entrant not found.")

            entrant.is_active = False
            session.flush()
            session.refresh(entrant)
            return self._detach(session, entrant)

    def find_entry_for_user(self, *, tournament_id: str, discord_id: str) -> Entrant | None:
        with session_scope() as session:
            entrant = self._find_active_entry_for_user(session, tournament_id, str(discord_id))
            if entrant is None:
                return None
            return self._detach(session, entrant)