from __future__ import annotations

from typing import Literal

import discord
from discord import app_commands
from sqlalchemy import select

from app.config import Settings
from app.db.session import session_scope
from app.models.entrant import Entrant
from app.models.entrant_member import EntrantMember
from app.models.pairing import Pairing
from app.models.seeding_submission import SeedingSubmission
from app.models.tournament import Tournament
from app.services.async_seed_service import AsyncSeedService
from app.services.bracket_service import BracketService
from app.services.identity_service import IdentityRow, IdentityService
from app.services.pairing_service import PairingService
from app.services.permission_service import PermissionService
from app.services.seeding_service import SeedingService, format_seconds, parse_time_to_seconds
from app.services.speedgaming_profile_service import SpeedGamingProfileService
from app.services.swiss_service import SwissService
from app.services.thread_service import ThreadService
from app.services.tournament_service import TournamentService


DM_BLESSING = "Hear the words of O-Lir, last Sentinel of the Fortress Temple. May they serve you well."
TEAM_EVENT_NAME_KEYWORDS = ["bingo", "co-op", "coop", "co op"]

SEEDING_METHOD_CHOICES = [
    app_commands.Choice(name="Baja Special", value="baja_special"),
    app_commands.Choice(name="Average Score", value="average_score"),
    app_commands.Choice(name="Sum of Placements", value="sum_of_placements"),
    app_commands.Choice(name="Percent Max", value="percent_max"),
    app_commands.Choice(name="Percent Difference", value="percent_difference"),
    app_commands.Choice(name="Z-Sum", value="z_sum"),
    app_commands.Choice(name="Z-Percentile", value="z_percentile"),
    app_commands.Choice(name="Zipf's Law", value="zipfs_law"),
]

STANDINGS_TIEBREAK_CHOICES = [
    app_commands.Choice(name="Buchholz", value="buchholz"),
    app_commands.Choice(name="Sonneborn-Berger", value="sonneborn_berger"),
    app_commands.Choice(name="Buchholz then Sonneborn-Berger", value="buchholz_then_sonneborn_berger"),
]

SEEDING_DROP_COUNT_CHOICES = [
    app_commands.Choice(name="Drop 0", value=0),
    app_commands.Choice(name="Drop 1", value=1),
]


class TournamentCommandSupport:
    def _init_support(self, settings: Settings) -> None:
        self.settings = settings
        self.tournament_service = TournamentService()
        self.pairing_service = PairingService()
        self.thread_service = ThreadService()
        self.permission_service = PermissionService()
        self.seeding_service = SeedingService()
        self.swiss_service = SwissService()
        self.bracket_service = BracketService()
        self.async_seed_service = AsyncSeedService()
        self.identity_service = IdentityService()
        self.speedgaming_profile_service = SpeedGamingProfileService()

    def _staff_only(self, interaction: discord.Interaction) -> bool:
        return self.permission_service.can_manage_tournament(interaction) or self.permission_service.is_bot_admin(interaction)

    def _display_name_for_user(self, user: discord.abc.User) -> str:
        return getattr(user, "display_name", None) or getattr(user, "global_name", None) or user.name

    def _pairing_public_id(self, pairing: Pairing) -> str:
        return f"Match-{str(pairing.id)[:5].upper()}"

    def _pairing_matchup_label(self, entrant1_name: str, entrant2_name: str) -> str:
        return f"{entrant1_name} vs {entrant2_name}"

    def _pairing_stage_text(self, pairing: Pairing) -> str:
        stage = str(getattr(pairing, "stage", None) or getattr(pairing, "phase_type", None) or "").lower()
        round_number = int(getattr(pairing, "round_number", 0) or 0)

        if "loser" in stage:
            return f"Losers Bracket Round {round_number}"
        if "winner" in stage:
            return f"Winners Bracket Round {round_number}"
        if "grand" in stage:
            return "Grand Finals"
        if "top8" in stage or "top_8" in stage or "top-cut" in stage:
            return f"Top Cut Round {round_number}"

        return f"Week {round_number} Swiss"

    def _pairing_summary_text(self, pairing: Pairing, entrant1_name: str, entrant2_name: str) -> str:
        return f"{self._pairing_public_id(pairing)} | {self._pairing_matchup_label(entrant1_name, entrant2_name)} | {self._pairing_stage_text(pairing)}"

    def _pairing_thread_name(self, pairing: Pairing, entrant1_name: str, entrant2_name: str) -> str:
        raw = f"{self._pairing_public_id(pairing)} {entrant1_name} vs {entrant2_name} {self._pairing_stage_text(pairing)}"
        return raw[:100]

    def _match_tournament_label(self, tournament_name: str, category_slug: str) -> str:
        suffix = f" [{category_slug}]" if category_slug else ""
        return f"{tournament_name}{suffix}"[:100]

    def _match_entrant_label(self, display_name: str, seed: int | None) -> str:
        seed_text = f"Seed {seed}" if seed else "Unseeded"
        return f"{display_name} | {seed_text}"[:100]

    def _match_pairing_label(self, public_id: str, entrant1_name: str, entrant2_name: str, stage_text: str) -> str:
        return f"{public_id} | {entrant1_name} vs {entrant2_name} | {stage_text}"[:100]

    def _status_choices(self) -> list[str]:
        return ["pending", "approved", "rejected"]

    def _team_name_keyword_match(self, tournament_name: str | None) -> bool:
        name = (tournament_name or "").lower()
        return any(keyword in name for keyword in TEAM_EVENT_NAME_KEYWORDS)

    def _tournament_allows_single_entry(self, tournament: Tournament | None) -> bool:
        if tournament is None:
            return False
        category = str(getattr(tournament, "category_slug", "") or "").lower()
        if self._team_name_keyword_match(getattr(tournament, "name", "")):
            return False
        return category in {"mpr", "mp2r"}

    def _tournament_allows_team_entry(self, tournament: Tournament | None) -> bool:
        if tournament is None:
            return False
        category = str(getattr(tournament, "category_slug", "") or "").lower()
        if category == "mpcgr":
            return True
        return self._team_name_keyword_match(getattr(tournament, "name", ""))

    def _single_entry_error_text(self, tournament: Tournament | None) -> str:
        tournament_name = tournament.name if tournament else "that tournament"
        return (
            f"{tournament_name} does not allow singles signup. "
            f"Singles entry is restricted to mpr and mp2r tournaments that are not team-formatted events."
        )

    def _team_entry_error_text(self, tournament: Tournament | None) -> str:
        tournament_name = tournament.name if tournament else "that tournament"
        return (
            f"{tournament_name} does not allow team signup. "
            f"Team entry is restricted to mpcgr tournaments and tournaments whose names indicate team formats such as Bingo or Co-op."
        )

    def _find_requesting_entrant(self, tournament_id: str, user_id: str) -> Entrant | None:
        with session_scope() as session:
            direct = session.execute(
                select(Entrant).where(
                    Entrant.tournament_id == tournament_id,
                    Entrant.discord_id == str(user_id),
                    Entrant.is_active.is_(True),
                )
            ).scalar_one_or_none()

            if direct:
                session.expunge(direct)
                return direct

            team_entrant_ids = session.execute(
                select(EntrantMember.entrant_id).where(EntrantMember.discord_id == str(user_id))
            ).scalars().all()

            if not team_entrant_ids:
                return None

            entrant = session.execute(
                select(Entrant).where(
                    Entrant.tournament_id == tournament_id,
                    Entrant.id.in_(team_entrant_ids),
                    Entrant.is_active.is_(True),
                )
            ).scalar_one_or_none()

            if entrant:
                session.expunge(entrant)
            return entrant

    async def _dm_proof(self, interaction: discord.Interaction, submission: SeedingSubmission, entrant: Entrant) -> str:
        user = interaction.user
        file = discord.File(submission.local_path, filename=submission.original_filename)

        tournament = self.tournament_service.get_tournament(submission.tournament_id)
        tournament_name = tournament.name if tournament else submission.tournament_id

        body = (
            f"{DM_BLESSING}\n\n"
            f"Seeding proof for {entrant.display_name}\n"
            f"Tournament: {tournament_name}\n"
            f"Race: {submission.race_number}\n"
            f"Time: {format_seconds(submission.submitted_time_seconds)}\n"
            f"VOD: {submission.vod_url}\n"
            f"Status: {submission.status}\n"
            f"Submitted by: <@{submission.submitted_by_discord_id}>\n"
            f"Submitted at: <t:{int(submission.submitted_at_utc.timestamp())}:F>"
        )
        try:
            await user.send(body, file=file)
            return "Proof image sent to your DM."
        except Exception:
            return "Could not DM you. Please open your DMs and try again."

    async def _dm_async_seed(
        self,
        *,
        recipients: list[tuple[discord.abc.User, str]],
        tournament_id: str,
        entrant_name: str,
        race_number: int,
        local_path: str,
        original_filename: str,
    ) -> tuple[list[str], list[str]]:
        tournament = self.tournament_service.get_tournament(tournament_id)
        tournament_name = tournament.name if tournament else tournament_id

        base_body = (
            f"{DM_BLESSING}\n\n"
            f"Async seed for tournament {tournament_name}\n"
            f"Entrant: {entrant_name}\n"
            f"Race: {race_number}\n\n"
            f"This request has been logged by O-Lir.\n"
            f"When you submit your result, the bot will validate it against the entrant or team composition that requested this async."
        )

        sent_to: list[str] = []
        failed_to: list[str] = []

        for recipient, label in recipients:
            try:
                await recipient.send(
                    base_body,
                    file=discord.File(local_path, filename=original_filename),
                )
                sent_to.append(label)
            except Exception:
                failed_to.append(label)

        if failed_to and sent_to:
            failed_names_text = ", ".join(failed_to)
            followup = (
                f"{DM_BLESSING}\n\n"
                f"Delivery note: O-Lir could not DM {failed_names_text}. "
                f"Make sure they receive this async seed before running it."
            )
            for recipient, label in recipients:
                if label not in sent_to:
                    continue
                try:
                    await recipient.send(followup)
                except Exception:
                    pass

        return sent_to, failed_to

    def _list_tournament_pairings(self, tournament_id: str) -> list[Pairing]:
        return self.pairing_service.list_pairings(tournament_id)

    def _latest_round_pairings(self, tournament_id: str) -> tuple[int | None, list[Pairing]]:
        pairings = self._list_tournament_pairings(tournament_id)
        if not pairings:
            return None, []

        latest_round = max(int(getattr(pairing, "round_number", 0) or 0) for pairing in pairings)
        latest_pairings = [pairing for pairing in pairings if int(getattr(pairing, "round_number", 0) or 0) == latest_round]
        return latest_round, latest_pairings

    def _validate_latest_round_complete(self, tournament_id: str) -> tuple[bool, list[str]]:
        latest_round, pairings = self._latest_round_pairings(tournament_id)
        if latest_round is None or not pairings:
            return False, ["No existing round matches were found."]

        issues: list[str] = []

        for pairing in pairings:
            entrant1 = self.tournament_service.get_entrant(pairing.entrant1_id) if getattr(pairing, "entrant1_id", None) else None
            entrant2 = self.tournament_service.get_entrant(pairing.entrant2_id) if getattr(pairing, "entrant2_id", None) else None
            left_name = entrant1.display_name if entrant1 else "TBD"
            right_name = entrant2.display_name if entrant2 else "BYE"

            if not getattr(pairing, "entrant2_id", None):
                continue

            status = str(getattr(pairing, "status", "") or "").lower()
            approved = str(getattr(pairing, "result_approved", "") or "").lower()
            winner = getattr(pairing, "winner_entrant_id", None)

            if status != "completed":
                issues.append(f"{self._pairing_summary_text(pairing, left_name, right_name)} | status: {status or 'unknown'}")
                continue

            if approved not in {"true", "approved", "yes", "1"}:
                issues.append(f"{self._pairing_summary_text(pairing, left_name, right_name)} | result not approved")
                continue

            if not winner:
                issues.append(f"{self._pairing_summary_text(pairing, left_name, right_name)} | winner missing")

        return len(issues) == 0, issues

    def _ready_unthreaded_pairings(self, tournament_id: str) -> list[Pairing]:
        pairings = self._list_tournament_pairings(tournament_id)
        ready: list[Pairing] = []

        for pairing in pairings:
            status = str(getattr(pairing, "status", "") or "").lower()
            thread_id = getattr(pairing, "thread_id", None)
            entrant1_id = getattr(pairing, "entrant1_id", None)
            entrant2_id = getattr(pairing, "entrant2_id", None)

            if status == "ready" and not thread_id and entrant1_id and entrant2_id:
                ready.append(pairing)

        ready.sort(key=lambda p: (int(getattr(p, "round_number", 0) or 0), str(getattr(p, "id", ""))))
        return ready

    async def _open_thread_for_pairing(
        self,
        interaction: discord.Interaction,
        pairing: Pairing,
    ) -> str | None:
        if getattr(pairing, "thread_id", None):
            return getattr(pairing, "thread_id", None)

        parent_channel = interaction.guild.get_channel(self.settings.tournament_scheduling_channel_id) if interaction.guild else None
        if parent_channel is None or not isinstance(parent_channel, discord.TextChannel):
            raise RuntimeError("Tournament scheduling channel could not be resolved.")

        entrant1 = self.tournament_service.get_entrant(pairing.entrant1_id) if getattr(pairing, "entrant1_id", None) else None
        entrant2 = self.tournament_service.get_entrant(pairing.entrant2_id) if getattr(pairing, "entrant2_id", None) else None

        mention_parts: list[str] = []
        for entrant in [entrant1, entrant2]:
            if entrant is None:
                continue
            if entrant.is_team:
                for member in self.tournament_service.get_entrant_members(entrant.id):
                    mention_parts.append(f"<@{member.discord_id}>")
            elif entrant.discord_id:
                mention_parts.append(f"<@{entrant.discord_id}>")

        left_name = entrant1.display_name if entrant1 else "TBD"
        right_name = entrant2.display_name if entrant2 else "BYE"
        stage_text = self._pairing_stage_text(pairing)
        public_id = self._pairing_public_id(pairing)

        title = f"{public_id} {stage_text}"
        body = self.thread_service.build_pairing_thread_body(
            public_id=public_id,
            entrant1_name=left_name,
            entrant2_name=right_name,
            stage_text=stage_text,
            status_text="Waiting for schedule",
            lightbringer_match_id=getattr(pairing, "lightbringer_match_id", None),
            scheduled_start_text=(
                f"<t:{int(getattr(pairing, 'scheduled_start_at_utc').timestamp())}:F>"
                if getattr(pairing, "scheduled_start_at_utc", None)
                else None
            ),
        )

        starter, thread = await self.thread_service.open_pairing_thread(
            parent_channel=parent_channel,
            title=title,
            body=body,
            thread_name=self._pairing_thread_name(pairing, left_name, right_name),
            mention_text=" ".join(dict.fromkeys(mention_parts)) if mention_parts else None,
        )

        self.pairing_service.set_thread_context(
            pairing.id,
            thread_id=str(thread.id),
            thread_channel_id=str(parent_channel.id),
            starter_message_id=str(starter.id),
        )
        return str(thread.id)


    async def _auto_open_threads_for_pairings(
        self,
        interaction: discord.Interaction,
        pairings: list[Pairing],
    ) -> list[str]:
        opened: list[str] = []

        for pairing in pairings:
            entrant1_id = getattr(pairing, "entrant1_id", None)
            entrant2_id = getattr(pairing, "entrant2_id", None)
            if not entrant1_id or not entrant2_id:
                continue

            thread_id = await self._open_thread_for_pairing(interaction, pairing)
            if thread_id:
                entrant1 = self.tournament_service.get_entrant(pairing.entrant1_id) if pairing.entrant1_id else None
                entrant2 = self.tournament_service.get_entrant(pairing.entrant2_id) if pairing.entrant2_id else None
                left_name = entrant1.display_name if entrant1 else "TBD"
                right_name = entrant2.display_name if entrant2 else "BYE"
                opened.append(f"{self._pairing_summary_text(pairing, left_name, right_name)} -> <#{thread_id}>")

        return opened

    async def _autocomplete_tournament_ids(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower().strip()

        with session_scope() as session:
            tournament_rows = [
                (t.id, t.name, t.category_slug)
                for t in session.execute(
                    select(Tournament).where(
                        Tournament.guild_id == str(interaction.guild_id or self.settings.guild_id)
                    )
                ).scalars().all()
            ]

        tournament_rows.sort(key=lambda row: ((row[1] or "").lower(), row[0]))
        results: list[app_commands.Choice[str]] = []

        for tournament_id, tournament_name, category_slug in tournament_rows:
            haystack = f"{tournament_name} {category_slug}".lower()
            if not current_lower or current_lower in haystack:
                label = self._match_tournament_label(tournament_name, category_slug)
                results.append(app_commands.Choice(name=label, value=tournament_id))
            if len(results) >= 25:
                break

        return results

    async def _autocomplete_entrant_ids(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        tournament_id = getattr(interaction.namespace, "tournament_id", None)
        if not tournament_id:
            return []

        current_lower = current.lower().strip()

        with session_scope() as session:
            entrant_rows = [
                (e.id, e.display_name, e.seed)
                for e in session.execute(
                    select(Entrant).where(
                        Entrant.tournament_id == str(tournament_id),
                        Entrant.is_active.is_(True),
                    )
                ).scalars().all()
            ]

        entrant_rows.sort(key=lambda row: (row[2] or 999999, (row[1] or "").lower(), row[0]))
        results: list[app_commands.Choice[str]] = []

        for entrant_id, display_name, seed in entrant_rows:
            haystack = f"{display_name} {seed or ''}".lower()
            if not current_lower or current_lower in haystack:
                label = self._match_entrant_label(display_name, seed)
                results.append(app_commands.Choice(name=label, value=entrant_id))
            if len(results) >= 25:
                break

        return results

    async def _autocomplete_pairing_ids(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower().strip()

        with session_scope() as session:
            pairings = session.execute(select(Pairing)).scalars().all()

            entrant_ids = set()
            for pairing in pairings:
                if pairing.entrant1_id:
                    entrant_ids.add(pairing.entrant1_id)
                if pairing.entrant2_id:
                    entrant_ids.add(pairing.entrant2_id)

            entrant_map = {}
            if entrant_ids:
                entrant_map = {
                    e.id: e.display_name
                    for e in session.execute(
                        select(Entrant).where(Entrant.id.in_(entrant_ids))
                    ).scalars().all()
                }

            pairing_rows = [
                (
                    p.id,
                    p.entrant1_id,
                    p.entrant2_id,
                    getattr(p, "round_number", 0),
                    self._pairing_public_id(p),
                    self._pairing_stage_text(p),
                )
                for p in pairings
            ]

        pairing_rows.sort(key=lambda row: (row[3] or 0, row[0]))
        results: list[app_commands.Choice[str]] = []

        for pairing_id, entrant1_id, entrant2_id, _round_number, public_id, stage_text in pairing_rows:
            entrant1_name = entrant_map.get(entrant1_id or "", "TBD")
            entrant2_name = entrant_map.get(entrant2_id or "", "TBD")
            summary = self._match_pairing_label(public_id, entrant1_name, entrant2_name, stage_text)
            haystack = f"{public_id} {entrant1_name} {entrant2_name} {stage_text}".lower()

            if not current_lower or current_lower in haystack:
                results.append(app_commands.Choice(name=summary, value=pairing_id))
            if len(results) >= 25:
                break

        return results

    async def _autocomplete_submission_status(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower().strip()
        values = self._status_choices()
        return [
            app_commands.Choice(name=value, value=value)
            for value in values
            if not current_lower or current_lower in value.lower()
        ][:25]


class TournamentSetupGroup(TournamentCommandSupport, app_commands.Group):
    def __init__(self, settings: Settings):
        app_commands.Group.__init__(self, name="setup", description="Self-service tournament setup commands")
        self._init_support(settings)

    @app_commands.command(name="speedgaming", description="Create or update your SpeedGaming profile")
    @app_commands.describe(
        sg_display_name="Your SpeedGaming display name",
        sg_twitch_name="Your Twitch username for SG scheduling",
    )
    async def speedgaming(
        self,
        interaction: discord.Interaction,
        sg_display_name: str,
        sg_twitch_name: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        row = self.speedgaming_profile_service.upsert_profile(
            discord_id=str(interaction.user.id),
            discord_username_snapshot=str(interaction.user.name),
            sg_display_name=sg_display_name.strip(),
            sg_twitch_name=sg_twitch_name.strip(),
        )

        await interaction.edit_original_response(
            content=(
                f"Stored your SpeedGaming profile.\n"
                f"Discord username: {row.discord_username_snapshot}\n"
                f"SG display name: {row.sg_display_name}\n"
                f"SG Twitch name: {row.sg_twitch_name}"
            )
        )

    @app_commands.command(name="speedgaming_view", description="View your current SpeedGaming profile")
    async def speedgaming_view(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        row = self.speedgaming_profile_service.get_profile_by_discord_id(str(interaction.user.id))
        if row is None:
            await interaction.edit_original_response(
                content="You do not have a SpeedGaming profile on file yet. Run /tournament setup speedgaming first."
            )
            return

        await interaction.edit_original_response(
            content=(
                f"Your SpeedGaming profile:\n"
                f"Discord username: {row.discord_username_snapshot}\n"
                f"SG display name: {row.sg_display_name}\n"
                f"SG Twitch name: {row.sg_twitch_name}"
            )
        )

    @app_commands.command(name="speedgaming_clear", description="Delete your current SpeedGaming profile")
    async def speedgaming_clear(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        deleted = self.speedgaming_profile_service.clear_profile_by_discord_id(str(interaction.user.id))
        if not deleted:
            await interaction.edit_original_response(content="No SpeedGaming profile was found to clear.")
            return

        await interaction.edit_original_response(content="Cleared your SpeedGaming profile.")


class TournamentEntryGroup(TournamentCommandSupport, app_commands.Group):
    def __init__(self, settings: Settings):
        app_commands.Group.__init__(self, name="entry", description="Entry and signup commands")
        self._init_support(settings)

    @app_commands.command(name="signup", description="Sign yourself up as a singles entrant")
    @app_commands.describe(tournament_id="Tournament name", display_name="Optional display name override")
    async def signup(self, interaction: discord.Interaction, tournament_id: str, display_name: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True)

        tournament = self.tournament_service.get_tournament(tournament_id)
        if tournament is None:
            await interaction.edit_original_response(content="Tournament not found.")
            return

        if not self._tournament_allows_single_entry(tournament):
            await interaction.edit_original_response(content=self._single_entry_error_text(tournament))
            return

        sg_profile = self.speedgaming_profile_service.get_profile_by_discord_id(str(interaction.user.id))
        if sg_profile is None:
            await interaction.edit_original_response(
                content="You must complete /tournament setup speedgaming before signing up."
            )
            return

        final_name = display_name.strip() if display_name and display_name.strip() else sg_profile.sg_display_name

        try:
            entrant = self.tournament_service.signup_player(
                tournament_id=tournament_id,
                discord_id=str(interaction.user.id),
                display_name=final_name,
            )
        except ValueError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        self.identity_service.upsert_single_identity(
            entrant_id=str(entrant.id),
            tournament_id=str(tournament_id),
            discord_id=str(interaction.user.id),
            discord_username_snapshot=str(interaction.user.name),
            submitted_display_name=sg_profile.sg_display_name,
            twitch_name=sg_profile.sg_twitch_name,
        )

        await interaction.edit_original_response(content=f"You are signed up for {tournament.name} as {entrant.display_name}.")

    @app_commands.command(name="signup_team", description="Sign up a two-player team")
    @app_commands.describe(
        tournament_id="Tournament name",
        team_name="Team name",
        member1="First team member",
        member2="Second team member",
    )
    async def signup_team(
        self,
        interaction: discord.Interaction,
        tournament_id: str,
        team_name: str,
        member1: discord.Member,
        member2: discord.Member,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        tournament = self.tournament_service.get_tournament(tournament_id)
        if tournament is None:
            await interaction.edit_original_response(content="Tournament not found.")
            return

        if not self._tournament_allows_team_entry(tournament):
            await interaction.edit_original_response(content=self._team_entry_error_text(tournament))
            return

        sg1 = self.speedgaming_profile_service.get_profile_by_discord_id(str(member1.id))
        sg2 = self.speedgaming_profile_service.get_profile_by_discord_id(str(member2.id))

        if sg1 is None:
            await interaction.edit_original_response(
                content=f"{member1.display_name} has not completed /tournament setup speedgaming yet."
            )
            return

        if sg2 is None:
            await interaction.edit_original_response(
                content=f"{member2.display_name} has not completed /tournament setup speedgaming yet."
            )
            return

        try:
            entrant = self.tournament_service.signup_team(
                tournament_id=tournament_id,
                team_name=team_name,
                captain_discord_id=str(interaction.user.id),
                member1_id=str(member1.id),
                member1_name=sg1.sg_display_name,
                member2_id=str(member2.id),
                member2_name=sg2.sg_display_name,
            )
        except ValueError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        self.identity_service.replace_team_identities(
            entrant_id=str(entrant.id),
            tournament_id=str(tournament_id),
            members=[
                IdentityRow(
                    entrant_id=str(entrant.id),
                    tournament_id=str(tournament_id),
                    member_slot=1,
                    discord_id=str(member1.id),
                    discord_username_snapshot=str(member1.name),
                    submitted_display_name=sg1.sg_display_name,
                    twitch_name=sg1.sg_twitch_name,
                    is_captain=str(member1.id) == str(interaction.user.id),
                ),
                IdentityRow(
                    entrant_id=str(entrant.id),
                    tournament_id=str(tournament_id),
                    member_slot=2,
                    discord_id=str(member2.id),
                    discord_username_snapshot=str(member2.name),
                    submitted_display_name=sg2.sg_display_name,
                    twitch_name=sg2.sg_twitch_name,
                    is_captain=str(member2.id) == str(interaction.user.id),
                ),
            ],
        )

        await interaction.edit_original_response(
            content=f"Team {entrant.display_name} has been signed up for {tournament.name}.\nMembers: {sg1.sg_display_name}, {sg2.sg_display_name}"
        )

    @app_commands.command(name="withdraw", description="Withdraw your active entry from a tournament while signup is open")
    @app_commands.describe(tournament_id="Tournament name")
    async def withdraw(self, interaction: discord.Interaction, tournament_id: str) -> None:
        await interaction.response.defer(ephemeral=True)

        tournament = self.tournament_service.get_tournament(tournament_id)
        tournament_name = tournament.name if tournament else "that tournament"

        try:
            entrant = self.tournament_service.withdraw_user_entry(
                tournament_id=tournament_id,
                discord_id=str(interaction.user.id),
            )
        except ValueError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        await interaction.edit_original_response(content=f"Your entry {entrant.display_name} has been withdrawn from {tournament_name}.")

    @app_commands.command(name="my_entry", description="Show your active entry for a tournament")
    @app_commands.describe(tournament_id="Tournament name")
    async def my_entry(self, interaction: discord.Interaction, tournament_id: str) -> None:
        await interaction.response.defer(ephemeral=True)

        tournament = self.tournament_service.get_tournament(tournament_id)
        tournament_name = tournament.name if tournament else "that tournament"

        entrant = self.tournament_service.find_entry_for_user(
            tournament_id=tournament_id,
            discord_id=str(interaction.user.id),
        )
        if entrant is None:
            await interaction.edit_original_response(content=f"You do not have an active entry in {tournament_name}.")
            return

        if entrant.is_team:
            members = self.tournament_service.get_entrant_members(entrant.id)
            member_text = ", ".join(member.display_name for member in members) if members else "No members found"
            await interaction.edit_original_response(
                content=f"Your active entry in {tournament_name} is team {entrant.display_name}.\nMembers: {member_text}"
            )
            return

        await interaction.edit_original_response(content=f"Your active entry in {tournament_name} is {entrant.display_name}.")

    @app_commands.command(name="entrants", description="List active entrants for a tournament")
    @app_commands.describe(tournament_id="Tournament name")
    async def entrants(self, interaction: discord.Interaction, tournament_id: str) -> None:
        await interaction.response.defer(ephemeral=True)

        tournament = self.tournament_service.get_tournament(tournament_id)
        tournament_name = tournament.name if tournament else "that tournament"

        entrants = self.tournament_service.list_entrants(tournament_id, active_only=True)
        if not entrants:
            await interaction.edit_original_response(content=f"No active entrants found for {tournament_name}.")
            return

        lines: list[str] = [f"Entrants for {tournament_name}:"]
        for entrant in entrants[:50]:
            prefix = f"Seed {entrant.seed}" if entrant.seed else "Unseeded"
            if entrant.is_team:
                members = self.tournament_service.get_entrant_members(entrant.id)
                member_text = ", ".join(member.display_name for member in members) if members else "No members"
                lines.append(f"{prefix} | {entrant.display_name} | {member_text}")
            else:
                lines.append(f"{prefix} | {entrant.display_name}")

        await interaction.edit_original_response(content="\n".join(lines))

    @signup.autocomplete("tournament_id")
    @signup_team.autocomplete("tournament_id")
    @withdraw.autocomplete("tournament_id")
    @my_entry.autocomplete("tournament_id")
    @entrants.autocomplete("tournament_id")
    async def tournament_id_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._autocomplete_tournament_ids(interaction, current)


class TournamentSeedingGroup(TournamentCommandSupport, app_commands.Group):
    def __init__(self, settings: Settings):
        app_commands.Group.__init__(self, name="seeding", description="Async seed and submission commands")
        self._init_support(settings)

    @app_commands.command(name="upload_async_seed", description="Upload or replace an async seed file for a seeding race")
    @app_commands.describe(
        tournament_id="Tournament name",
        race_number="Async seed race number",
        seed_file="The async seed file to store privately",
        notes="Optional staff notes",
        replace_existing="Replace the existing uploaded async seed for this race",
    )
    async def upload_async_seed(
        self,
        interaction: discord.Interaction,
        tournament_id: str,
        race_number: app_commands.Range[int, 1, 10],
        seed_file: discord.Attachment,
        notes: str | None = None,
        replace_existing: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        tournament = self.tournament_service.get_tournament(tournament_id)
        tournament_name = tournament.name if tournament else "that tournament"

        file_bytes = await seed_file.read()

        try:
            asset = self.async_seed_service.upload_asset(
                tournament_id=tournament_id,
                race_number=race_number,
                uploaded_by_discord_id=str(interaction.user.id),
                raw_bytes=file_bytes,
                original_filename=seed_file.filename,
                content_type=seed_file.content_type or "application/octet-stream",
                notes=notes,
                replace_existing=replace_existing,
            )
        except ValueError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        await interaction.edit_original_response(content=f"Stored async seed for {tournament_name}, race {race_number}.\nFilename: {asset.original_filename}")

    @app_commands.command(name="request_async_seed", description="Request an async seed by DM for your entrant or team")
    @app_commands.describe(tournament_id="Tournament name", race_number="Async seed race number")
    async def request_async_seed(
        self,
        interaction: discord.Interaction,
        tournament_id: str,
        race_number: app_commands.Range[int, 1, 10],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        entrant = self._find_requesting_entrant(tournament_id, str(interaction.user.id))
        if entrant is None:
            await interaction.edit_original_response(content="You are not registered as an active entrant or team member in that tournament.")
            return

        try:
            request, asset = self.async_seed_service.create_request(
                tournament_id=tournament_id,
                entrant_id=entrant.id,
                race_number=race_number,
                requested_by_discord_id=str(interaction.user.id),
            )
        except ValueError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        recipients: list[tuple[discord.abc.User, str]] = []
        if entrant.is_team:
            members = self.tournament_service.get_entrant_members(entrant.id)
            seen_ids: set[int] = set()
            for member in members:
                try:
                    user_obj = interaction.client.get_user(int(member.discord_id)) or await interaction.client.fetch_user(int(member.discord_id))
                except Exception:
                    continue
                if user_obj.id in seen_ids:
                    continue
                seen_ids.add(user_obj.id)
                recipients.append((user_obj, member.display_name))
        else:
            recipients.append((interaction.user, self._display_name_for_user(interaction.user)))

        sent_to, failed_to = await self._dm_async_seed(
            recipients=recipients,
            tournament_id=tournament_id,
            entrant_name=entrant.display_name,
            race_number=race_number,
            local_path=asset.local_path,
            original_filename=asset.original_filename,
        )

        if not sent_to:
            try:
                self.async_seed_service.clear_request(
                    tournament_id=tournament_id,
                    entrant_id=entrant.id,
                    race_number=race_number,
                )
            except Exception:
                pass
            await interaction.edit_original_response(
                content="Could not DM the async seed to any recipient. Please make sure at least one team member has DMs open and try again."
            )
            return

        response = f"Async seed race {race_number} sent for entrant {entrant.display_name}."
        if sent_to:
            response += f"\nDelivered to: {', '.join(sent_to)}"
        if failed_to:
            response += f"\nWarning: Could not DM {', '.join(failed_to)}."
        await interaction.edit_original_response(content=response)

    @app_commands.command(name="list_async_seed_requests", description="List logged async seed requests for a tournament")
    @app_commands.describe(tournament_id="Tournament name", race_number="Optional race number filter")
    async def list_async_seed_requests(
        self,
        interaction: discord.Interaction,
        tournament_id: str,
        race_number: int | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        tournament = self.tournament_service.get_tournament(tournament_id)
        tournament_name = tournament.name if tournament else "that tournament"

        requests = self.async_seed_service.list_requests(tournament_id=tournament_id, race_number=race_number)
        if not requests:
            await interaction.edit_original_response(content=f"No async seed requests found for {tournament_name}.")
            return

        with session_scope() as session:
            entrant_map = {
                e.id: e.display_name
                for e in session.execute(select(Entrant).where(Entrant.tournament_id == tournament_id)).scalars().all()
            }

        lines = [f"Async seed requests for {tournament_name}:"]
        for req in requests[:50]:
            entrant_name = entrant_map.get(req.entrant_id, req.entrant_id)
            lines.append(
                f"Race {req.race_number} | {entrant_name} | requested by <@{req.requested_by_discord_id}> | <t:{int(req.requested_at_utc.timestamp())}:F>"
            )

        await interaction.edit_original_response(content="\n".join(lines))

    @app_commands.command(name="clear_async_seed_request", description="Clear a logged async seed request so it can be reissued")
    @app_commands.describe(tournament_id="Tournament name", entrant_id="Entrant name", race_number="Async seed race number")
    async def clear_async_seed_request(
        self,
        interaction: discord.Interaction,
        tournament_id: str,
        entrant_id: str,
        race_number: app_commands.Range[int, 1, 10],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        entrant = self.tournament_service.get_entrant(entrant_id)
        entrant_name = entrant.display_name if entrant else "that entrant"

        try:
            self.async_seed_service.clear_request(
                tournament_id=tournament_id,
                entrant_id=entrant_id,
                race_number=race_number,
            )
        except ValueError as exc:
            await interaction.edit_original_response(content=str(exc))
            return
        await interaction.edit_original_response(content=f"Cleared async seed request for {entrant_name}, race {race_number}.")

    @app_commands.command(name="submit_seed", description="Submit a seeding race time, VOD link, and proof image")
    @app_commands.describe(
        tournament_id="Tournament name",
        entrant_id="Entrant name",
        race_number="Seeding race number starting at 1",
        time_value="Time or sum-of-times in mm:ss, hh:mm:ss, or raw seconds",
        vod_url="Required link to the VOD for this async seed run",
        proof_image="Screenshot proof image",
    )
    async def submit_seed(
        self,
        interaction: discord.Interaction,
        tournament_id: str,
        entrant_id: str,
        race_number: app_commands.Range[int, 1, 10],
        time_value: str,
        vod_url: str,
        proof_image: discord.Attachment,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not (
            self.permission_service.can_submit_for_entrant(interaction, entrant_id)
            or self.tournament_service.can_user_submit_for_entrant(entrant_id, str(interaction.user.id))
        ):
            await interaction.edit_original_response(content="You are not allowed to submit seeding proof for that entrant.")
            return

        try:
            seconds = parse_time_to_seconds(time_value)
        except ValueError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        file_bytes = await proof_image.read()
        try:
            submission = self.seeding_service.submit_seeding_time(
                tournament_id=tournament_id,
                entrant_id=entrant_id,
                race_number=race_number,
                submitted_time_seconds=seconds,
                submitted_by_discord_id=str(interaction.user.id),
                vod_url=vod_url,
                original_filename=proof_image.filename,
                content_type=proof_image.content_type or "application/octet-stream",
                file_bytes=file_bytes,
            )
        except ValueError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        entrant = self.tournament_service.get_entrant(entrant_id)
        entrant_name = entrant.display_name if entrant else entrant_id

        await interaction.edit_original_response(
            content=f"Seeding submission recorded for {entrant_name}, race {race_number}. Submitted value: `{format_seconds(submission.submitted_time_seconds)}`. VOD saved. Staff will review the proof privately."
        )

    @app_commands.command(name="submissions", description="List seeding submissions for a tournament")
    @app_commands.describe(tournament_id="Tournament name", entrant_id="Entrant name", status="Submission status")
    async def submissions(
        self,
        interaction: discord.Interaction,
        tournament_id: str,
        entrant_id: str | None = None,
        status: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self.permission_service.can_view_seeding_proof(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        tournament = self.tournament_service.get_tournament(tournament_id)
        tournament_name = tournament.name if tournament else "that tournament"

        submissions = self.seeding_service.list_submissions(tournament_id, entrant_id=entrant_id, status=status)
        if not submissions:
            await interaction.edit_original_response(content=f"No submissions found for {tournament_name}.")
            return

        with session_scope() as session:
            entrant_rows = session.execute(
                select(Entrant).where(Entrant.tournament_id == tournament_id)
            ).scalars().all()
            entrant_map = {str(e.id): e.display_name for e in entrant_rows}

        lines = [f"Seeding submissions for {tournament_name}:"]
        for submission in submissions[:30]:
            entrant_name = entrant_map.get(str(submission.entrant_id), str(submission.entrant_id))
            lines.append(
                f"{entrant_name} | race {submission.race_number} | {format_seconds(submission.submitted_time_seconds)} | {submission.status} | VOD saved"
            )

        await interaction.edit_original_response(content="\n".join(lines))

    @app_commands.command(name="show_submission", description="DM a seeding proof image to authorized staff")
    @app_commands.describe(submission_id="Submission to show")
    async def show_submission(self, interaction: discord.Interaction, submission_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self.permission_service.can_view_seeding_proof(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        submission = self.seeding_service.get_submission(submission_id)
        if submission is None:
            await interaction.edit_original_response(content="Submission not found.")
            return

        entrant = self.tournament_service.get_entrant(submission.entrant_id)
        if entrant is None:
            await interaction.edit_original_response(content="Entrant not found for submission.")
            return

        result = await self._dm_proof(interaction, submission, entrant)
        await interaction.edit_original_response(content=result)

    @app_commands.command(name="approve_submission", description="Approve a seeding submission")
    @app_commands.describe(submission_id="Submission to approve", notes="Optional staff notes")
    async def approve_submission(self, interaction: discord.Interaction, submission_id: int, notes: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self.permission_service.can_view_seeding_proof(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return
        try:
            submission = self.seeding_service.approve_submission(submission_id, str(interaction.user.id), notes)
        except LookupError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        entrant = self.tournament_service.get_entrant(submission.entrant_id)
        entrant_name = entrant.display_name if entrant else submission.entrant_id
        await interaction.edit_original_response(content=f"Approved the submission for {entrant_name}.")

    @app_commands.command(name="reject_submission", description="Reject a seeding submission")
    @app_commands.describe(submission_id="Submission to reject", notes="Optional staff notes")
    async def reject_submission(self, interaction: discord.Interaction, submission_id: int, notes: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self.permission_service.can_view_seeding_proof(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return
        try:
            submission = self.seeding_service.reject_submission(submission_id, str(interaction.user.id), notes)
        except LookupError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        entrant = self.tournament_service.get_entrant(submission.entrant_id)
        entrant_name = entrant.display_name if entrant else submission.entrant_id
        await interaction.edit_original_response(content=f"Rejected the submission for {entrant_name}.")

    @app_commands.command(name="clear_submission", description="Clear a seeding submission so the entrant can resubmit")
    @app_commands.describe(submission_id="Submission to clear")
    async def clear_submission(self, interaction: discord.Interaction, submission_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self.permission_service.can_view_seeding_proof(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        submission = self.seeding_service.get_submission(submission_id)
        entrant_name = None
        if submission is not None:
            entrant = self.tournament_service.get_entrant(submission.entrant_id)
            entrant_name = entrant.display_name if entrant else submission.entrant_id

        try:
            self.seeding_service.clear_submission(submission_id)
        except LookupError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        if entrant_name:
            await interaction.edit_original_response(content=f"Cleared the submission for {entrant_name}.")
        else:
            await interaction.edit_original_response(content="Cleared the submission.")

    @app_commands.command(name="compute_seeds", description="Compute official seeds from approved seeding submissions")
    @app_commands.describe(tournament_id="Tournament name")
    async def compute_seeds(self, interaction: discord.Interaction, tournament_id: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        tournament = self.tournament_service.get_tournament(tournament_id)
        tournament_name = tournament.name if tournament else "that tournament"

        try:
            rows = self.seeding_service.compute_seeds(tournament_id)
        except (LookupError, ValueError) as exc:
            await interaction.edit_original_response(content=str(exc))
            return
        lines = [f"Computed seeds for {tournament_name}:"]
        lines.extend(f"{row.seed}. {row.display_name} - {row.score:.4f} pts" for row in rows[:24])
        await interaction.edit_original_response(content="\n".join(lines))

    @upload_async_seed.autocomplete("tournament_id")
    @request_async_seed.autocomplete("tournament_id")
    @list_async_seed_requests.autocomplete("tournament_id")
    @clear_async_seed_request.autocomplete("tournament_id")
    @submit_seed.autocomplete("tournament_id")
    @submissions.autocomplete("tournament_id")
    @compute_seeds.autocomplete("tournament_id")
    async def tournament_id_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._autocomplete_tournament_ids(interaction, current)

    @clear_async_seed_request.autocomplete("entrant_id")
    @submit_seed.autocomplete("entrant_id")
    @submissions.autocomplete("entrant_id")
    async def entrant_id_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._autocomplete_entrant_ids(interaction, current)

    @submissions.autocomplete("status")
    async def submission_status_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._autocomplete_submission_status(interaction, current)


class TournamentBracketGroup(TournamentCommandSupport, app_commands.Group):
    def __init__(self, settings: Settings):
        app_commands.Group.__init__(self, name="bracket", description="Standings, matches, and advancement")
        self._init_support(settings)

    @app_commands.command(name="matches", description="List matches for a tournament")
    @app_commands.describe(
        tournament_id="Tournament name",
        round_number="Optional round filter",
        unresolved_only="Only show matches that are not fully completed and approved",
    )
    async def matches(
        self,
        interaction: discord.Interaction,
        tournament_id: str,
        round_number: int | None = None,
        unresolved_only: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        tournament = self.tournament_service.get_tournament(tournament_id)
        tournament_name = tournament.name if tournament else "that tournament"

        pairings = self.pairing_service.list_pairings(
            tournament_id,
            round_number=round_number,
            unresolved_only=unresolved_only,
        )
        if not pairings:
            await interaction.edit_original_response(content=f"No matches found for {tournament_name}.")
            return

        lines: list[str] = [f"Matches for {tournament_name}:"]
        for pairing in pairings[:50]:
            entrant1 = self.tournament_service.get_entrant(pairing.entrant1_id) if pairing.entrant1_id else None
            entrant2 = self.tournament_service.get_entrant(pairing.entrant2_id) if pairing.entrant2_id else None
            left = entrant1.display_name if entrant1 else "TBD"
            right = entrant2.display_name if entrant2 else "BYE"
            status = str(getattr(pairing, "status", "") or "")
            approved = str(getattr(pairing, "result_approved", "") or "")
            lines.append(f"{self._pairing_summary_text(pairing, left, right)} | status: {status} | approved: {approved}")

        await interaction.edit_original_response(content="\n".join(lines))

    @app_commands.command(name="match_details", description="Show details for a specific match")
    @app_commands.describe(pairing_id="Match to show")
    async def match_details(self, interaction: discord.Interaction, pairing_id: str) -> None:
        await interaction.response.defer(ephemeral=True)

        pairing = self.pairing_service.get_pairing(pairing_id)
        if pairing is None:
            await interaction.edit_original_response(content="Match not found.")
            return

        entrant1 = self.tournament_service.get_entrant(pairing.entrant1_id) if pairing.entrant1_id else None
        entrant2 = self.tournament_service.get_entrant(pairing.entrant2_id) if pairing.entrant2_id else None
        result = self.pairing_service.get_pairing_result(pairing_id)

        left = entrant1.display_name if entrant1 else "TBD"
        right = entrant2.display_name if entrant2 else "BYE"

        winner_name = "-"
        winner_id = getattr(pairing, "winner_entrant_id", None)
        if winner_id:
            winner = self.tournament_service.get_entrant(winner_id)
            winner_name = winner.display_name if winner else "-"

        lines = [
            f"Match: {self._pairing_public_id(pairing)}",
            f"Label: {self._pairing_matchup_label(left, right)}",
            f"Stage: {self._pairing_stage_text(pairing)}",
            f"Status: {getattr(pairing, 'status', '-')}",
            f"Approved: {getattr(pairing, 'result_approved', '-')}",
            f"Winner: {winner_name}",
            f"Thread: <#{pairing.thread_id}>" if getattr(pairing, "thread_id", None) else "Thread: -",
        ]

        if result:
            lines.extend(
                [
                    f"Result Source: {getattr(result, 'source', '-')}",
                    f"Winner Side: {getattr(result, 'winner_side', '-')}",
                    f"Entrant 1 Time: {format_seconds(getattr(result, 'entrant1_finish_time_seconds', None))}",
                    f"Entrant 2 Time: {format_seconds(getattr(result, 'entrant2_finish_time_seconds', None))}",
                    f"Override: {getattr(result, 'is_override', False)}",
                ]
            )

        await interaction.edit_original_response(content="\n".join(lines))

    @app_commands.command(name="record_match_result", description="Manually record a match result when import is unavailable")
    @app_commands.describe(
        pairing_id="Match to record",
        winner_entrant_id="Winner entrant",
        entrant1_time="Finish time for entrant 1 in mm:ss, hh:mm:ss, or raw seconds",
        entrant2_time="Finish time for entrant 2 in mm:ss, hh:mm:ss, or raw seconds",
        notes="Optional staff notes explaining the manual entry",
        override_existing="Replace an already approved result if necessary",
        auto_approve="Immediately approve this manual result",
    )
    async def record_match_result(
        self,
        interaction: discord.Interaction,
        pairing_id: str,
        winner_entrant_id: str,
        entrant1_time: str,
        entrant2_time: str,
        notes: str | None = None,
        override_existing: bool = False,
        auto_approve: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        try:
            entrant1_seconds = parse_time_to_seconds(entrant1_time)
            entrant2_seconds = parse_time_to_seconds(entrant2_time)
        except ValueError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        try:
            pairing, result = self.pairing_service.record_manual_result(
                pairing_id=pairing_id,
                winner_entrant_id=winner_entrant_id,
                entrant1_finish_time_seconds=entrant1_seconds,
                entrant2_finish_time_seconds=entrant2_seconds,
                recorded_by_discord_id=str(interaction.user.id),
                notes=notes,
                override_existing=override_existing,
                auto_approve=auto_approve,
            )
        except (LookupError, ValueError) as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        winner = self.tournament_service.get_entrant(winner_entrant_id)
        winner_name = winner.display_name if winner else "the selected entrant"
        approved_text = "approved" if str(getattr(pairing, "result_approved", "") or "").lower() in {"true", "approved", "yes", "1"} else "pending approval"
        await interaction.edit_original_response(
            content=f"Recorded manual result for {self._pairing_public_id(pairing)}.\nWinner: {winner_name}\nResult source: {result.source}\nStatus: {approved_text}"
        )

    @app_commands.command(name="approve_match_result", description="Approve a recorded match result for tournament progression")
    @app_commands.describe(pairing_id="Match to approve", notes="Optional staff notes")
    async def approve_match_result(self, interaction: discord.Interaction, pairing_id: str, notes: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        try:
            pairing, _result = self.pairing_service.approve_match_result(
                pairing_id=pairing_id,
                approved_by_discord_id=str(interaction.user.id),
                notes=notes,
            )
        except (LookupError, ValueError) as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        entrant1 = self.tournament_service.get_entrant(pairing.entrant1_id) if pairing.entrant1_id else None
        entrant2 = self.tournament_service.get_entrant(pairing.entrant2_id) if pairing.entrant2_id else None
        left = entrant1.display_name if entrant1 else "TBD"
        right = entrant2.display_name if entrant2 else "BYE"
        await interaction.edit_original_response(content=f"Approved match result for {self._pairing_summary_text(pairing, left, right)}.")

    @app_commands.command(name="clear_match_result", description="Clear a recorded match result so it can be corrected")
    @app_commands.describe(pairing_id="Match to clear")
    async def clear_match_result(self, interaction: discord.Interaction, pairing_id: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        try:
            pairing = self.pairing_service.clear_match_result(pairing_id=pairing_id)
        except LookupError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        entrant1 = self.tournament_service.get_entrant(pairing.entrant1_id) if pairing.entrant1_id else None
        entrant2 = self.tournament_service.get_entrant(pairing.entrant2_id) if pairing.entrant2_id else None
        left = entrant1.display_name if entrant1 else "TBD"
        right = entrant2.display_name if entrant2 else "BYE"
        await interaction.edit_original_response(content=f"Cleared recorded result for {self._pairing_summary_text(pairing, left, right)}.")

    @app_commands.command(name="generate_swiss_round", description="Generate the next swiss round pairings and open scheduling threads")
    @app_commands.describe(tournament_id="Tournament name")
    async def generate_swiss_round(self, interaction: discord.Interaction, tournament_id: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        tournament = self.tournament_service.get_tournament(tournament_id)
        tournament_name = tournament.name if tournament else "that tournament"

        try:
            created = self.swiss_service.generate_next_round_pairings(tournament_id)
        except (LookupError, ValueError) as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        try:
            opened = await self._auto_open_threads_for_pairings(interaction, list(created))
        except Exception as exc:
            await interaction.edit_original_response(
                content=f"Generated {len(created)} swiss pairings for {tournament_name}, but thread creation failed: {exc}"
            )
            return

        if opened:
            await interaction.edit_original_response(
                content=f"Generated {len(created)} swiss pairings for {tournament_name}.\nOpened scheduling threads:\n" + "\n".join(opened)
            )
        else:
            await interaction.edit_original_response(content=f"Generated {len(created)} swiss pairings for {tournament_name}. No ready pairings required threads.")

    @app_commands.command(name="advance_to_next_round", description="Advance after staff verification, create next pairings, and open new scheduling threads")
    @app_commands.describe(tournament_id="Tournament name")
    async def advance_to_next_round(self, interaction: discord.Interaction, tournament_id: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        tournament = self.tournament_service.get_tournament(tournament_id)
        if tournament is None:
            await interaction.edit_original_response(content="Tournament not found.")
            return

        latest_round, latest_pairings = self._latest_round_pairings(tournament_id)

        if latest_round is None or not latest_pairings:
            stage_type = str(getattr(tournament, "stage_type", "main") or "main").lower()
            if stage_type == "top8":
                await interaction.edit_original_response(content=f"No pairings exist yet for the Top 8 phase of {tournament.name}.")
                return

            try:
                created = self.swiss_service.generate_next_round_pairings(tournament_id)
                opened = await self._auto_open_threads_for_pairings(interaction, list(created))
            except (LookupError, ValueError, RuntimeError) as exc:
                await interaction.edit_original_response(content=str(exc))
                return

            await interaction.edit_original_response(
                content=f"Started {tournament.name} with {len(created)} pairings.\n" + ("\n".join(opened) if opened else "No threads were opened.")
            )
            return

        can_advance, issues = self._validate_latest_round_complete(tournament_id)
        if not can_advance:
            await interaction.edit_original_response(
                content="Cannot advance tournament yet.\n\nThe following matches are still unresolved:\n" + "\n".join(f"- {issue}" for issue in issues[:25])
            )
            return

        stage_type = str(getattr(tournament, "stage_type", "main") or "main").lower()

        if stage_type == "top8":
            ready_pairings = self._ready_unthreaded_pairings(tournament_id)
            if not ready_pairings:
                await interaction.edit_original_response(content=f"All current results are verified, but no newly ready Top 8 matches are waiting for threads in {tournament.name}.")
                return

            try:
                opened = await self._auto_open_threads_for_pairings(interaction, ready_pairings)
            except RuntimeError as exc:
                await interaction.edit_original_response(content=str(exc))
                return

            await interaction.edit_original_response(
                content=f"Advanced the Top 8 phase of {tournament.name}.\nOpened {len(opened)} new scheduling threads:\n" + "\n".join(opened)
            )
            return

        swiss_round_count = int(getattr(tournament, "swiss_round_count", 0) or 0)

        if latest_round < swiss_round_count:
            try:
                created = self.swiss_service.generate_next_round_pairings(tournament_id)
                opened = await self._auto_open_threads_for_pairings(interaction, list(created))
            except (LookupError, ValueError, RuntimeError) as exc:
                await interaction.edit_original_response(content=str(exc))
                return

            await interaction.edit_original_response(
                content=f"Advanced {tournament.name} to swiss round {latest_round + 1}.\nOpened {len(opened)} scheduling threads:\n"
                + ("\n".join(opened) if opened else "No ready pairings required threads.")
            )
            return

        try:
            created = self.bracket_service.create_top8_winners_round1(tournament_id)
            opened = await self._auto_open_threads_for_pairings(interaction, list(created))
        except (LookupError, ValueError, RuntimeError) as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        await interaction.edit_original_response(
            content=f"Swiss is complete for {tournament.name}.\nGenerated Top Cut and opened {len(opened)} scheduling threads:\n"
            + ("\n".join(opened) if opened else "No ready pairings required threads.")
        )

    @app_commands.command(name="standings", description="View the current standings or ranking state for a tournament")
    @app_commands.describe(tournament_id="Tournament name")
    async def standings(self, interaction: discord.Interaction, tournament_id: str) -> None:
        await interaction.response.defer(ephemeral=True)

        tournament = self.tournament_service.get_tournament(tournament_id)
        tournament_name = tournament.name if tournament else "that tournament"

        standings = self.swiss_service.compute_standings(tournament_id)
        if not standings:
            await interaction.edit_original_response(content=f"No standings available for {tournament_name}.")
            return
        lines = [f"Standings for {tournament_name}:"]
        for index, row in enumerate(standings[:24], start=1):
            lines.append(f"{index}. {row.display_name} | MP {row.match_points} | Buchholz {row.buchholz} | SB {row.sonneborn_berger} | Seed {row.seed or '-'}")
        await interaction.edit_original_response(content="\n".join(lines))

    @app_commands.command(name="generate_top_cut", description="Seed the top 8 into winners bracket round 1 pairings and open scheduling threads")
    @app_commands.describe(tournament_id="Tournament name")
    async def generate_top_cut(self, interaction: discord.Interaction, tournament_id: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        tournament = self.tournament_service.get_tournament(tournament_id)
        tournament_name = tournament.name if tournament else "that tournament"

        try:
            created = self.bracket_service.create_top8_winners_round1(tournament_id)
            opened = await self._auto_open_threads_for_pairings(interaction, list(created))
        except (LookupError, ValueError, RuntimeError) as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        lines = [f"Created top cut matches for {tournament_name}:"]
        for pairing in created:
            entrant1 = self.tournament_service.get_entrant(pairing.entrant1_id) if pairing.entrant1_id else None
            entrant2 = self.tournament_service.get_entrant(pairing.entrant2_id) if pairing.entrant2_id else None
            left = entrant1.display_name if entrant1 else "TBD"
            right = entrant2.display_name if entrant2 else "BYE"
            lines.append(self._pairing_summary_text(pairing, left, right))

        thread_text = "\n".join(opened) if opened else "No ready pairings required threads."
        await interaction.edit_original_response(content="\n".join(lines) + "\n\nOpened scheduling threads:\n" + thread_text)

    @app_commands.command(name="open_match_thread", description="Open a scheduling thread for an existing match")
    @app_commands.describe(pairing_id="Match to open", thread_name="Optional thread name override")
    async def open_match_thread(self, interaction: discord.Interaction, pairing_id: str, thread_name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        pairing = self.pairing_service.get_pairing(pairing_id)
        if pairing is None:
            await interaction.edit_original_response(content="Match not found.")
            return

        if getattr(pairing, "thread_id", None):
            await interaction.edit_original_response(content=f"{self._pairing_public_id(pairing)} already has thread <#{pairing.thread_id}>.")
            return

        parent_channel = interaction.guild.get_channel(self.settings.tournament_scheduling_channel_id) if interaction.guild else None
        if parent_channel is None or not isinstance(parent_channel, discord.TextChannel):
            await interaction.edit_original_response(content="Tournament scheduling channel could not be resolved.")
            return

        entrant1 = self.tournament_service.get_entrant(pairing.entrant1_id) if pairing.entrant1_id else None
        entrant2 = self.tournament_service.get_entrant(pairing.entrant2_id) if pairing.entrant2_id else None

        mention_parts: list[str] = []
        for entrant in [entrant1, entrant2]:
            if entrant is None:
                continue
            if entrant.is_team:
                for member in self.tournament_service.get_entrant_members(entrant.id):
                    mention_parts.append(f"<@{member.discord_id}>")
            elif entrant.discord_id:
                mention_parts.append(f"<@{entrant.discord_id}>")

        left_name = entrant1.display_name if entrant1 else "TBD"
        right_name = entrant2.display_name if entrant2 else "BYE"
        stage_text = self._pairing_stage_text(pairing)
        public_id = self._pairing_public_id(pairing)

        body = self.thread_service.build_pairing_thread_body(
            public_id=public_id,
            entrant1_name=left_name,
            entrant2_name=right_name,
            stage_text=stage_text,
            status_text="Waiting for schedule",
            lightbringer_match_id=getattr(pairing, "lightbringer_match_id", None),
            scheduled_start_text=(
                f"<t:{int(getattr(pairing, 'scheduled_start_at_utc').timestamp())}:F>"
                if getattr(pairing, "scheduled_start_at_utc", None)
                else None
            ),
        )

        starter, thread = await self.thread_service.open_pairing_thread(
            parent_channel=parent_channel,
            title=f"{public_id} {stage_text}",
            body=body,
            thread_name=thread_name[:100],
            mention_text=" ".join(dict.fromkeys(mention_parts)) if mention_parts else None,
        )
        self.pairing_service.set_thread_context(
            pairing_id,
            thread_id=str(thread.id),
            thread_channel_id=str(parent_channel.id),
            starter_message_id=str(starter.id),
        )
        await interaction.edit_original_response(content=f"Opened scheduling thread <#{thread.id}> for {public_id}.")

    @matches.autocomplete("tournament_id")
    @generate_swiss_round.autocomplete("tournament_id")
    @advance_to_next_round.autocomplete("tournament_id")
    @standings.autocomplete("tournament_id")
    @generate_top_cut.autocomplete("tournament_id")
    async def tournament_id_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._autocomplete_tournament_ids(interaction, current)

    @record_match_result.autocomplete("winner_entrant_id")
    async def entrant_id_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._autocomplete_entrant_ids(interaction, current)

    @match_details.autocomplete("pairing_id")
    @record_match_result.autocomplete("pairing_id")
    @approve_match_result.autocomplete("pairing_id")
    @clear_match_result.autocomplete("pairing_id")
    @open_match_thread.autocomplete("pairing_id")
    async def pairing_id_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._autocomplete_pairing_ids(interaction, current)


class TournamentAdminGroup(TournamentCommandSupport, app_commands.Group):
    def __init__(self, settings: Settings):
        app_commands.Group.__init__(self, name="admin", description="Tournament setup and staff override commands")
        self._init_support(settings)

    @app_commands.command(name="create", description="Create a tournament")
    @app_commands.describe(
        name="Tournament name",
        category_slug="Category slug",
        entrant_type="player or team",
        seeding_race_count="Number of seeding races expected per entrant",
        seeding_method="Seeding calculation method",
        seeding_drop_count="How many lowest seeding race results to drop",
        standings_tiebreak_method="Standings tiebreak method",
        swiss_round_count="Number of swiss rounds before the cut",
        top_cut_size="Top cut size, usually 8",
    )
    @app_commands.choices(
        seeding_method=SEEDING_METHOD_CHOICES,
        seeding_drop_count=SEEDING_DROP_COUNT_CHOICES,
        standings_tiebreak_method=STANDINGS_TIEBREAK_CHOICES,
    )
    async def create(
        self,
        interaction: discord.Interaction,
        name: str,
        category_slug: Literal["mpr", "mp2r", "mpcgr"],
        entrant_type: Literal["player", "team"],
        seeding_race_count: app_commands.Range[int, 1, 10],
        seeding_method: app_commands.Choice[str],
        seeding_drop_count: app_commands.Choice[int],
        standings_tiebreak_method: app_commands.Choice[str],
        swiss_round_count: app_commands.Range[int, 1, 12],
        top_cut_size: app_commands.Range[int, 2, 32],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        if seeding_drop_count.value >= seeding_race_count:
            await interaction.edit_original_response(
                content="Seeding drop count must be lower than the total number of seeding races."
            )
            return

        tournament = self.tournament_service.create_tournament(
            guild_id=str(interaction.guild_id or self.settings.guild_id),
            name=name,
            category_slug=category_slug,
            created_by_discord_id=str(interaction.user.id),
            entrant_type=entrant_type,
            seeding_race_count=seeding_race_count,
            seeding_method=seeding_method.value,
            seeding_drop_count=seeding_drop_count.value,
            standings_tiebreak_method=standings_tiebreak_method.value,
            swiss_round_count=swiss_round_count,
            top_cut_size=top_cut_size,
        )
        await interaction.edit_original_response(
            content=(
                f"Created tournament {tournament.name}.\n"
                f"Seeding Method: {seeding_method.name}\n"
                f"Seeding Drop Count: {seeding_drop_count.value}\n"
                f"Standings Tiebreak: {standings_tiebreak_method.name}"
            )
        )

    @app_commands.command(name="add_entrant", description="Add a singles entrant to a tournament")
    @app_commands.describe(tournament_id="Tournament name", display_name="Entrant display name", user="Optional Discord user")
    async def add_entrant(self, interaction: discord.Interaction, tournament_id: str, display_name: str, user: discord.Member | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        tournament = self.tournament_service.get_tournament(tournament_id)
        if tournament is None:
            await interaction.edit_original_response(content="Tournament not found.")
            return

        if not self._tournament_allows_single_entry(tournament):
            await interaction.edit_original_response(content=self._single_entry_error_text(tournament))
            return

        target_user = user or interaction.user
        sg_profile = self.speedgaming_profile_service.get_profile_by_discord_id(str(target_user.id))
        if sg_profile is None:
            await interaction.edit_original_response(
                content=f"{target_user.display_name if isinstance(target_user, discord.Member) else target_user.name} has not completed /tournament setup speedgaming yet."
            )
            return

        try:
            entrant = self.tournament_service.add_entrant(
                tournament_id=tournament_id,
                display_name=display_name,
                discord_id=str(target_user.id),
            )
        except ValueError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        self.identity_service.upsert_single_identity(
            entrant_id=str(entrant.id),
            tournament_id=str(tournament_id),
            discord_id=str(target_user.id),
            discord_username_snapshot=str(target_user.name),
            submitted_display_name=sg_profile.sg_display_name,
            twitch_name=sg_profile.sg_twitch_name,
        )

        await interaction.edit_original_response(content=f"Added singles entrant {entrant.display_name} to {tournament.name}.")

    @app_commands.command(name="add_team", description="Add a two-player team entrant to a tournament")
    @app_commands.describe(
        tournament_id="Tournament name",
        team_name="Team name",
        member1="First team member",
        member2="Second team member",
    )
    async def add_team(
        self,
        interaction: discord.Interaction,
        tournament_id: str,
        team_name: str,
        member1: discord.Member,
        member2: discord.Member,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self._staff_only(interaction):
            await interaction.edit_original_response(content="Tournament staff access required.")
            return

        tournament = self.tournament_service.get_tournament(tournament_id)
        if tournament is None:
            await interaction.edit_original_response(content="Tournament not found.")
            return

        if not self._tournament_allows_team_entry(tournament):
            await interaction.edit_original_response(content=self._team_entry_error_text(tournament))
            return

        sg1 = self.speedgaming_profile_service.get_profile_by_discord_id(str(member1.id))
        sg2 = self.speedgaming_profile_service.get_profile_by_discord_id(str(member2.id))

        if sg1 is None:
            await interaction.edit_original_response(
                content=f"{member1.display_name} has not completed /tournament setup speedgaming yet."
            )
            return

        if sg2 is None:
            await interaction.edit_original_response(
                content=f"{member2.display_name} has not completed /tournament setup speedgaming yet."
            )
            return

        try:
            entrant = self.tournament_service.add_team(
                tournament_id=tournament_id,
                display_name=team_name,
                members=[(str(member1.id), sg1.sg_display_name), (str(member2.id), sg2.sg_display_name)],
                captain_discord_id=str(member1.id),
            )
        except ValueError as exc:
            await interaction.edit_original_response(content=str(exc))
            return

        self.identity_service.replace_team_identities(
            entrant_id=str(entrant.id),
            tournament_id=str(tournament_id),
            members=[
                IdentityRow(
                    entrant_id=str(entrant.id),
                    tournament_id=str(tournament_id),
                    member_slot=1,
                    discord_id=str(member1.id),
                    discord_username_snapshot=str(member1.name),
                    submitted_display_name=sg1.sg_display_name,
                    twitch_name=sg1.sg_twitch_name,
                    is_captain=True,
                ),
                IdentityRow(
                    entrant_id=str(entrant.id),
                    tournament_id=str(tournament_id),
                    member_slot=2,
                    discord_id=str(member2.id),
                    discord_username_snapshot=str(member2.name),
                    submitted_display_name=sg2.sg_display_name,
                    twitch_name=sg2.sg_twitch_name,
                    is_captain=False,
                ),
            ],
        )

        await interaction.edit_original_response(content=f"Added team entrant {entrant.display_name} to {tournament.name}.")

    @add_entrant.autocomplete("tournament_id")
    @add_team.autocomplete("tournament_id")
    async def tournament_id_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._autocomplete_tournament_ids(interaction, current)


class TournamentCommands(app_commands.Group):
    def __init__(self, settings: Settings):
        super().__init__(name="tournament", description="O-Lir tournament commands")
        self.add_command(TournamentSetupGroup(settings))
        self.add_command(TournamentEntryGroup(settings))
        self.add_command(TournamentSeedingGroup(settings))
        self.add_command(TournamentBracketGroup(settings))
        self.add_command(TournamentAdminGroup(settings))