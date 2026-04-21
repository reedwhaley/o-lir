from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.models.pairing import Pairing
from app.models.pairing_result import PairingResult
from app.models.tournament import Tournament
from app.services.top8_service import Top8Service


class PairingService:
    def __init__(self) -> None:
        self.top8 = Top8Service()

    def _new_id(self) -> str:
        return secrets.token_hex(16)

    def _winner_entrant_id_from_payload(self, pairing: Pairing, payload: dict) -> str | None:
        winner_side = str(payload.get("winner_side", "") or "").lower()
        if winner_side == "team1":
            return pairing.entrant1_id
        if winner_side == "team2":
            return pairing.entrant2_id
        return None

    def _all_main_stage_pairings_complete(self, session: Session, tournament_id: str) -> bool:
        pairings = session.execute(
            select(Pairing).where(Pairing.tournament_id == tournament_id)
        ).scalars().all()

        if not pairings:
            return False

        return all(p.status == "completed" and p.result_approved == "true" for p in pairings)

    def _scheduled_dt_from_iso(self, value: str | None) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt
        except ValueError as exc:
            raise ValueError(f"Invalid ISO datetime: {value}") from exc

    def get_pairing(self, pairing_id: str) -> Pairing | None:
        with session_scope() as session:
            pairing = session.get(Pairing, pairing_id)
            if pairing is not None:
                session.expunge(pairing)
            return pairing

    def list_pairings(
        self,
        tournament_id: str,
        round_number: int | None = None,
        unresolved_only: bool = False,
    ) -> list[Pairing]:
        with session_scope() as session:
            stmt = select(Pairing).where(Pairing.tournament_id == tournament_id)

            if round_number is not None:
                stmt = stmt.where(Pairing.round_number == round_number)

            pairings = list(session.execute(stmt).scalars().all())

            if unresolved_only:
                pairings = [
                    p for p in pairings
                    if not (
                        str(getattr(p, "status", "") or "").lower() == "completed"
                        and str(getattr(p, "result_approved", "") or "").lower() == "true"
                    )
                ]

            pairings.sort(key=lambda p: (int(getattr(p, "round_number", 0) or 0), str(getattr(p, "id", ""))))
            for pairing in pairings:
                session.expunge(pairing)
            return pairings

    def get_pairing_result(self, pairing_id: str) -> PairingResult | None:
        with session_scope() as session:
            result = session.execute(
                select(PairingResult).where(PairingResult.pairing_id == pairing_id)
            ).scalar_one_or_none()
            if result is not None:
                session.expunge(result)
            return result

    def get_pairing_by_thread_id(self, thread_id: str) -> Pairing | None:
        with session_scope() as session:
            pairing = session.execute(
                select(Pairing).where(Pairing.thread_id == str(thread_id))
            ).scalar_one_or_none()
            if pairing is not None:
                session.expunge(pairing)
            return pairing

    def build_lookup_response(self, pairing: Pairing) -> dict[str, Any]:
        return {
            "pairing_id": pairing.id,
            "status": pairing.status,
            "thread_id": pairing.thread_id,
            "thread_channel_id": pairing.thread_channel_id,
            "starter_message_id": getattr(pairing, "starter_message_id", None),
            "lightbringer_match_id": pairing.lightbringer_match_id,
            "scheduled_start_at_utc": pairing.scheduled_start_at_utc,
            "entrant1_id": pairing.entrant1_id,
            "entrant2_id": pairing.entrant2_id,
            "tournament_id": pairing.tournament_id,
        }

    def set_thread_context(
        self,
        pairing_id: str,
        *,
        thread_id: str,
        thread_channel_id: str,
        starter_message_id: str | None = None,
    ) -> Pairing:
        with session_scope() as session:
            pairing = session.get(Pairing, pairing_id)
            if pairing is None:
                raise LookupError("Pairing not found")

            pairing.thread_id = str(thread_id)
            pairing.thread_channel_id = str(thread_channel_id)
            if starter_message_id is not None:
                pairing.starter_message_id = str(starter_message_id)

            session.flush()
            session.refresh(pairing)
            session.expunge(pairing)
            return pairing

    def link_lightbringer_match(
        self,
        *,
        pairing_id: str,
        lightbringer_match_id: str,
        scheduled_start_at_utc: str,
    ) -> Pairing:
        with session_scope() as session:
            pairing = session.get(Pairing, pairing_id)
            if pairing is None:
                raise LookupError("Pairing not found")

            existing = session.execute(
                select(Pairing).where(Pairing.lightbringer_match_id == str(lightbringer_match_id))
            ).scalar_one_or_none()

            if existing is not None and existing.id != pairing.id:
                raise ValueError("Lightbringer match is already linked to a different pairing")

            pairing.lightbringer_match_id = str(lightbringer_match_id)
            pairing.scheduled_start_at_utc = self._scheduled_dt_from_iso(scheduled_start_at_utc)

            current_status = str(getattr(pairing, "status", "") or "").lower()
            if current_status not in {"completed", "cancelled"}:
                pairing.status = "scheduled"

            session.flush()
            session.refresh(pairing)
            session.expunge(pairing)
            return pairing

    def record_lightbringer_result(self, payload: Any) -> Pairing:
        payload_dict = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        lightbringer_match_id = str(payload_dict.get("lightbringer_match_id", "") or "").strip()
        if not lightbringer_match_id:
            raise LookupError("Missing Lightbringer match ID")

        with session_scope() as session:
            pairing, _newly_ready, _promoted_child = self.record_imported_result(
                session,
                lightbringer_match_id=lightbringer_match_id,
                payload=payload_dict,
            )
            session.refresh(pairing)
            session.expunge(pairing)
            return pairing

    def record_imported_result(
        self,
        session: Session,
        *,
        lightbringer_match_id: str,
        payload: dict,
    ) -> tuple[Pairing, list[Pairing], Tournament | None]:
        pairing = session.execute(
            select(Pairing).where(Pairing.lightbringer_match_id == lightbringer_match_id)
        ).scalar_one_or_none()

        if not pairing:
            raise RuntimeError("Pairing not found for Lightbringer match")

        tournament = session.get(Tournament, pairing.tournament_id)
        if not tournament:
            raise RuntimeError("Tournament not found")

        winner_entrant_id = self._winner_entrant_id_from_payload(pairing, payload)

        result = session.execute(
            select(PairingResult).where(PairingResult.pairing_id == pairing.id)
        ).scalar_one_or_none()

        if not result:
            result = PairingResult(
                id=self._new_id(),
                pairing_id=pairing.id,
                lightbringer_match_id=lightbringer_match_id,
            )
            session.add(result)

        result.source = str(payload.get("result_source", "lightbringer"))
        result.status = str(payload.get("status", "finished"))
        result.winner_side = payload.get("winner_side")
        result.winner_entrant_id = winner_entrant_id
        result.entrant1_finish_time_seconds = (
            payload.get("team1", {}) or {}
        ).get("finish_time_seconds")
        result.entrant2_finish_time_seconds = (
            payload.get("team2", {}) or {}
        ).get("finish_time_seconds")
        result.payload_json = json.dumps(payload)
        result.confirmed_at_utc = datetime.utcnow()

        pairing.winner_entrant_id = winner_entrant_id
        pairing.status = "completed"
        pairing.result_approved = "true"

        newly_ready: list[Pairing] = []
        promoted_child: Tournament | None = None

        if tournament.stage_type == "top8" and tournament.format == "double_elim":
            newly_ready = self.top8.apply_result(session, pairing.id)

        elif tournament.stage_type == "main" and tournament.format == "swiss_to_top8_double_elim":
            if self._all_main_stage_pairings_complete(session, tournament.id) and not tournament.promoted_child_tournament_id:
                promoted_child = self.top8.promote_parent_to_top8(session, tournament.id)
                newly_ready = session.execute(
                    select(Pairing).where(
                        Pairing.tournament_id == promoted_child.id,
                        Pairing.status == "ready",
                    )
                ).scalars().all()

        session.flush()
        return pairing, newly_ready, promoted_child