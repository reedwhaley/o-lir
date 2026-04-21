from __future__ import annotations

import discord

from app.config import get_settings
from app.db.session import session_scope
from app.models.entrant import Entrant
from app.models.entrant_member import EntrantMember


class PermissionService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _role_ids(self, member: discord.Member) -> set[int]:
        return {role.id for role in member.roles}

    def is_bot_admin(self, interaction: discord.Interaction) -> bool:
        try:
            if interaction.permissions and interaction.permissions.administrator:
                return True
        except Exception:
            pass
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        try:
            if member.guild_permissions.administrator:
                return True
        except Exception:
            pass
        user_roles = self._role_ids(member)
        return bool({self.settings.tournament_admin_role_id, self.settings.server_admin_role_id}.intersection(user_roles))

    def can_manage_tournament(self, interaction: discord.Interaction) -> bool:
        if self.is_bot_admin(interaction):
            return True
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        user_roles = self._role_ids(member)
        return bool(set(self.settings.tournament_organizer_role_ids).intersection(user_roles))

    def can_create_tournament_match_context(self, interaction: discord.Interaction, is_weekly: bool = False) -> bool:
        if self.is_bot_admin(interaction) or self.can_manage_tournament(interaction):
            return True
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        user_roles = self._role_ids(member)
        return self.settings.tournament_participant_role_id in user_roles

    def can_view_seeding_proof(self, interaction: discord.Interaction) -> bool:
        return self.is_bot_admin(interaction) or self.can_manage_tournament(interaction)

    def can_submit_for_entrant(self, interaction: discord.Interaction, entrant_id: str) -> bool:
        if self.is_bot_admin(interaction) or self.can_manage_tournament(interaction):
            return True
        user_id = str(interaction.user.id)
        with session_scope() as session:
            entrant = session.get(Entrant, entrant_id)
            if entrant is None:
                return False
            if not entrant.is_team:
                return str(entrant.discord_id or '') == user_id
            member = session.query(EntrantMember).filter(EntrantMember.entrant_id == entrant_id, EntrantMember.discord_id == user_id).first()
            return member is not None
