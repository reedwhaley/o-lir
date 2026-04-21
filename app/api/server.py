from __future__ import annotations

from fastapi import FastAPI

from app.api.routes_pairings import router as pairing_router
from app.api.routes_speedgaming_profiles import router as speedgaming_profile_router
from app.config import get_settings
from app.db.session import create_all, init_db
from app.models import entrant, entrant_member, pairing, seeding_submission, speedgaming_profile, tournament  # noqa: F401

settings = get_settings()
init_db(settings.database_url)
create_all()

app = FastAPI(title='O-Lir Internal API', version='0.2.0')
app.include_router(pairing_router)
app.include_router(speedgaming_profile_router)


@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok'}
