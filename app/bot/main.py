from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from app.bot.commands.tournament_commands import TournamentCommands
from app.config import get_settings
from app.db.session import create_all, init_db
from app.models import entrant, entrant_member, pairing, seeding_submission, tournament  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('olir')

settings = get_settings()
init_db(settings.database_url)
create_all()

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, application_id=settings.application_id)
tree = bot.tree
_commands_synced = False


@bot.event
async def setup_hook():
    logger.info('setup_hook complete')


@bot.event
async def on_ready():
    global _commands_synced
    logger.info('Connected as %s (%s)', bot.user, bot.user.id if bot.user else 'unknown')
    if not _commands_synced:
        guild = discord.Object(id=settings.guild_id)
        try:
            tree.clear_commands(guild=guild)
        except Exception as exc:
            logger.warning('Could not clear guild commands before sync: %s', exc)
        tree.add_command(TournamentCommands(settings), guild=guild, override=True)
        synced = await tree.sync(guild=guild)
        logger.info('Synced %s command(s) to guild %s', len(synced), settings.guild_id)
        _commands_synced = True
    logger.info('O-Lir ready as %s', bot.user)


async def main():
    async with bot:
        await bot.start(settings.discord_token)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('Shutting down O-Lir')
