from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PairingResult(Base):
    __tablename__ = "pairing_results"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    pairing_id: Mapped[str] = mapped_column(String(32), index=True)
    lightbringer_match_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    source: Mapped[str] = mapped_column(String(32), default="lightbringer")
    status: Mapped[str] = mapped_column(String(32), default="finished")

    winner_side: Mapped[str | None] = mapped_column(String(16), nullable=True)
    winner_entrant_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    entrant1_finish_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    entrant2_finish_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    reported_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    confirmed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    is_override: Mapped[bool] = mapped_column(Boolean, default=False)