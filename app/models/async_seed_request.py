from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AsyncSeedRequest(Base):
    __tablename__ = "async_seed_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)

    tournament_id: Mapped[str] = mapped_column(String(32), index=True)
    entrant_id: Mapped[str] = mapped_column(String(32), index=True)
    race_number: Mapped[int] = mapped_column(Integer, index=True)

    requested_by_discord_id: Mapped[str] = mapped_column(String(32), index=True)

    entrant_name_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    entrant_is_team_snapshot: Mapped[bool] = mapped_column(Boolean, default=False)
    entrant_member_ids_snapshot: Mapped[str | None] = mapped_column(String(500), nullable=True)

    requested_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)