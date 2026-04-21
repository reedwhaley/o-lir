from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SpeedGamingProfile(Base):
    __tablename__ = "speedgaming_profiles"

    discord_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    discord_username_snapshot: Mapped[str] = mapped_column(String(64))
    sg_display_name: Mapped[str] = mapped_column(String(200))
    sg_twitch_name: Mapped[str] = mapped_column(String(100))

    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )