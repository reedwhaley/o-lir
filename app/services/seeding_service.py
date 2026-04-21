from __future__ import annotations

import hashlib
import math
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy import select

from app.db.session import session_scope
from app.models.async_seed_request import AsyncSeedRequest
from app.models.entrant import Entrant
from app.models.entrant_member import EntrantMember
from app.models.seeding_submission import SeedingSubmission
from app.models.tournament import Tournament


def parse_time_to_seconds(value: str) -> float:
    raw = str(value).strip()
    if not raw:
        raise ValueError("Time value is required.")

    if raw.isdigit():
        return float(int(raw))

    parts = raw.split(":")
    try:
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return (minutes * 60) + seconds

        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return (hours * 3600) + (minutes * 60) + seconds
    except ValueError as exc:
        raise ValueError("Invalid time format. Use mm:ss, hh:mm:ss, or raw seconds.") from exc

    raise ValueError("Invalid time format. Use mm:ss, hh:mm:ss, or raw seconds.")


def format_seconds(value: float | int | None) -> str:
    if value is None:
        return "-"

    total = float(value)
    if total < 0:
        return "-"

    whole = int(total)
    frac = total - whole

    hours = whole // 3600
    minutes = (whole % 3600) // 60
    seconds = whole % 60

    if frac:
        sec_text = f"{seconds + frac:05.2f}"
        if hours > 0:
            return f"{hours}:{minutes:02d}:{sec_text}"
        return f"{minutes}:{sec_text}"

    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


@dataclass
class SeedRow:
    entrant_id: str
    display_name: str
    seed: int
    score: float


class SeedingService:
    def __init__(self) -> None:
        self.storage_root = os.getenv("SEEDING_PROOF_STORAGE_ROOT", "./seeding_proofs")

    def _new_id(self) -> str:
        return secrets.token_hex(16)

    def _ensure_dir(self, *parts: str) -> str:
        path = os.path.join(*parts)
        os.makedirs(path, exist_ok=True)
        return path

    def _detach(self, session, obj):
        if obj is not None:
            session.expunge(obj)
        return obj

    def _detach_many(self, session, objs: Iterable):
        items = list(objs)
        for obj in items:
            session.expunge(obj)
        return items

    def _entrant_snapshot_now(self, session, entrant_id: str) -> tuple[bool, list[str]]:
        entrant = session.get(Entrant, entrant_id)
        if not entrant:
            raise ValueError("Entrant not found.")

        if entrant.is_team:
            members = list(
                session.execute(
                    select(EntrantMember).where(EntrantMember.entrant_id == entrant_id)
                ).scalars().all()
            )
            member_ids = sorted(str(member.discord_id) for member in members)
            return True, member_ids

        member_ids = [str(entrant.discord_id)] if entrant.discord_id else []
        return False, member_ids

    def _validate_async_request_snapshot(
        self,
        session,
        *,
        tournament_id: str,
        entrant_id: str,
        race_number: int,
    ) -> AsyncSeedRequest:
        request = session.execute(
            select(AsyncSeedRequest).where(
                AsyncSeedRequest.tournament_id == str(tournament_id),
                AsyncSeedRequest.entrant_id == str(entrant_id),
                AsyncSeedRequest.race_number == int(race_number),
            )
        ).scalar_one_or_none()

        if request is None:
            raise ValueError("This entrant has not requested that async seed yet.")

        current_is_team, current_member_ids = self._entrant_snapshot_now(session, entrant_id)
        requested_is_team = bool(getattr(request, "entrant_is_team_snapshot", False))
        requested_member_ids = sorted(
            [x for x in str(getattr(request, "entrant_member_ids_snapshot", "") or "").split(",") if x]
        )

        if current_is_team != requested_is_team:
            raise ValueError("Entrant composition no longer matches the original async request.")

        if current_member_ids != requested_member_ids:
            raise ValueError("Entrant composition no longer matches the original async request.")

        return request

    def submit_seeding_time(
        self,
        *,
        tournament_id: str,
        entrant_id: str,
        race_number: int,
        submitted_time_seconds: float,
        submitted_by_discord_id: str,
        vod_url: str,
        original_filename: str,
        content_type: str,
        file_bytes: bytes,
    ) -> SeedingSubmission:
        with session_scope() as session:
            tournament = session.get(Tournament, tournament_id)
            if not tournament:
                raise ValueError("Tournament not found.")

            entrant = session.get(Entrant, entrant_id)
            if not entrant:
                raise ValueError("Entrant not found.")

            if str(entrant.tournament_id) != str(tournament_id):
                raise ValueError("Entrant does not belong to that tournament.")

            request = self._validate_async_request_snapshot(
                session,
                tournament_id=tournament_id,
                entrant_id=entrant_id,
                race_number=race_number,
            )

            existing = session.execute(
                select(SeedingSubmission).where(
                    SeedingSubmission.tournament_id == str(tournament_id),
                    SeedingSubmission.entrant_id == str(entrant_id),
                    SeedingSubmission.race_number == int(race_number),
                )
            ).scalar_one_or_none()

            if existing:
                raise ValueError("A submission already exists for that entrant and seed race.")

            folder = self._ensure_dir(self.storage_root, str(tournament_id), str(entrant_id))
            safe_name = original_filename or f"seed_{race_number}.bin"
            local_filename = f"{self._new_id()}_{safe_name}"
            local_path = os.path.join(folder, local_filename)

            with open(local_path, "wb") as f:
                f.write(file_bytes)

            sha256_value = hashlib.sha256(file_bytes).hexdigest()
            now = datetime.utcnow()

            submission = SeedingSubmission(
                tournament_id=str(tournament_id),
                entrant_id=str(entrant_id),
                async_seed_request_id=str(request.id),
                race_number=int(race_number),
                submitted_time_seconds=float(submitted_time_seconds),
                sum_of_times_seconds=None,
                submitted_by_discord_id=str(submitted_by_discord_id),
                submitted_at_utc=now,
                vod_url=str(vod_url),
                outcome_code="submitted",
                status="pending",
                seeding_score=None,
                original_filename=original_filename,
                content_type=content_type,
                local_path=local_path,
                sha256=sha256_value,
                review_notes=None,
                reviewed_by_discord_id=None,
                reviewed_at_utc=None,
                created_at_utc=now,
                updated_at_utc=now,
            )
            session.add(submission)
            session.flush()
            session.refresh(submission)
            return self._detach(session, submission)

    def get_submission(self, submission_id: str | int) -> SeedingSubmission | None:
        with session_scope() as session:
            submission = session.get(SeedingSubmission, submission_id)
            return self._detach(session, submission)

    def list_submissions(
        self,
        tournament_id: str,
        *,
        entrant_id: str | None = None,
        status: str | None = None,
    ) -> list[SeedingSubmission]:
        with session_scope() as session:
            stmt = select(SeedingSubmission).where(
                SeedingSubmission.tournament_id == str(tournament_id)
            )

            if entrant_id:
                stmt = stmt.where(SeedingSubmission.entrant_id == str(entrant_id))

            if status:
                stmt = stmt.where(SeedingSubmission.status == str(status))

            stmt = stmt.order_by(
                SeedingSubmission.race_number.asc(),
                SeedingSubmission.submitted_at_utc.asc(),
            )

            rows = list(session.execute(stmt).scalars().all())
            return self._detach_many(session, rows)

    def approve_submission(
        self,
        submission_id: str | int,
        reviewed_by_discord_id: str,
        notes: str | None = None,
    ) -> SeedingSubmission:
        with session_scope() as session:
            submission = session.get(SeedingSubmission, submission_id)
            if not submission:
                raise LookupError("Submission not found.")

            submission.status = "approved"
            submission.review_notes = notes
            submission.reviewed_by_discord_id = str(reviewed_by_discord_id)
            submission.reviewed_at_utc = datetime.utcnow()
            submission.updated_at_utc = datetime.utcnow()

            session.flush()
            session.refresh(submission)
            return self._detach(session, submission)

    def reject_submission(
        self,
        submission_id: str | int,
        reviewed_by_discord_id: str,
        notes: str | None = None,
    ) -> SeedingSubmission:
        with session_scope() as session:
            submission = session.get(SeedingSubmission, submission_id)
            if not submission:
                raise LookupError("Submission not found.")

            submission.status = "rejected"
            submission.review_notes = notes
            submission.reviewed_by_discord_id = str(reviewed_by_discord_id)
            submission.reviewed_at_utc = datetime.utcnow()
            submission.updated_at_utc = datetime.utcnow()

            session.flush()
            session.refresh(submission)
            return self._detach(session, submission)

    def clear_submission(self, submission_id: str | int) -> None:
        with session_scope() as session:
            submission = session.get(SeedingSubmission, submission_id)
            if not submission:
                raise LookupError("Submission not found.")

            try:
                if submission.local_path and os.path.exists(submission.local_path):
                    os.remove(submission.local_path)
            except OSError:
                pass

            session.delete(submission)
            session.flush()

    def _score_submission_groups(
        self,
        approved_submissions: list[SeedingSubmission],
    ) -> dict[int, list[tuple[str, float]]]:
        grouped: dict[int, list[tuple[str, float]]] = {}
        for submission in approved_submissions:
            grouped.setdefault(int(submission.race_number), []).append(
                (str(submission.entrant_id), float(submission.submitted_time_seconds))
            )
        return grouped

    def compute_seeds(self, tournament_id: str) -> list[SeedRow]:
        with session_scope() as session:
            tournament = session.get(Tournament, tournament_id)
            if not tournament:
                raise LookupError("Tournament not found.")

            entrants = list(
                session.execute(
                    select(Entrant).where(
                        Entrant.tournament_id == str(tournament_id),
                        Entrant.is_active.is_(True),
                    )
                ).scalars().all()
            )
            if not entrants:
                raise ValueError("No active entrants found for this tournament.")

            approved_submissions = list(
                session.execute(
                    select(SeedingSubmission).where(
                        SeedingSubmission.tournament_id == str(tournament_id),
                        SeedingSubmission.status == "approved",
                    )
                ).scalars().all()
            )

            entrant_count = len(entrants)
            top_x = max(1, math.ceil(entrant_count / 6))
            grouped = self._score_submission_groups(approved_submissions)

            scores_by_entrant: dict[str, list[float]] = {str(e.id): [] for e in entrants}

            for _race_number, runs in grouped.items():
                if not runs:
                    continue

                sorted_runs = sorted(runs, key=lambda item: item[1])
                par_pool = sorted_runs[:top_x]
                par_sum = sum(t for _entrant_id, t in par_pool)

                if par_sum <= 0:
                    continue

                per_race_map = {entrant_id: time_value for entrant_id, time_value in runs}

                for entrant in entrants:
                    entrant_id = str(entrant.id)
                    if entrant_id not in per_race_map:
                        score = 0.0
                    else:
                        score = (2 - (per_race_map[entrant_id] / par_sum)) * 100
                        score = max(0.1, score)
                    scores_by_entrant[entrant_id].append(float(score))

            final_rows: list[SeedRow] = []
            for entrant in entrants:
                entrant_id = str(entrant.id)
                scores = sorted(scores_by_entrant.get(entrant_id, []), reverse=True)
                final_score = sum(scores[:2]) if scores else 0.0
                final_rows.append(
                    SeedRow(
                        entrant_id=entrant_id,
                        display_name=str(entrant.display_name),
                        seed=0,
                        score=final_score,
                    )
                )

            final_rows.sort(key=lambda row: (-row.score, row.display_name.lower(), row.entrant_id))

            for index, row in enumerate(final_rows, start=1):
                row.seed = index

            for row in final_rows:
                entrant = next((e for e in entrants if str(e.id) == row.entrant_id), None)
                if entrant is not None:
                    entrant.seed = int(row.seed)

            session.flush()
            return final_rows