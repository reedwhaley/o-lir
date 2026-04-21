from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SeedingSubmission(Base):
    __tablename__ = "seeding_submissions"
    __table_args__ = (
        UniqueConstraint("tournament_id", "entrant_id", "race_number", name="uq_one_submission_per_seed_race"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    tournament_id: Mapped[str] = mapped_column(String(32), index=True)
    entrant_id: Mapped[str] = mapped_column(String(32), index=True)

    async_seed_request_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    race_number: Mapped[int] = mapped_column(Integer, index=True)

    submitted_time_seconds: Mapped[float] = mapped_column(Float)
    sum_of_times_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    submitted_by_discord_id: Mapped[str] = mapped_column(String(32), index=True)
    submitted_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)

    vod_url: Mapped[str] = mapped_column(Text)

    outcome_code: Mapped[str] = mapped_column(String(32), default="submitted")
    status: Mapped[str] = mapped_column(String(32), default="pending")

    seeding_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    local_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_discord_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )