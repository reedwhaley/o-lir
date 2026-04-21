from __future__ import annotations

import asyncio
import logging

import discord
import uvicorn
from discord.ext import commands
from fastapi import FastAPI

from app.api.routes_identities import router as identity_router
from app.api.routes_pairings import router as pairing_router
from app.api.routes_speedgaming_profiles import router as speedgaming_profile_router
from app.bot.commands.tournament_commands import TournamentCommands
from app.config import get_settings
from app.db.session import create_all, init_db
from app.models import (
    async_seed_asset,
    async_seed_request,
    entrant,
    entrant_identity,
    entrant_member,
    pairing,
    pairing_result,
    seeding_submission,
    speedgaming_profile,
    tournament,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("olir")

settings = get_settings()

init_db(settings.database_url)
create_all()

api_app = FastAPI(title="O-Lir Internal API", version="0.2.0")
api_app.include_router(pairing_router)
api_app.include_router(identity_router)
api_app.include_router(speedgaming_profile_router)


@api_app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    application_id=settings.application_id,
)

tree = bot.tree
_commands_synced = False


@bot.event
async def setup_hook():
    logger.info("setup_hook complete")


@bot.event
async def on_ready():
    global _commands_synced

    logger.info("Connected as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")

    if not _commands_synced:
        guild = discord.Object(id=settings.guild_id)

        try:
            tree.clear_commands(guild=guild)
        except Exception as exc:
            logger.warning("Could not clear guild commands before sync: %s", exc)

        tree.add_command(
            TournamentCommands(settings),
            guild=guild,
            override=True,
        )

        synced = await tree.sync(guild=guild)
        logger.info("Synced %s command(s) to guild %s", len(synced), settings.guild_id)
        _commands_synced = True

    logger.info("O-Lir ready as %s", bot.user)


async def run_api() -> None:
    config = uvicorn.Config(
        api_app,
        host=settings.olir_api_host,
        port=settings.olir_api_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_bot() -> None:
    async with bot:
        await bot.start(settings.discord_token)


async def main() -> None:
    logger.info(
        "Starting O-Lir bot and API on %s:%s",
        settings.olir_api_host,
        settings.olir_api_port,
    )

    api_task = asyncio.create_task(run_api(), name="olir_api")
    bot_task = asyncio.create_task(run_bot(), name="olir_bot")

    done, pending = await asyncio.wait(
        {api_task, bot_task},
        return_when=asyncio.FIRST_EXCEPTION,
    )

    first_exception: BaseException | None = None

    for task in done:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            exc = None

        if exc is not None:
            first_exception = exc
            logger.exception("Task %s failed", task.get_name(), exc_info=exc)

    for task in pending:
        task.cancel()

    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    if first_exception is not None:
        raise first_exception


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down O-Lir")