from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EntrantIdentity(Base):
    __tablename__ = "entrant_identities"
    __table_args__ = (
        UniqueConstraint("entrant_id", "member_slot", name="uq_entrant_identity_member_slot"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    entrant_id: Mapped[str] = mapped_column(String(32), index=True)
    tournament_id: Mapped[str] = mapped_column(String(32), index=True)

    member_slot: Mapped[int] = mapped_column(Integer, default=1)

    discord_id: Mapped[str] = mapped_column(String(32), index=True)
    discord_username_snapshot: Mapped[str] = mapped_column(String(64))
    submitted_display_name: Mapped[str] = mapped_column(String(200))
    twitch_name: Mapped[str] = mapped_column(String(100))

    is_captain: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )