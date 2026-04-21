from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    discord_token: str
    application_id: int
    guild_id: int
    default_timezone: str
    database_url: str
    tournament_scheduling_channel_id: int
    tournament_participant_role_id: int
    tournament_admin_role_id: int
    server_admin_role_id: int
    tournament_organizer_role_ids: list[int]
    olir_internal_api_token: str
    olir_api_host: str
    olir_api_port: int
    proof_storage_root: str


def _required(name: str) -> str:
    value = os.getenv(name, '').strip()
    if not value:
        raise RuntimeError(f'Missing required environment variable: {name}')
    return value


def _parse_role_list(name: str) -> list[int]:
    raw = os.getenv(name, '').strip()
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(',') if x.strip()]


def get_settings() -> Settings:
    return Settings(
        discord_token=_required('DISCORD_TOKEN'),
        application_id=int(_required('DISCORD_APPLICATION_ID')),
        guild_id=int(_required('GUILD_ID')),
        default_timezone=os.getenv('DEFAULT_TIMEZONE', 'America/Chicago').strip(),
        database_url=os.getenv('DATABASE_URL', 'sqlite:///./olir.db').strip(),
        tournament_scheduling_channel_id=int(_required('TOURNAMENT_SCHEDULING_CHANNEL_ID')),
        tournament_participant_role_id=int(_required('TOURNAMENT_PARTICIPANT_ROLE_ID')),
        tournament_admin_role_id=int(_required('TOURNAMENT_ADMIN_ROLE_ID')),
        server_admin_role_id=int(_required('SERVER_ADMIN_ROLE_ID')),
        tournament_organizer_role_ids=_parse_role_list('TOURNAMENT_ORGANIZER_ROLE_IDS'),
        olir_internal_api_token=_required('OLIR_INTERNAL_API_TOKEN'),
        olir_api_host=os.getenv('OLIR_API_HOST', '127.0.0.1').strip(),
        olir_api_port=int(os.getenv('OLIR_API_PORT', '8101').strip()),
        proof_storage_root=os.getenv('PROOF_STORAGE_ROOT', './proofs').strip(),
    )
