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

    # Start background tasks
    if not check_reminders.is_running():
        check_reminders.start()
    if not check_dm_queue.is_running():
        check_dm_queue.start()


@bot.event
async def on_message(message: discord.Message):
    """Handle incoming messages."""
    # Ignore bot messages
    if message.author.bot:
        return

    # Check allowed context
    if not is_allowed_context(message):
        return

    # Check if this is a DM or a mention in a guild
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mention = bot.user in message.mentions if message.guild else False

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

    # For non-mentions in guilds, just observe (add to context) but check if should respond
    if not is_dm and not is_mention:
        # Add to context for awareness, then decide whether to respond
        context = await context_builder.build(message, observe_only=True)

        # If user has no permissions, just observe silently
        if not perms["allowed"]:
            return

        # Ask Claude if this warrants a response
        should_respond = await claude.should_respond(
            context=context,
            system_prompt=get_system_prompt(user_id),
        )

        if not should_respond:
            return

        logger.info(f"Choosing to respond to {perms.get('name', user_id)}: {content[:50]}...")
    else:
        # Direct mention or DM - always respond if permitted
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


@tasks.loop(seconds=10)
async def check_dm_queue():
    """Check for queued DMs every 10 seconds."""
    dm_script = Path("/home/executive-assistant/integrations/dm.py")
    if not dm_script.exists():
        return

    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(dm_script),
            "check",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()

        if stdout:
            import json
            try:
                pending_dms = json.loads(stdout.decode())
                for dm in pending_dms:
                    user_id = dm.get("user_id")
                    message_text = dm.get("message")
                    if user_id and message_text:
                        try:
                            user = await bot.fetch_user(int(user_id))
                            await user.send(message_text)
                            logger.info(f"Sent DM to {user_id}: {message_text[:50]}...")
                        except Exception as e:
                            logger.error(f"Failed to send DM: {e}")
            except json.JSONDecodeError:
                pass
    except Exception as e:
        logger.error(f"Error checking DM queue: {e}")


@check_dm_queue.before_loop
async def before_check_dm_queue():
    """Wait for bot to be ready before checking DM queue."""
    await bot.wait_until_ready()


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


@bot.command(name="restart")
async def restart_bot(ctx: commands.Context):
    """Restart the bot (admin only)."""
    if not is_allowed_context(ctx.message):
        return

    # Check admin permission
    user_id = str(ctx.author.id)
    perms = get_user_permissions(user_id)
    if perms.get("role") != "admin":
        await ctx.send("Only admins can restart the bot.")
        return

    await ctx.send("Restarting... 🔄")
    logger.info(f"Restart requested by {perms.get('name', user_id)}")

    # Write restart signal file with channel to notify on return
    restart_file = WORKSPACE / "state" / "restart_requested"
    restart_file.write_text(str(ctx.channel.id))

    # Exit - the wrapper script will restart us
    await bot.close()


@bot.command(name="reload")
async def reload_modules(ctx: commands.Context):
    """Hot reload modules without full restart (admin only)."""
    if not is_allowed_context(ctx.message):
        return

    # Check admin permission
    user_id = str(ctx.author.id)
    perms = get_user_permissions(user_id)
    if perms.get("role") != "admin":
        await ctx.send("Only admins can reload modules.")
        return

    try:
        import importlib
        import assistant_prompt
        import permissions
        import context_builder as ctx_builder_module

        importlib.reload(assistant_prompt)
        importlib.reload(permissions)
        importlib.reload(ctx_builder_module)

        # Re-initialize context builder with fresh module
        global context_builder
        context_builder = ctx_builder_module.ContextBuilder(workspace=WORKSPACE)

        await ctx.send("Modules reloaded! ✨")
        logger.info(f"Hot reload performed by {perms.get('name', user_id)}")
    except Exception as e:
        await ctx.send(f"Reload failed: {e}")
        logger.error(f"Hot reload failed: {e}", exc_info=True)


def main():
    """Run the bot."""
    logger.info("Starting Iris...")

    # Check if we're coming back from a restart
    restart_file = WORKSPACE / "state" / "restart_requested"
    notify_channel = None
    if restart_file.exists():
        try:
            notify_channel = int(restart_file.read_text().strip())
        except:
            pass
        restart_file.unlink()

    # If we need to notify a channel after restart, do it on_ready
    if notify_channel:
        @bot.event
        async def on_ready_notify():
            try:
                channel = bot.get_channel(notify_channel)
                if channel:
                    await channel.send("Back online! ✨")
            except Exception as e:
                logger.error(f"Failed to send restart notification: {e}")

        # Register as a listener (in addition to existing on_ready)
        bot.add_listener(on_ready_notify, "on_ready")

    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
