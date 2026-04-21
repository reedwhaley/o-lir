from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Pairing(Base):
    __tablename__ = "pairings"
    __table_args__ = (
        UniqueConstraint("tournament_id", "pairing_code", name="uq_pairing_code_per_tournament"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(String(32), index=True)

    round_number: Mapped[int] = mapped_column(Integer, default=1)
    phase_type: Mapped[str] = mapped_column(String(32), default="main")
    pairing_code: Mapped[str | None] = mapped_column(String(16), nullable=True)

    entrant1_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    entrant2_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(32), default="pending")

    thread_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    thread_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    starter_message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    lightbringer_match_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    scheduled_start_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    winner_entrant_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    result_approved: Mapped[str] = mapped_column(String(8), default="false")

    bracket_side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    bracket_round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bracket_match_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source_win_pairing_a_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_win_pairing_b_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_loss_pairing_a_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_loss_pairing_b_code: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )