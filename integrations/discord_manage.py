#!/usr/bin/env python3
"""Discord server management integration for Iris."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import discord

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")


async def create_channel(guild_id: int, name: str, category: str = None, channel_type: str = "text") -> dict:
    """Create a channel in a guild."""
    intents = discord.Intents.default()
    intents.guilds = True
    client = discord.Client(intents=intents)
    result = {}

    @client.event
    async def on_ready():
        nonlocal result
        try:
            try:
                guild = await client.fetch_guild(guild_id)
            except discord.NotFound:
                result = {"error": f"Guild {guild_id} not found"}
                await client.close()
                return

            # Find category if specified
            category_obj = None
            if category:
                fetched_channels = await guild.fetch_channels()
                for cat in [c for c in fetched_channels if isinstance(c, discord.CategoryChannel)]:
                    if cat.name.lower() == category.lower():
                        category_obj = cat
                        break
                if not category_obj:
                    # Create the category
                    category_obj = await guild.create_category(category)

            # Create channel
            if channel_type == "voice":
                channel = await guild.create_voice_channel(name, category=category_obj)
            else:
                channel = await guild.create_text_channel(name, category=category_obj)

            result = {
                "success": True,
                "channel_id": channel.id,
                "channel_name": channel.name,
                "category": category_obj.name if category_obj else None
            }
        except discord.Forbidden:
            result = {"error": "Missing permissions to create channel"}
        except Exception as e:
            result = {"error": str(e)}
        finally:
            await client.close()

    await client.start(DISCORD_TOKEN)
    return result


async def list_channels(guild_id: int) -> dict:
    """List all channels in a guild."""
    intents = discord.Intents.default()
    intents.guilds = True
    client = discord.Client(intents=intents)
    result = {}

    @client.event
    async def on_ready():
        nonlocal result
        try:
            try:
                guild = await client.fetch_guild(guild_id)
            except discord.NotFound:
                result = {"error": f"Guild {guild_id} not found"}
                await client.close()
                return

            channels = []
            fetched_channels = await guild.fetch_channels()
            for channel in fetched_channels:
                channels.append({
                    "id": channel.id,
                    "name": channel.name,
                    "type": str(channel.type),
                    "category": channel.category.name if channel.category else None
                })

            result = {"success": True, "channels": channels}
        except Exception as e:
            result = {"error": str(e)}
        finally:
            await client.close()

    await client.start(DISCORD_TOKEN)
    return result


async def create_category(guild_id: int, name: str) -> dict:
    """Create a category in a guild."""
    intents = discord.Intents.default()
    intents.guilds = True
    client = discord.Client(intents=intents)
    result = {}

    @client.event
    async def on_ready():
        nonlocal result
        try:
            try:
                guild = await client.fetch_guild(guild_id)
            except discord.NotFound:
                result = {"error": f"Guild {guild_id} not found"}
                await client.close()
                return

            category = await guild.create_category(name)
            result = {
                "success": True,
                "category_id": category.id,
                "category_name": category.name
            }
        except discord.Forbidden:
            result = {"error": "Missing permissions to create category"}
        except Exception as e:
            result = {"error": str(e)}
        finally:
            await client.close()

    await client.start(DISCORD_TOKEN)
    return result


async def delete_channel(guild_id: int, channel_name: str) -> dict:
    """Delete a channel by name."""
    intents = discord.Intents.default()
    intents.guilds = True
    client = discord.Client(intents=intents)
    result = {}

    @client.event
    async def on_ready():
        nonlocal result
        try:
            try:
                guild = await client.fetch_guild(guild_id)
            except discord.NotFound:
                result = {"error": f"Guild {guild_id} not found"}
                await client.close()
                return

            # Find channel by name
            channel = None
            fetched_channels = await guild.fetch_channels()
            for ch in fetched_channels:
                if ch.name.lower() == channel_name.lower():
                    channel = ch
                    break

            if not channel:
                result = {"error": f"Channel '{channel_name}' not found"}
                await client.close()
                return

            await channel.delete()
            result = {"success": True, "deleted": channel_name}
        except discord.Forbidden:
            result = {"error": "Missing permissions to delete channel"}
        except Exception as e:
            result = {"error": str(e)}
        finally:
            await client.close()

    await client.start(DISCORD_TOKEN)
    return result


async def rename_channel(channel_id: int, new_name: str) -> dict:
    """Rename a channel by ID."""
    intents = discord.Intents.default()
    intents.guilds = True
    client = discord.Client(intents=intents)
    result = {}

    @client.event
    async def on_ready():
        nonlocal result
        try:
            channel = await client.fetch_channel(channel_id)
            old_name = channel.name
            await channel.edit(name=new_name)
            result = {
                "success": True,
                "channel_id": channel_id,
                "old_name": old_name,
                "new_name": new_name
            }
        except discord.NotFound:
            result = {"error": f"Channel {channel_id} not found"}
        except discord.Forbidden:
            result = {"error": "Missing permissions to rename channel"}
        except Exception as e:
            result = {"error": str(e)}
        finally:
            await client.close()

    await client.start(DISCORD_TOKEN)
    return result


def main():
    parser = argparse.ArgumentParser(description="Discord server management")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # List channels
    list_parser = subparsers.add_parser("list", help="List channels in a guild")
    list_parser.add_argument("guild_id", type=int, help="Guild ID")

    # Create channel
    create_parser = subparsers.add_parser("create", help="Create a channel")
    create_parser.add_argument("guild_id", type=int, help="Guild ID")
    create_parser.add_argument("name", help="Channel name")
    create_parser.add_argument("--category", help="Category name (created if doesn't exist)")
    create_parser.add_argument("--type", choices=["text", "voice"], default="text", help="Channel type")

    # Create category
    cat_parser = subparsers.add_parser("category", help="Create a category")
    cat_parser.add_argument("guild_id", type=int, help="Guild ID")
    cat_parser.add_argument("name", help="Category name")

    # Delete channel
    delete_parser = subparsers.add_parser("delete", help="Delete a channel")
    delete_parser.add_argument("guild_id", type=int, help="Guild ID")
    delete_parser.add_argument("name", help="Channel name to delete")

    # Rename channel
    rename_parser = subparsers.add_parser("rename", help="Rename a channel")
    rename_parser.add_argument("channel_id", type=int, help="Channel ID")
    rename_parser.add_argument("new_name", help="New channel name")

    args = parser.parse_args()

    if not DISCORD_TOKEN:
        print(json.dumps({"error": "DISCORD_TOKEN not set"}))
        sys.exit(1)

    if args.command == "list":
        result = asyncio.run(list_channels(args.guild_id))
    elif args.command == "create":
        result = asyncio.run(create_channel(args.guild_id, args.name, args.category, args.type))
    elif args.command == "category":
        result = asyncio.run(create_category(args.guild_id, args.name))
    elif args.command == "delete":
        result = asyncio.run(delete_channel(args.guild_id, args.name))
    elif args.command == "rename":
        result = asyncio.run(rename_channel(args.channel_id, args.new_name))

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
