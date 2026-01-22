"""Discord context builder for Claude messages."""

import discord
from pathlib import Path
from typing import Optional


class ContextBuilder:
    """Builds rich context from Discord messages for Claude."""

    def __init__(self, workspace: Path, history_limit: int = 10):
        self.workspace = Path(workspace)
        self.image_dir = self.workspace / "images"
        self.history_limit = history_limit

        # Ensure image directory exists
        self.image_dir.mkdir(parents=True, exist_ok=True)

    async def build(self, message: discord.Message) -> str:
        """Build context string from a Discord message.

        Includes:
        - Reply context (if replying to another message)
        - Recent channel history
        - Image attachments (saved locally for Claude to read)
        - The current message

        Args:
            message: The Discord message to build context from

        Returns:
            Formatted context string for Claude
        """
        sections = []

        # Handle reply context
        reply_context = await self._get_reply_context(message)
        if reply_context:
            sections.append(reply_context)

        # Get channel history (for servers, not DMs with lots of history)
        if message.guild:
            history = await self._get_channel_history(message)
            if history:
                sections.append(history)

        # Handle image attachments
        images = await self._save_attachments(message)
        if images:
            sections.append(self._format_images(images))

        # Current message
        sections.append(self._format_message(message))

        return "\n\n".join(sections)

    async def _get_reply_context(self, message: discord.Message) -> Optional[str]:
        """Get the message being replied to, if any."""
        if not message.reference or not message.reference.message_id:
            return None

        try:
            replied = await message.channel.fetch_message(message.reference.message_id)
            author = replied.author.display_name
            content = replied.content or "[no text content]"
            return f"## Replying to:\n[{author}]: {content}"
        except discord.NotFound:
            return None

    async def _get_channel_history(self, message: discord.Message) -> Optional[str]:
        """Get recent channel history for context."""
        history = []

        try:
            async for msg in message.channel.history(limit=self.history_limit + 1):
                # Skip the current message
                if msg.id == message.id:
                    continue

                author = msg.author.display_name
                content = msg.content or "[attachment/embed]"
                history.append(f"[{author}]: {content}")

                if len(history) >= self.history_limit:
                    break
        except discord.Forbidden:
            return None

        if not history:
            return None

        # Reverse to chronological order
        history.reverse()
        return "## Recent messages:\n" + "\n".join(history)

    async def _save_attachments(self, message: discord.Message) -> list[Path]:
        """Save image attachments locally for Claude to read."""
        saved = []

        for attachment in message.attachments:
            # Only process images
            if not attachment.content_type or not attachment.content_type.startswith("image/"):
                continue

            # Save with unique filename
            filename = f"{message.id}_{attachment.filename}"
            path = self.image_dir / filename

            try:
                await attachment.save(path)
                saved.append(path)
            except Exception:
                continue

        return saved

    def _format_images(self, images: list[Path]) -> str:
        """Format image paths for Claude."""
        paths = "\n".join(f"- `{p}`" for p in images)
        return f"## Images attached (use Read tool to view):\n{paths}"

    def _format_message(self, message: discord.Message) -> str:
        """Format the current message."""
        author = message.author.display_name
        content = message.content or "[no text content]"
        return f"## New message:\n[{author}]: {content}"
