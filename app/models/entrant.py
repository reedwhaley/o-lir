from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Entrant(Base):
    __tablename__ = "entrants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(String(32), index=True)

    display_name: Mapped[str] = mapped_column(String(150))
    discord_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    captain_discord_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    is_team: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_eliminated: Mapped[bool] = mapped_column(Boolean, default=False)

    seed: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    final_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    final_seeding_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_seed_race_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    second_best_seed_race_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    match_points: Mapped[float] = mapped_column(Float, default=0.0)
    buchholz: Mapped[float] = mapped_column(Float, default=0.0)
    sonneborn_berger: Mapped[float] = mapped_column(Float, default=0.0)
    opponent_match_win_pct: Mapped[float] = mapped_column(Float, default=0.0)
    game_win_pct: Mapped[float] = mapped_column(Float, default=0.0)

    source_tournament_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_swiss_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_swiss_points: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )