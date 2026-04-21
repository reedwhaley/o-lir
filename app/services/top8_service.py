from __future__ import annotations

import secrets
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entrant import Entrant
from app.models.entrant_member import EntrantMember
from app.models.pairing import Pairing
from app.models.tournament import Tournament


class Top8Service:
    def _new_id(self) -> str:
        return secrets.token_hex(16)

    def _make_pairing(
        self,
        session: Session,
        *,
        tournament_id: str,
        round_number: int,
        pairing_code: str,
        phase_type: str,
        bracket_side: str | None = None,
        bracket_round: int | None = None,
        bracket_match_number: int | None = None,
        entrant1_id: str | None = None,
        entrant2_id: str | None = None,
        source_win_pairing_a_code: str | None = None,
        source_win_pairing_b_code: str | None = None,
        source_loss_pairing_a_code: str | None = None,
        source_loss_pairing_b_code: str | None = None,
    ) -> Pairing:
        status = "ready" if entrant1_id and entrant2_id else "pending"

        pairing = Pairing(
            id=self._new_id(),
            tournament_id=tournament_id,
            round_number=round_number,
            phase_type=phase_type,
            pairing_code=pairing_code,
            entrant1_id=entrant1_id,
            entrant2_id=entrant2_id,
            status=status,
            bracket_side=bracket_side,
            bracket_round=bracket_round,
            bracket_match_number=bracket_match_number,
            source_win_pairing_a_code=source_win_pairing_a_code,
            source_win_pairing_b_code=source_win_pairing_b_code,
            source_loss_pairing_a_code=source_loss_pairing_a_code,
            source_loss_pairing_b_code=source_loss_pairing_b_code,
        )
        session.add(pairing)
        session.flush()
        return pairing

    def _clone_entrant_for_child(
        self,
        session: Session,
        *,
        parent_entrant: Entrant,
        child_tournament_id: str,
        cut_seed: int,
    ) -> Entrant:
        child = Entrant(
            id=self._new_id(),
            tournament_id=child_tournament_id,
            display_name=parent_entrant.display_name,
            discord_id=parent_entrant.discord_id,
            is_team=parent_entrant.is_team,
            is_active=True,
            is_eliminated=False,
            seed=cut_seed,
            final_rank=None,
            final_seeding_score=parent_entrant.final_seeding_score,
            best_seed_race_score=parent_entrant.best_seed_race_score,
            second_best_seed_race_score=parent_entrant.second_best_seed_race_score,
            source_tournament_id=parent_entrant.tournament_id,
            source_swiss_rank=parent_entrant.final_rank,
            source_swiss_points=parent_entrant.match_points,
        )
        session.add(child)
        session.flush()

        if parent_entrant.is_team:
            members = session.execute(
                select(EntrantMember).where(EntrantMember.entrant_id == parent_entrant.id)
            ).scalars().all()

            for member in members:
                session.add(
                    EntrantMember(
                        id=self._new_id(),
                        entrant_id=child.id,
                        discord_id=member.discord_id,
                        display_name=member.display_name,
                    )
                )
            session.flush()

        return child

    def _ordered_cut_entrants(self, session: Session, tournament_id: str, cut_size: int) -> list[Entrant]:
        entrants = session.execute(
            select(Entrant).where(
                Entrant.tournament_id == tournament_id,
                Entrant.is_active.is_(True),
            )
        ).scalars().all()

        ranked = sorted(
            entrants,
            key=lambda e: (
                -(e.match_points or 0.0),
                -(e.buchholz or 0.0),
                -(e.sonneborn_berger or 0.0),
                e.seed or 999999,
                e.display_name.lower(),
            ),
        )

        return ranked[:cut_size]

    def promote_parent_to_top8(self, session: Session, parent_tournament_id: str) -> Tournament:
        parent = session.get(Tournament, parent_tournament_id)
        if not parent:
            raise RuntimeError("Parent tournament not found")

        if parent.promoted_child_tournament_id:
            child = session.get(Tournament, parent.promoted_child_tournament_id)
            if not child:
                raise RuntimeError("Promoted child tournament reference is broken")
            return child

        ordered = self._ordered_cut_entrants(session, parent.id, parent.top_cut_size)
        if len(ordered) < 8:
            raise RuntimeError("At least 8 entrants are required to create the Top 8 child tournament")

        child = Tournament(
            id=self._new_id(),
            guild_id=parent.guild_id,
            name=f"{parent.name} Top 8",
            category_slug=parent.category_slug,
            format="double_elim",
            entrant_type=parent.entrant_type,
            stage_type="top8",
            status="active",
            current_round_number=1,
            swiss_round_count=None,
            top_cut_size=8,
            seeding_race_count=0,
            seeding_locked=True,
            config_json=parent.config_json,
            parent_tournament_id=parent.id,
            created_by_discord_id=parent.created_by_discord_id,
        )
        session.add(child)
        session.flush()

        child_by_seed: dict[int, Entrant] = {}
        for idx, parent_entrant in enumerate(ordered, start=1):
            parent_entrant.final_rank = idx
            child_entrant = self._clone_entrant_for_child(
                session,
                parent_entrant=parent_entrant,
                child_tournament_id=child.id,
                cut_seed=idx,
            )
            child_by_seed[idx] = child_entrant

        self.generate_top8_double_elim_pairings(session, child.id, child_by_seed)

        parent.promoted_child_tournament_id = child.id
        parent.is_locked = True
        parent.status = "completed"
        session.flush()
        return child

    def generate_top8_double_elim_pairings(
        self,
        session: Session,
        tournament_id: str,
        entrants_by_seed: dict[int, Entrant],
    ) -> list[Pairing]:
        created: list[Pairing] = []

        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=1,
            pairing_code="WB1",
            phase_type="top8",
            bracket_side="WB",
            bracket_round=1,
            bracket_match_number=1,
            entrant1_id=entrants_by_seed[1].id,
            entrant2_id=entrants_by_seed[8].id,
        ))
        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=1,
            pairing_code="WB2",
            phase_type="top8",
            bracket_side="WB",
            bracket_round=1,
            bracket_match_number=2,
            entrant1_id=entrants_by_seed[4].id,
            entrant2_id=entrants_by_seed[5].id,
        ))
        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=1,
            pairing_code="WB3",
            phase_type="top8",
            bracket_side="WB",
            bracket_round=1,
            bracket_match_number=3,
            entrant1_id=entrants_by_seed[2].id,
            entrant2_id=entrants_by_seed[7].id,
        ))
        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=1,
            pairing_code="WB4",
            phase_type="top8",
            bracket_side="WB",
            bracket_round=1,
            bracket_match_number=4,
            entrant1_id=entrants_by_seed[3].id,
            entrant2_id=entrants_by_seed[6].id,
        ))

        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=2,
            pairing_code="WB5",
            phase_type="top8",
            bracket_side="WB",
            bracket_round=2,
            bracket_match_number=1,
            source_win_pairing_a_code="WB1",
            source_win_pairing_b_code="WB2",
        ))
        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=2,
            pairing_code="WB6",
            phase_type="top8",
            bracket_side="WB",
            bracket_round=2,
            bracket_match_number=2,
            source_win_pairing_a_code="WB3",
            source_win_pairing_b_code="WB4",
        ))
        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=3,
            pairing_code="WB7",
            phase_type="top8",
            bracket_side="WB",
            bracket_round=3,
            bracket_match_number=1,
            source_win_pairing_a_code="WB5",
            source_win_pairing_b_code="WB6",
        ))

        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=1,
            pairing_code="LB1",
            phase_type="top8",
            bracket_side="LB",
            bracket_round=1,
            bracket_match_number=1,
            source_loss_pairing_a_code="WB1",
            source_loss_pairing_b_code="WB2",
        ))
        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=1,
            pairing_code="LB2",
            phase_type="top8",
            bracket_side="LB",
            bracket_round=1,
            bracket_match_number=2,
            source_loss_pairing_a_code="WB3",
            source_loss_pairing_b_code="WB4",
        ))
        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=2,
            pairing_code="LB3",
            phase_type="top8",
            bracket_side="LB",
            bracket_round=2,
            bracket_match_number=1,
            source_win_pairing_a_code="LB1",
            source_loss_pairing_b_code="WB6",
        ))
        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=2,
            pairing_code="LB4",
            phase_type="top8",
            bracket_side="LB",
            bracket_round=2,
            bracket_match_number=2,
            source_win_pairing_a_code="LB2",
            source_loss_pairing_b_code="WB5",
        ))
        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=3,
            pairing_code="LB5",
            phase_type="top8",
            bracket_side="LB",
            bracket_round=3,
            bracket_match_number=1,
            source_win_pairing_a_code="LB3",
            source_win_pairing_b_code="LB4",
        ))
        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=4,
            pairing_code="LB6",
            phase_type="top8",
            bracket_side="LB",
            bracket_round=4,
            bracket_match_number=1,
            source_win_pairing_a_code="LB5",
            source_loss_pairing_b_code="WB7",
        ))
        created.append(self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=5,
            pairing_code="GF1",
            phase_type="top8",
            bracket_side="GF",
            bracket_round=1,
            bracket_match_number=1,
            source_win_pairing_a_code="WB7",
            source_win_pairing_b_code="LB6",
        ))

        session.flush()
        return created

    def _get_pairing_by_code(self, session: Session, tournament_id: str, pairing_code: str) -> Pairing | None:
        return session.execute(
            select(Pairing).where(
                Pairing.tournament_id == tournament_id,
                Pairing.pairing_code == pairing_code,
            )
        ).scalar_one_or_none()

    def _assign_downstream_slot(
        self,
        downstream: Pairing,
        *,
        source_code: str,
        winner_entrant_id: str | None,
        loser_entrant_id: str | None,
    ) -> bool:
        changed = False

        if downstream.source_win_pairing_a_code == source_code and winner_entrant_id and downstream.entrant1_id != winner_entrant_id:
            downstream.entrant1_id = winner_entrant_id
            changed = True
        if downstream.source_win_pairing_b_code == source_code and winner_entrant_id and downstream.entrant2_id != winner_entrant_id:
            downstream.entrant2_id = winner_entrant_id
            changed = True
        if downstream.source_loss_pairing_a_code == source_code and loser_entrant_id and downstream.entrant1_id != loser_entrant_id:
            downstream.entrant1_id = loser_entrant_id
            changed = True
        if downstream.source_loss_pairing_b_code == source_code and loser_entrant_id and downstream.entrant2_id != loser_entrant_id:
            downstream.entrant2_id = loser_entrant_id
            changed = True

        if downstream.entrant1_id and downstream.entrant2_id and downstream.status == "pending":
            downstream.status = "ready"
            changed = True

        return changed

    def _ensure_gf_reset(self, session: Session, tournament_id: str, entrant1_id: str, entrant2_id: str) -> Pairing:
        existing = self._get_pairing_by_code(session, tournament_id, "GF2")
        if existing:
            return existing

        return self._make_pairing(
            session,
            tournament_id=tournament_id,
            round_number=6,
            pairing_code="GF2",
            phase_type="top8",
            bracket_side="GF",
            bracket_round=2,
            bracket_match_number=1,
            entrant1_id=entrant1_id,
            entrant2_id=entrant2_id,
        )

    def apply_result(self, session: Session, pairing_id: str) -> list[Pairing]:
        pairing = session.get(Pairing, pairing_id)
        if not pairing:
            raise RuntimeError("Pairing not found")
        if not pairing.winner_entrant_id:
            raise RuntimeError("Pairing has no winner set")

        loser_entrant_id: str | None = None
        if pairing.entrant1_id and pairing.entrant2_id:
            loser_entrant_id = pairing.entrant2_id if pairing.winner_entrant_id == pairing.entrant1_id else pairing.entrant1_id

        pairing.status = "completed"
        pairing.result_approved = "true"

        downstream = session.execute(
            select(Pairing).where(Pairing.tournament_id == pairing.tournament_id)
        ).scalars().all()

        newly_ready: list[Pairing] = []
        for child in downstream:
            if child.id == pairing.id:
                continue
            changed = self._assign_downstream_slot(
                child,
                source_code=pairing.pairing_code or "",
                winner_entrant_id=pairing.winner_entrant_id,
                loser_entrant_id=loser_entrant_id,
            )
            if changed and child.status == "ready":
                newly_ready.append(child)

        tournament = session.get(Tournament, pairing.tournament_id)
        if not tournament:
            raise RuntimeError("Tournament not found")

        if pairing.pairing_code == "GF1":
            if pairing.winner_entrant_id == pairing.entrant1_id:
                tournament.status = "completed"
                tournament.is_locked = True
            else:
                gf2 = self._ensure_gf_reset(
                    session,
                    tournament_id=pairing.tournament_id,
                    entrant1_id=pairing.entrant1_id or "",
                    entrant2_id=pairing.entrant2_id or "",
                )
                newly_ready.append(gf2)

        if pairing.pairing_code == "GF2":
            tournament.status = "completed"
            tournament.is_locked = True

        session.flush()
        return newly_ready