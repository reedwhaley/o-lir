from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EntrantMember(Base):
    __tablename__ = "entrant_members"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    entrant_id: Mapped[str] = mapped_column(String(32), index=True)
    discord_id: Mapped[str] = mapped_column(String(32), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=1)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)