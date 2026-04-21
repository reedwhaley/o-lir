from __future__ import annotations

import discord


class ThreadService:
    def build_pairing_thread_body(
        self,
        *,
        public_id: str,
        entrant1_name: str,
        entrant2_name: str,
        stage_text: str,
        status_text: str,
        lightbringer_match_id: str | None = None,
        scheduled_start_text: str | None = None,
    ) -> str:
        lines = [
            public_id,
            f"Match: {entrant1_name} vs {entrant2_name}",
            f"Stage: {stage_text}",
            "",
            "Use this thread to agree on a race time.",
            "Once agreed, create the official match with Lightbringer in this thread.",
            f"Status: {status_text}",
        ]

        if lightbringer_match_id:
            lines.append(f"Lightbringer Match ID: {lightbringer_match_id}")

        if scheduled_start_text:
            lines.append(f"Scheduled Start: {scheduled_start_text}")

        return "\n".join(lines)

    async def open_pairing_thread(
        self,
        *,
        parent_channel: discord.TextChannel,
        title: str,
        body: str,
        thread_name: str,
        mention_text: str | None = None,
        auto_archive_duration: int = 10080,
    ) -> tuple[discord.Message, discord.Thread]:
        starter = await parent_channel.send(body)
        thread = await starter.create_thread(name=thread_name, auto_archive_duration=auto_archive_duration)
        if mention_text:
            await thread.send(mention_text)
        return starter, thread

    async def refresh_pairing_starter_message(
        self,
        *,
        client: discord.Client,
        parent_channel_id: int | str,
        starter_message_id: int | str,
        new_body: str,
    ) -> bool:
        channel = client.get_channel(int(parent_channel_id))
        if channel is None:
            try:
                channel = await client.fetch_channel(int(parent_channel_id))
            except Exception:
                return False

        if channel is None or not isinstance(channel, discord.abc.Messageable):
            return False

        try:
            message = await channel.fetch_message(int(starter_message_id))
            await message.edit(content=new_body)
            return True
        except Exception:
            return False