#!/usr/bin/env python3
"""Iris - Discord Executive Assistant Bot."""

import asyncio
import json
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

# Research threads state file
RESEARCH_THREADS_STATE = Path("/home/iris/executive-assistant/workspace/state/research_threads.json")
# Questions channel state file
QUESTIONS_CHANNEL_STATE = Path("/home/iris/executive-assistant/workspace/state/questions_channel.json")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Configuration
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
# Allowed guilds - comma-separated list in env var, or defaults
ALLOWED_GUILD_IDS = set(
    os.environ.get("DISCORD_GUILD_IDS", "").split(",")
) if os.environ.get("DISCORD_GUILD_IDS") else {
    "1463663917849907454",  # Original guild
    "1464568327044071540",  # Added by Samuel
    "1465098921255764090",  # Jacob's server
}
WORKSPACE = Path("/home/iris/executive-assistant/workspace")
CLAUDE_TIMEOUT = 600  # 10 minutes

if not DISCORD_TOKEN:
    logger.error("DISCORD_TOKEN environment variable not set")
    sys.exit(1)

# Discord setup
intents = discord.Intents.default()
intents.message_content = True  # Required to read message content

bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize components
claude = ClaudeClient(workspace=WORKSPACE, timeout=CLAUDE_TIMEOUT)
context_builder = ContextBuilder(workspace=WORKSPACE)


def load_research_threads_config() -> dict:
    """Load research threads configuration."""
    if RESEARCH_THREADS_STATE.exists():
        try:
            return json.loads(RESEARCH_THREADS_STATE.read_text())
        except json.JSONDecodeError:
            pass
    return {"enabled": False, "channels": [], "contribute_thoughts": True}


def save_research_threads_config(config: dict):
    """Save research threads configuration."""
    RESEARCH_THREADS_STATE.parent.mkdir(parents=True, exist_ok=True)
    RESEARCH_THREADS_STATE.write_text(json.dumps(config, indent=2))


def is_research_channel(channel_id: int) -> bool:
    """Check if a channel is configured for auto-threading."""
    config = load_research_threads_config()
    return config.get("enabled", False) and channel_id in config.get("channels", [])


def load_questions_channel_config() -> dict:
    """Load questions channel configuration."""
    if QUESTIONS_CHANNEL_STATE.exists():
        try:
            return json.loads(QUESTIONS_CHANNEL_STATE.read_text())
        except json.JSONDecodeError:
            pass
    return {"enabled": False, "channels": [], "always_reply_in_thread": True}


def is_questions_channel(channel_id: int) -> bool:
    """Check if a channel is configured for always-reply-in-thread."""
    config = load_questions_channel_config()
    return config.get("enabled", False) and channel_id in config.get("channels", [])


def split_message(text: str, limit: int = 2000) -> list[str]:
    """Split long messages at natural boundaries, preserving code blocks."""
    if not text or len(text) <= limit:
        return [text] if text else [""]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        # Try to split at a double newline (paragraph boundary)
        split_at = text.rfind("\n\n", 0, limit)
        if split_at == -1 or split_at < limit // 4:
            # Try single newline
            split_at = text.rfind("\n", 0, limit)
        if split_at == -1 or split_at < limit // 4:
            # Fall back to space
            split_at = text.rfind(" ", 0, limit)
        if split_at == -1:
            # Hard split as last resort
            split_at = limit

        chunk = text[:split_at]

        # If we're splitting inside a code block, close it and reopen in next chunk
        open_blocks = chunk.count("```")
        if open_blocks % 2 == 1:
            # Odd number of ``` means we're inside a code block
            chunk += "\n```"
            text = "```\n" + text[split_at:].lstrip()
        else:
            text = text[split_at:].lstrip()

        chunks.append(chunk)

    return chunks


def is_allowed_context(message: discord.Message) -> bool:
    """Check if the message is from an allowed context."""
    # Always allow DMs
    if isinstance(message.channel, discord.DMChannel):
        return True

    # If guild restrictions are set, check them
    if ALLOWED_GUILD_IDS:
        return str(message.guild.id) in ALLOWED_GUILD_IDS

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
    if not check_channel_message_queue.is_running():
        check_channel_message_queue.start()
    if not check_file_queue.is_running():
        check_file_queue.start()


async def handle_research_thread(message: discord.Message):
    """Auto-create thread and contribute thoughts for research channels."""
    config = load_research_threads_config()

    # Generate thread name from first ~50 chars of message
    content = message.content[:50].strip()
    if len(message.content) > 50:
        content += "..."
    thread_name = content or f"Research from {message.author.display_name}"

    try:
        # Create thread from the message
        thread = await message.create_thread(
            name=thread_name[:100],  # Discord limit
            auto_archive_duration=10080  # 7 days
        )
        logger.info(f"Created research thread: {thread.name}")

        # If configured to contribute thoughts, generate and post a response
        if config.get("contribute_thoughts", True):
            # Build context for Claude to generate thoughts
            research_prompt = f"""A research topic was just posted. Here's the content:

{message.content}

As Iris, provide your initial thoughts, relevant connections, questions to explore, or resources that might help. Be concise but substantive. If you have genuine insights or opinions on this topic, share them. If you don't have much to add, just acknowledge it briefly."""

            async with thread.typing():
                try:
                    response = await claude.send(
                        message=research_prompt,
                        system_prompt=get_system_prompt(str(message.author.id), str(message.guild.id) if message.guild else None),
                    )

                    for chunk in split_message(response):
                        await thread.send(chunk)

                    logger.info(f"Added thoughts to research thread: {thread.name}")
                except Exception as e:
                    logger.error(f"Error generating research thoughts: {e}")

    except discord.Forbidden:
        logger.warning(f"Missing permissions to create thread in {message.channel.name}")
    except discord.HTTPException as e:
        # Thread might already exist for this message
        if e.code == 160004:  # Thread already exists
            logger.debug(f"Thread already exists for message {message.id}")
        else:
            logger.error(f"Discord error creating thread: {e}")


@bot.event
async def on_message(message: discord.Message):
    """Handle incoming messages."""
    # Ignore bot messages
    if message.author.bot:
        return

    # Log all incoming messages for debugging
    guild_name = message.guild.name if message.guild else "DM"
    logger.debug(f"Message received in {guild_name}: [{message.author.display_name}] {message.content[:50]}...")

    # Check allowed context
    if not is_allowed_context(message):
        logger.debug(f"Message rejected: not in allowed context (guild: {message.guild.id if message.guild else 'DM'})")
        return

    # Check for research channel auto-threading (before other processing)
    # Only for top-level messages in text channels, not in threads
    if (message.guild
        and isinstance(message.channel, discord.TextChannel)
        and is_research_channel(message.channel.id)):
        await handle_research_thread(message)
        # Don't return - still process normally for mentions etc.

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

        # If user has no permissions at all (role=none), just observe silently
        if not perms["allowed"]:
            logger.debug(f"Skipping unpermitted user: {user_id}")
            return

        # Ask Claude (Haiku) if this warrants a response
        guild_id = str(message.guild.id) if message.guild else None
        logger.info(f"Asking Haiku if should respond to [{perms.get('name', user_id)}]: {content[:50]}...")
        should_respond = await claude.should_respond(
            context=context,
            system_prompt=get_system_prompt(user_id, guild_id),
        )

        if not should_respond:
            logger.info(f"Haiku decided not to respond")
            return

        logger.info(f"Haiku decided to respond to {perms.get('name', user_id)}: {content[:50]}...")
    else:
        # Direct mention or DM - always respond if permitted
        if not perms["allowed"]:
            await message.channel.send(
                "Sorry, you don't have permission to use this bot."
            )
            return

    logger.info(f"User {perms.get('name', user_id)} ({perms['role']}): {content[:50]}...")

    # Check if this is a questions channel (always reply in thread)
    use_thread = (
        message.guild
        and isinstance(message.channel, discord.TextChannel)
        and is_questions_channel(message.channel.id)
    )

    # Show typing indicator while processing
    async with message.channel.typing():
        try:
            # Build context
            context = await context_builder.build(message)

            # Send to Claude with user-scoped system prompt
            guild_id = str(message.guild.id) if message.guild else None
            response = await claude.send(
                message=context,
                system_prompt=get_system_prompt(user_id, guild_id),
            )

            # Determine where to send the response
            if use_thread:
                # Create a thread from the message and reply there
                thread_name = content[:50].strip() if content else f"Question from {message.author.display_name}"
                if len(content) > 50:
                    thread_name += "..."
                try:
                    thread = await message.create_thread(
                        name=thread_name[:100],
                        auto_archive_duration=10080  # 7 days
                    )
                    target_channel = thread
                    logger.info(f"Created question thread: {thread.name}")
                except discord.HTTPException as e:
                    if e.code == 160004:  # Thread already exists
                        # Find existing thread
                        target_channel = message.channel
                    else:
                        raise
            else:
                target_channel = message.channel

            # Send response, splitting if necessary
            for chunk in split_message(response):
                await target_channel.send(chunk)

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            await message.channel.send(
                "Something went wrong processing your request. Please try again."
            )


@tasks.loop(seconds=60)
async def check_reminders():
    """Check for due reminders every minute."""
    reminders_script = Path("/home/iris/executive-assistant/integrations/reminders.py")
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
    dm_script = Path("/home/iris/executive-assistant/integrations/dm.py")
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


@tasks.loop(seconds=10)
async def check_channel_message_queue():
    """Check for queued channel messages every 10 seconds."""
    queue_script = Path("/home/iris/executive-assistant/integrations/channel_message.py")
    if not queue_script.exists():
        return

    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(queue_script),
            "check",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()

        if stdout:
            try:
                pending_messages = json.loads(stdout.decode())
                for msg in pending_messages:
                    channel_id = msg.get("channel_id")
                    content = msg.get("content")
                    create_thread = msg.get("create_thread", False)
                    thread_name = msg.get("thread_name")

                    if channel_id and content:
                        try:
                            channel = bot.get_channel(int(channel_id))
                            if channel:
                                sent_msg = await channel.send(content)
                                logger.info(f"Sent message to channel {channel_id}: {content[:50]}...")

                                # Create thread if requested
                                if create_thread:
                                    name = thread_name or content[:50] + ("..." if len(content) > 50 else "")
                                    await sent_msg.create_thread(
                                        name=name[:100],
                                        auto_archive_duration=10080  # 7 days
                                    )
                                    logger.info(f"Created thread: {name[:50]}")
                            else:
                                logger.error(f"Channel {channel_id} not found")
                        except Exception as e:
                            logger.error(f"Failed to send channel message: {e}")
            except json.JSONDecodeError:
                pass
    except Exception as e:
        logger.error(f"Error checking channel message queue: {e}")


@check_channel_message_queue.before_loop
async def before_check_channel_message_queue():
    """Wait for bot to be ready before checking channel message queue."""
    await bot.wait_until_ready()


@tasks.loop(seconds=10)
async def check_file_queue():
    """Check for queued file attachments every 10 seconds."""
    queue_script = Path("/home/iris/executive-assistant/integrations/file_sender.py")
    if not queue_script.exists():
        return

    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(queue_script),
            "check",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()

        if stdout:
            try:
                pending_files = json.loads(stdout.decode())
                for item in pending_files:
                    file_path = item.get("file_path")
                    message = item.get("message", "")
                    is_dm = item.get("is_dm", False)
                    target_id = item.get("channel_id")

                    if not file_path or not Path(file_path).exists():
                        logger.error(f"File not found: {file_path}")
                        continue

                    try:
                        discord_file = discord.File(file_path)

                        if is_dm:
                            user = await bot.fetch_user(int(target_id))
                            await user.send(content=message or None, file=discord_file)
                            logger.info(f"Sent file {Path(file_path).name} to user {target_id}")
                        else:
                            channel = bot.get_channel(int(target_id))
                            if channel:
                                await channel.send(content=message or None, file=discord_file)
                                logger.info(f"Sent file {Path(file_path).name} to channel {target_id}")
                            else:
                                logger.error(f"Channel {target_id} not found")
                    except Exception as e:
                        logger.error(f"Failed to send file: {e}")
            except json.JSONDecodeError:
                pass
    except Exception as e:
        logger.error(f"Error checking file queue: {e}")


@check_file_queue.before_loop
async def before_check_file_queue():
    """Wait for bot to be ready before checking file queue."""
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
