from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select

from app.db.session import session_scope
from app.models.entrant import Entrant
from app.models.pairing import Pairing
from app.models.tournament import Tournament


@dataclass
class StandingRow:
    entrant_id: str
    display_name: str
    seed: int | None
    match_points: int
    buchholz: int
    sonneborn_berger: int


class SwissService:
    def _new_id(self) -> str:
        return secrets.token_hex(16)

    def _detach_many(self, session, objs: Iterable):
        items = list(objs)
        for obj in items:
            session.expunge(obj)
        return items

    def _get_active_entrants(self, session, tournament_id: str) -> list[Entrant]:
        entrants = list(
            session.execute(
                select(Entrant).where(
                    Entrant.tournament_id == str(tournament_id),
                    Entrant.is_active.is_(True),
                )
            ).scalars().all()
        )
        return entrants

    def _get_pairings(self, session, tournament_id: str) -> list[Pairing]:
        return list(
            session.execute(
                select(Pairing).where(Pairing.tournament_id == str(tournament_id))
            ).scalars().all()
        )

    def _completed_pairings(self, pairings: list[Pairing]) -> list[Pairing]:
        done: list[Pairing] = []
        for pairing in pairings:
            status = str(getattr(pairing, "status", "") or "").lower()
            winner_id = getattr(pairing, "winner_entrant_id", None)
            if status == "completed" and winner_id:
                done.append(pairing)
        return done

    def compute_standings(self, tournament_id: str) -> list[StandingRow]:
        with session_scope() as session:
            tournament = session.get(Tournament, tournament_id)
            if not tournament:
                raise LookupError("Tournament not found.")

            entrants = self._get_active_entrants(session, tournament_id)
            if not entrants:
                return []

            pairings = self._get_pairings(session, tournament_id)
            completed = self._completed_pairings(pairings)

            points: dict[str, int] = {str(e.id): 0 for e in entrants}
            opponents: dict[str, list[str]] = {str(e.id): [] for e in entrants}
            wins_over: dict[str, list[str]] = {str(e.id): [] for e in entrants}

            for pairing in completed:
                entrant1_id = str(getattr(pairing, "entrant1_id", "") or "")
                entrant2_id = str(getattr(pairing, "entrant2_id", "") or "")
                winner_id = str(getattr(pairing, "winner_entrant_id", "") or "")

                if entrant1_id and entrant2_id:
                    opponents.setdefault(entrant1_id, []).append(entrant2_id)
                    opponents.setdefault(entrant2_id, []).append(entrant1_id)

                if entrant1_id and not entrant2_id:
                    points[entrant1_id] = points.get(entrant1_id, 0) + 3
                    continue

                if not entrant1_id or not entrant2_id or not winner_id:
                    continue

                loser_id = entrant2_id if winner_id == entrant1_id else entrant1_id
                points[winner_id] = points.get(winner_id, 0) + 3
                wins_over.setdefault(winner_id, []).append(loser_id)

            buchholz: dict[str, int] = {}
            sonneborn_berger: dict[str, int] = {}

            for entrant in entrants:
                entrant_id = str(entrant.id)
                buchholz[entrant_id] = sum(points.get(opp_id, 0) for opp_id in opponents.get(entrant_id, []))
                sonneborn_berger[entrant_id] = sum(points.get(opp_id, 0) for opp_id in wins_over.get(entrant_id, []))

            rows = [
                StandingRow(
                    entrant_id=str(entrant.id),
                    display_name=str(entrant.display_name),
                    seed=getattr(entrant, "seed", None),
                    match_points=points.get(str(entrant.id), 0),
                    buchholz=buchholz.get(str(entrant.id), 0),
                    sonneborn_berger=sonneborn_berger.get(str(entrant.id), 0),
                )
                for entrant in entrants
            ]

            rows.sort(
                key=lambda row: (
                    -row.match_points,
                    -row.buchholz,
                    -row.sonneborn_berger,
                    row.seed if row.seed is not None else 999999,
                    row.display_name.lower(),
                )
            )
            return rows

    def _opponent_history(self, pairings: list[Pairing]) -> dict[str, set[str]]:
        history: dict[str, set[str]] = {}

        for pairing in pairings:
            entrant1_id = str(getattr(pairing, "entrant1_id", "") or "")
            entrant2_id = str(getattr(pairing, "entrant2_id", "") or "")

            if not entrant1_id or not entrant2_id:
                continue

            history.setdefault(entrant1_id, set()).add(entrant2_id)
            history.setdefault(entrant2_id, set()).add(entrant1_id)

        return history

    def _next_round_number(self, pairings: list[Pairing]) -> int:
        if not pairings:
            return 1
        return max(int(getattr(pairing, "round_number", 0) or 0) for pairing in pairings) + 1

    def _pair_standings(self, rows: list[StandingRow], history: dict[str, set[str]]) -> list[tuple[str, str | None]]:
        remaining = [row.entrant_id for row in rows]
        pairings: list[tuple[str, str | None]] = []

        while remaining:
            left = remaining.pop(0)

            if not remaining:
                pairings.append((left, None))
                break

            partner_index = None
            for idx, candidate in enumerate(remaining):
                previous = history.get(left, set())
                if candidate not in previous:
                    partner_index = idx
                    break

            if partner_index is None:
                partner_index = 0

            right = remaining.pop(partner_index)
            pairings.append((left, right))

        return pairings

    def generate_next_round_pairings(self, tournament_id: str) -> list[Pairing]:
        with session_scope() as session:
            tournament = session.get(Tournament, tournament_id)
            if not tournament:
                raise LookupError("Tournament not found.")

            entrants = self._get_active_entrants(session, tournament_id)
            if len(entrants) < 2:
                raise ValueError("At least two active entrants are required to generate a swiss round.")

            all_pairings = self._get_pairings(session, tournament_id)
            unresolved = [
                pairing
                for pairing in all_pairings
                if str(getattr(pairing, "status", "") or "").lower() not in {"completed", "cancelled"}
            ]
            if unresolved:
                raise ValueError("Cannot generate a new swiss round while unresolved matches still exist.")

            standings = self.compute_standings(tournament_id)
            history = self._opponent_history(all_pairings)
            round_number = self._next_round_number(all_pairings)
            round_pairs = self._pair_standings(standings, history)

            created: list[Pairing] = []
            for entrant1_id, entrant2_id in round_pairs:
                pairing = Pairing(
                    id=self._new_id(),
                    tournament_id=str(tournament_id),
                    entrant1_id=str(entrant1_id),
                    entrant2_id=str(entrant2_id) if entrant2_id else None,
                    round_number=round_number,
                    phase_type="swiss",
                    status="ready",
                    winner_entrant_id=str(entrant1_id) if entrant2_id is None else None,
                )
                session.add(pairing)
                created.append(pairing)

            session.flush()

            for pairing in created:
                if getattr(pairing, "entrant2_id", None) is None:
                    pairing.status = "completed"

            session.flush()
            return self._detach_many(session, created)