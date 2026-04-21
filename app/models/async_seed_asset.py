from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AsyncSeedAsset(Base):
    __tablename__ = "async_seed_assets"
    __table_args__ = (
        UniqueConstraint("tournament_id", "race_number", name="uq_async_seed_asset_per_race"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(String(32), index=True)
    race_number: Mapped[int] = mapped_column(Integer, index=True)

    local_path: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    uploaded_by_discord_id: Mapped[str] = mapped_column(String(32), index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )