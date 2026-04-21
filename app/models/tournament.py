from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)

    name: Mapped[str] = mapped_column(String(150))
    category_slug: Mapped[str] = mapped_column(String(32), index=True)

    format: Mapped[str] = mapped_column(String(64), default="swiss_to_top8_double_elim")
    entrant_type: Mapped[str] = mapped_column(String(16), default="player")
    stage_type: Mapped[str] = mapped_column(String(32), default="main")

    status: Mapped[str] = mapped_column(String(32), default="registration_open")
    signup_open: Mapped[bool] = mapped_column(Boolean, default=True)

    current_round_number: Mapped[int] = mapped_column(Integer, default=0)

    swiss_round_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_cut_size: Mapped[int] = mapped_column(Integer, default=8)

    seeding_race_count: Mapped[int] = mapped_column(Integer, default=3)
    seeding_locked: Mapped[bool] = mapped_column(Boolean, default=False)

    seeding_method: Mapped[str] = mapped_column(String(32), default="baja_special")
    seeding_drop_count: Mapped[int] = mapped_column(Integer, default=1)
    standings_tiebreak_method: Mapped[str] = mapped_column(String(64), default="buchholz_then_sonneborn_berger")

    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    parent_tournament_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    promoted_child_tournament_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)

    created_by_discord_id: Mapped[str] = mapped_column(String(32))

    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )