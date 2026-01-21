#!/usr/bin/env python3
"""Iris - Discord Executive Assistant Bot."""

import asyncio
import logging
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands, tasks

from assistant_prompt import get_system_prompt
from permissions import get_user_permissions
from claude_client import ClaudeClient
from context_builder import ContextBuilder

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Configuration
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
ALLOWED_GUILD_ID = os.environ.get("DISCORD_GUILD_ID")  # Optional: restrict to one server
WORKSPACE = Path("/home/executive-assistant/workspace")
CLAUDE_TIMEOUT = 300  # 5 minutes

if not DISCORD_TOKEN:
    logger.error("DISCORD_TOKEN environment variable not set")
    sys.exit(1)

# Discord setup
intents = discord.Intents.default()
intents.message_content = True  # Required to read message content
intents.dm_messages = True  # Enable DM support

bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize components
claude = ClaudeClient(workspace=WORKSPACE, timeout=CLAUDE_TIMEOUT)
context_builder = ContextBuilder(workspace=WORKSPACE)


def split_message(text: str, limit: int = 2000) -> list[str]:
    """Split long messages at natural boundaries."""
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        # Try to split at newline
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1 or split_at < limit // 2:
            # Fall back to space
            split_at = text.rfind(" ", 0, limit)
        if split_at == -1:
            # Hard split
            split_at = limit

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()

    return chunks


def is_allowed_context(message: discord.Message) -> bool:
    """Check if the message is from an allowed context."""
    # Always allow DMs
    if isinstance(message.channel, discord.DMChannel):
        return True

    # If guild restriction is set, check it
    if ALLOWED_GUILD_ID:
        return str(message.guild.id) == ALLOWED_GUILD_ID

    # Otherwise allow all guilds
    return True


@bot.event
async def on_ready():
    """Called when the bot is ready."""
    logger.info(f"Bot ready: {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guild(s)")

    # Start reminder checker
    if not check_reminders.is_running():
        check_reminders.start()


@bot.event
async def on_message(message: discord.Message):
    """Handle incoming messages."""
    # Ignore bot messages
    if message.author.bot:
        return

    # Check if this is a DM or a mention in a guild
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mention = bot.user in message.mentions if message.guild else False

    # Only respond to DMs or mentions
    if not is_dm and not is_mention:
        return

    # Check allowed context
    if not is_allowed_context(message):
        return

    # Remove bot mention from message content for cleaner processing
    content = message.content
    if is_mention:
        content = content.replace(f"<@{bot.user.id}>", "").strip()
        if not content:
            await message.channel.send("Yes?")
            return


    # Check permissions first
    user_id = str(message.author.id)
    perms = get_user_permissions(user_id)

    if not perms["allowed"]:
        await message.channel.send(
            "Sorry, you don't have permission to use this bot."
        )
        return

    logger.info(f"User {perms.get('name', user_id)} ({perms['role']}): {content[:50]}...")

    # Show typing indicator while processing
    async with message.channel.typing():
        try:
            # Build context
            context = await context_builder.build(message)

            # Send to Claude with user-scoped system prompt
            response = await claude.send(
                message=context,
                system_prompt=get_system_prompt(user_id),
            )

            # Send response, splitting if necessary
            for chunk in split_message(response):
                await message.channel.send(chunk)

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            await message.channel.send(
                "Something went wrong processing your request. Please try again."
            )


@tasks.loop(seconds=60)
async def check_reminders():
    """Check for due reminders every minute."""
    reminders_script = Path("/home/executive-assistant/integrations/reminders.py")
    if not reminders_script.exists():
        return

    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(reminders_script),
            "check",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()

        if stdout:
            # Parse due reminders and send them
            import json
            try:
                due_reminders = json.loads(stdout.decode())
                for reminder in due_reminders:
                    user_id = reminder.get("user_id")
                    message_text = reminder.get("message")
                    if user_id and message_text:
                        try:
                            user = await bot.fetch_user(int(user_id))
                            await user.send(f"**Reminder:** {message_text}")
                            logger.info(f"Sent reminder to {user_id}: {message_text}")
                        except Exception as e:
                            logger.error(f"Failed to send reminder: {e}")
            except json.JSONDecodeError:
                pass
    except Exception as e:
        logger.error(f"Error checking reminders: {e}")


@check_reminders.before_loop
async def before_check_reminders():
    """Wait for bot to be ready before checking reminders."""
    await bot.wait_until_ready()


@bot.command(name="reset")
async def reset_session(ctx: commands.Context):
    """Reset the Claude session to start fresh."""
    if not is_allowed_context(ctx.message):
        return

    await claude.reset_session()
    await ctx.send("Session reset. Starting fresh conversation.")


@bot.command(name="status")
async def bot_status(ctx: commands.Context):
    """Check bot status."""
    if not is_allowed_context(ctx.message):
        return

    session_exists = claude.session_file.exists()
    await ctx.send(
        f"**Status:** Online\n"
        f"**Session:** {'Active' if session_exists else 'None'}\n"
        f"**Latency:** {round(bot.latency * 1000)}ms"
    )


def main():
    """Run the bot."""
    logger.info("Starting Iris...")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
