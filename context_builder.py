"""Discord context builder for Claude messages."""

import asyncio
import logging
import subprocess
import discord
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

VENV_PYTHON = Path("/home/iris/executive-assistant/venv/bin/python")
INTEGRATIONS = Path("/home/iris/executive-assistant/integrations")

# Track recent conversations for post-conversation extraction
# Key: user_id, Value: list of (timestamp, message_content)
_conversation_buffers: dict[str, list[tuple[float, str]]] = {}
CONVERSATION_BUFFER_TIMEOUT = 300  # 5 minutes of inactivity = conversation end
MAX_BUFFER_SIZE = 50  # Max messages per user buffer


class ContextBuilder:
    """Builds rich context from Discord messages for Claude."""

    def __init__(self, workspace: Path, history_limit: int = 20):
        self.workspace = Path(workspace)
        self.image_dir = self.workspace / "images"
        self.history_limit = history_limit

        # Ensure image directory exists
        self.image_dir.mkdir(parents=True, exist_ok=True)

    async def build(self, message: discord.Message, observe_only: bool = False) -> str:
        """Build context string from a Discord message.

        Includes:
        - Reply context (if replying to another message)
        - Recent channel history
        - Image attachments (saved locally for Claude to read)
        - The current message

        Args:
            message: The Discord message to build context from
            observe_only: If True, this is for deciding whether to respond (lighter context)

        Returns:
            Formatted context string for Claude
        """
        sections = []

        # Handle reply context
        reply_context = await self._get_reply_context(message)
        if reply_context:
            sections.append(reply_context)

        # Get channel history for context
        history = await self._get_channel_history(message)
        if history:
            sections.append(history)

        # Handle image attachments (skip for observe_only to save processing)
        if not observe_only:
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
            async for msg in message.channel.history(limit=self.history_limit + 1, before=message):
                author = msg.author.display_name
                content = msg.content or "[attachment/embed]"
                history.append(f"[{author}]: {content}")

                if len(history) >= self.history_limit:
                    break
        except discord.Forbidden:
            logger.warning(f"Missing 'Read Message History' permission in channel {message.channel}")
            return None
        except Exception as e:
            logger.error(f"Error fetching channel history: {e}")
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

    async def extract_commitments_async(self, text: str, user_id: str) -> None:
        """Extract and track commitments from user messages (background, non-blocking)."""
        # Only extract from admin/trusted users (Samuel mainly)
        # Run in background to not slow down responses
        try:
            process = await asyncio.create_subprocess_exec(
                str(VENV_PYTHON),
                str(INTEGRATIONS / "tasks.py"),
                "extract",
                text,
                "--add",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            if stdout:
                logger.info(f"Extracted commitments: {stdout.decode()[:200]}")
        except asyncio.TimeoutError:
            logger.warning("Commitment extraction timed out")
        except Exception as e:
            logger.error(f"Error extracting commitments: {e}")

    def add_to_conversation_buffer(self, user_id: str, content: str) -> None:
        """Add a message to the conversation buffer for post-conversation extraction."""
        import time
        now = time.time()

        if user_id not in _conversation_buffers:
            _conversation_buffers[user_id] = []

        buffer = _conversation_buffers[user_id]

        # Add new message
        buffer.append((now, content))

        # Trim old messages and enforce max size
        buffer[:] = [
            (ts, msg) for ts, msg in buffer
            if now - ts < CONVERSATION_BUFFER_TIMEOUT
        ][-MAX_BUFFER_SIZE:]

    def get_and_clear_conversation(self, user_id: str) -> str | None:
        """Get the buffered conversation for a user and clear it.

        Returns None if buffer is empty or too small to be meaningful.
        """
        if user_id not in _conversation_buffers:
            return None

        buffer = _conversation_buffers.pop(user_id, [])

        # Need at least 3 messages for meaningful extraction
        if len(buffer) < 3:
            return None

        # Build conversation text
        messages = [msg for _, msg in buffer]
        return "\n".join(messages)

    async def extract_conversation_memory_async(self, user_id: str, conversation: str) -> None:
        """Extract and save memories from a conversation (background, non-blocking)."""
        try:
            process = await asyncio.create_subprocess_exec(
                str(VENV_PYTHON),
                str(INTEGRATIONS / "conversation_extractor.py"),
                "extract",
                user_id,
                conversation,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=90)
            if stdout:
                logger.info(f"Extracted conversation memory for {user_id}: {stdout.decode()[:300]}")
            if stderr:
                logger.warning(f"Conversation extraction stderr: {stderr.decode()[:200]}")
        except asyncio.TimeoutError:
            logger.warning(f"Conversation extraction timed out for {user_id}")
        except Exception as e:
            logger.error(f"Error extracting conversation memory: {e}")

    async def check_and_extract_stale_conversations(self) -> None:
        """Check for conversations that have gone stale and extract them.

        Called periodically to catch conversations that ended without explicit signal.
        """
        import time
        now = time.time()

        stale_users = []
        for user_id, buffer in list(_conversation_buffers.items()):
            if not buffer:
                continue

            # Check if last message is older than timeout
            last_ts = buffer[-1][0]
            if now - last_ts > CONVERSATION_BUFFER_TIMEOUT:
                stale_users.append(user_id)

        for user_id in stale_users:
            conversation = self.get_and_clear_conversation(user_id)
            if conversation:
                logger.info(f"Extracting stale conversation for {user_id}")
                asyncio.create_task(self.extract_conversation_memory_async(user_id, conversation))
