from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from app.db.session import session_scope
from app.models.async_seed_asset import AsyncSeedAsset
from app.models.async_seed_request import AsyncSeedRequest
from app.models.entrant import Entrant
from app.models.entrant_member import EntrantMember
from app.models.tournament import Tournament


@dataclass
class EntrantSnapshot:
    entrant_id: str
    entrant_name: str
    is_team: bool
    member_ids: list[str]


class AsyncSeedService:
    def __init__(self) -> None:
        self.storage_root = os.getenv("ASYNC_SEED_STORAGE_ROOT", "./async_seeds")

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

    def _detach_many(self, session, objs):
        for obj in objs:
            session.expunge(obj)
        return objs

    def _snapshot_for_entrant(self, session, entrant_id: str) -> EntrantSnapshot:
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
            return EntrantSnapshot(
                entrant_id=str(entrant.id),
                entrant_name=str(entrant.display_name),
                is_team=True,
                member_ids=member_ids,
            )

        member_ids = [str(entrant.discord_id)] if entrant.discord_id else []
        return EntrantSnapshot(
            entrant_id=str(entrant.id),
            entrant_name=str(entrant.display_name),
            is_team=False,
            member_ids=member_ids,
        )

    def upload_asset(
        self,
        *,
        tournament_id: str,
        race_number: int,
        uploaded_by_discord_id: str,
        raw_bytes: bytes,
        original_filename: str,
        content_type: str,
        notes: str | None = None,
        replace_existing: bool = False,
    ) -> AsyncSeedAsset:
        with session_scope() as session:
            tournament = session.get(Tournament, tournament_id)
            if not tournament:
                raise ValueError("Tournament not found.")

            existing = session.execute(
                select(AsyncSeedAsset).where(
                    AsyncSeedAsset.tournament_id == tournament_id,
                    AsyncSeedAsset.race_number == race_number,
                )
            ).scalar_one_or_none()

            if existing and not replace_existing:
                raise ValueError("An async seed is already stored for that race. Use replace_existing to overwrite it.")

            folder = self._ensure_dir(self.storage_root, str(tournament_id), f"race_{race_number}")
            safe_name = original_filename or f"async_seed_{race_number}.bin"
            local_filename = f"{self._new_id()}_{safe_name}"
            local_path = os.path.join(folder, local_filename)

            with open(local_path, "wb") as f:
                f.write(raw_bytes)

            if existing:
                try:
                    if existing.local_path and os.path.exists(existing.local_path):
                        os.remove(existing.local_path)
                except OSError:
                    pass

                existing.original_filename = original_filename
                existing.content_type = content_type
                existing.local_path = local_path
                existing.notes = notes
                existing.uploaded_by_discord_id = str(uploaded_by_discord_id)
                existing.updated_at_utc = datetime.utcnow()

                session.flush()
                session.refresh(existing)
                return self._detach(session, existing)

            asset = AsyncSeedAsset(
                id=self._new_id(),
                tournament_id=str(tournament_id),
                race_number=int(race_number),
                original_filename=original_filename,
                content_type=content_type,
                local_path=local_path,
                notes=notes,
                uploaded_by_discord_id=str(uploaded_by_discord_id),
                created_at_utc=datetime.utcnow(),
                updated_at_utc=datetime.utcnow(),
            )
            session.add(asset)
            session.flush()
            session.refresh(asset)
            return self._detach(session, asset)

    def get_asset(self, *, tournament_id: str, race_number: int) -> AsyncSeedAsset | None:
        with session_scope() as session:
            asset = session.execute(
                select(AsyncSeedAsset).where(
                    AsyncSeedAsset.tournament_id == tournament_id,
                    AsyncSeedAsset.race_number == race_number,
                )
            ).scalar_one_or_none()
            return self._detach(session, asset)

    def create_request(
        self,
        *,
        tournament_id: str,
        entrant_id: str,
        race_number: int,
        requested_by_discord_id: str,
    ) -> tuple[AsyncSeedRequest, AsyncSeedAsset]:
        with session_scope() as session:
            tournament = session.get(Tournament, tournament_id)
            if not tournament:
                raise ValueError("Tournament not found.")

            asset = session.execute(
                select(AsyncSeedAsset).where(
                    AsyncSeedAsset.tournament_id == tournament_id,
                    AsyncSeedAsset.race_number == race_number,
                )
            ).scalar_one_or_none()
            if not asset:
                raise ValueError("No async seed has been uploaded for that race.")

            existing = session.execute(
                select(AsyncSeedRequest).where(
                    AsyncSeedRequest.tournament_id == tournament_id,
                    AsyncSeedRequest.entrant_id == entrant_id,
                    AsyncSeedRequest.race_number == race_number,
                )
            ).scalar_one_or_none()
            if existing:
                raise ValueError("That entrant has already requested this async seed.")

            snapshot = self._snapshot_for_entrant(session, entrant_id)

            request = AsyncSeedRequest(
                id=self._new_id(),
                tournament_id=str(tournament_id),
                entrant_id=str(entrant_id),
                race_number=int(race_number),
                requested_by_discord_id=str(requested_by_discord_id),
                entrant_name_snapshot=snapshot.entrant_name,
                entrant_is_team_snapshot=bool(snapshot.is_team),
                entrant_member_ids_snapshot=",".join(snapshot.member_ids),
                requested_at_utc=datetime.utcnow(),
            )
            session.add(request)
            session.flush()
            session.refresh(request)
            session.refresh(asset)

            return self._detach(session, request), self._detach(session, asset)

    def list_requests(
        self,
        *,
        tournament_id: str,
        race_number: int | None = None,
    ) -> list[AsyncSeedRequest]:
        with session_scope() as session:
            stmt = select(AsyncSeedRequest).where(AsyncSeedRequest.tournament_id == tournament_id)
            if race_number is not None:
                stmt = stmt.where(AsyncSeedRequest.race_number == race_number)
            stmt = stmt.order_by(AsyncSeedRequest.requested_at_utc.asc())

            rows = list(session.execute(stmt).scalars().all())
            return self._detach_many(session, rows)

    def clear_request(
        self,
        *,
        tournament_id: str,
        entrant_id: str,
        race_number: int,
    ) -> None:
        with session_scope() as session:
            request = session.execute(
                select(AsyncSeedRequest).where(
                    AsyncSeedRequest.tournament_id == tournament_id,
                    AsyncSeedRequest.entrant_id == entrant_id,
                    AsyncSeedRequest.race_number == race_number,
                )
            ).scalar_one_or_none()

            if not request:
                raise ValueError("Async seed request not found.")

            session.delete(request)
            session.flush()

    def validate_request_snapshot(
        self,
        *,
        tournament_id: str,
        entrant_id: str,
        race_number: int,
    ) -> None:
        with session_scope() as session:
            request = session.execute(
                select(AsyncSeedRequest).where(
                    AsyncSeedRequest.tournament_id == tournament_id,
                    AsyncSeedRequest.entrant_id == entrant_id,
                    AsyncSeedRequest.race_number == race_number,
                )
            ).scalar_one_or_none()

            if not request:
                raise ValueError("This entrant has not requested that async seed yet.")

            current = self._snapshot_for_entrant(session, entrant_id)
            requested_ids = sorted(
                [x for x in (request.entrant_member_ids_snapshot or "").split(",") if x]
            )

            if current.is_team != bool(request.entrant_is_team_snapshot):
                raise ValueError("Entrant composition no longer matches the original async request.")
            if current.member_ids != requested_ids:
                raise ValueError("Entrant composition no longer matches the original async request.")