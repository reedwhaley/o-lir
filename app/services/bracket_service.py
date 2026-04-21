from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import select

from app.db.session import session_scope
from app.models.entrant import Entrant
from app.models.pairing import Pairing
from app.services.swiss_service import SwissService


@dataclass
class TopCutSeed:
    entrant_id: str
    display_name: str
    cut_seed: int


class BracketService:
    def _generate_pairing_id(self) -> str:
        return f'PAIR-{secrets.token_hex(3).upper()}'

    def compute_top_cut(self, tournament_id: str, cut_size: int = 8) -> list[TopCutSeed]:
        standings = SwissService().compute_standings(tournament_id)
        top = standings[:cut_size]
        return [TopCutSeed(entrant_id=row.entrant_id, display_name=row.display_name, cut_seed=index) for index, row in enumerate(top, start=1)]

    def create_top8_winners_round1(self, tournament_id: str) -> list[Pairing]:
        top = self.compute_top_cut(tournament_id, 8)
        if len(top) < 8:
            raise ValueError('Top 8 cannot be created because fewer than 8 entrants are available after swiss.')
        lookup = {seed.cut_seed: seed for seed in top}
        matchups = [(1, 8), (4, 5), (2, 7), (3, 6)]
        created: list[Pairing] = []
        with session_scope() as session:
            existing = list(session.execute(select(Pairing).where(Pairing.tournament_id == tournament_id, Pairing.stage == 'top_cut')).scalars().all())
            if existing:
                raise ValueError('Top cut pairings already exist for this tournament.')
            for order, (left_seed, right_seed) in enumerate(matchups, start=1):
                pairing = Pairing(
                    id=self._generate_pairing_id(),
                    tournament_id=tournament_id,
                    stage='top_cut',
                    bracket_side='winners',
                    round_number=1,
                    order_in_round=order,
                    entrant1_id=lookup[left_seed].entrant_id,
                    entrant2_id=lookup[right_seed].entrant_id,
                    status='open',
                )
                session.add(pairing)
                created.append(pairing)
            session.flush()
            for pairing in created:
                session.refresh(pairing)
            return created
