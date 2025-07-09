import logging
import discord
import time
import re
import io
from datetime import datetime, timezone
from typing import Tuple

logger = logging.getLogger('discord')

def utc_to_gmt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def utc_to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

async def check_rate_limit(bot, user_id: int, cooldown_seconds: int = 60) -> bool:
    """
    Check if user is rate limited.
    Returns True if user IS rate limited (should be blocked)
    Returns False if user is NOT rate limited (can proceed)
    """
    try:
        current_time = time.time()
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT last_ticket_time FROM rate_limits WHERE user_id = ?", (user_id,))
            result = await cur.fetchone()

            if result:
                last_time = result[0]
                if current_time - last_time < cooldown_seconds:
                    return True  # User IS rate limited

            return False  # User is NOT rate limited
    except Exception as e:
        logger.error(f"Error checking rate limit: {e}")
        return False  # Allow on error

async def set_rate_limit(bot, user_id: int):
    try:
        current_time = time.time()
        async with bot.db.cursor() as cur:
            await cur.execute(
                "INSERT OR REPLACE INTO rate_limits (user_id, last_ticket_time) VALUES (?, ?)",
                (user_id, current_time)
            )
            await bot.db.commit()
    except Exception as e:
        logger.error(f"Error setting rate limit: {e}")

async def validate_ticket_setup(bot, guild_id: int) -> Tuple[bool, str]:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT channel_id, role_id FROM tickets WHERE guild_id = ?", (guild_id,))
            result = await cur.fetchone()

            if not result:
                return False, "Ticket system not configured"

            channel_id, role_id = result
            guild = bot.get_guild(guild_id)

            if not guild:
                return False, "Guild not found."

            if not guild.get_channel(channel_id):
                return False, "Support channel not found or deleted."

            if not guild.get_role(role_id):
                return False, "Support role not found or deleted."

            return True, "Setup valid"
    except Exception as e:
        logger.error(f"Error validating setup: {e}")
        return False, f"Database error: {e}"

async def generate_transcript(channel) -> Tuple[str, io.StringIO]:
    try:
        transcript_content = f"Transcript for #{channel.name}\n"
        transcript_content += f"Generated on: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        transcript_content += "=" * 50 + "\n\n"

        messages = []
        async for message in channel.history(limit=None, oldest_first=True):
            timestamp = message.created_at.strftime('%Y-%m-%d %H:%M:%S')
            author = f"{message.author.display_name} ({message.author.id})"
            content = message.content or "[No content]"

            if message.attachments:
                attachment_urls = [att.url for att in message.attachments]
                content += f"\nAttachments: {', '.join(attachment_urls)}"

            if message.embeds:
                content += f"\n[{len(message.embeds)} embed(s)]"

            messages.append(f"[{timestamp}] {author}: {content}\n")

        transcript_content += "\n".join(messages)
        transcript_file = io.StringIO(transcript_content)
        return transcript_content, transcript_file

    except Exception as e:
        logger.error(f"Error generating transcript: {e}")
        error_content = f"Error generating transcript: {str(e)}"
        error_file = io.StringIO(error_content)
        return error_content, error_file

def format_priority_emoji(priority: str) -> str:
    priority_emojis = {
        "Low": "<a:green_circle2:1382704526057930794>",
        "Medium": "<:Yellow_circle:1382704571377258559>", 
        "High": "<:icons_fire:1382705739960684706>",
        "Critical": "<:icons_Wrong:1382701332955402341>"
    }
    return priority_emojis.get(priority, "<:Yellow_circle:1382704571377258559>")

def get_priority_color(priority: str) -> int:
    priority_colors = {
        "Low": 0x00FF00,
        "Medium": 0xFFFF00,
        "High": 0xFF8C00,
        "Critical": 0xFF0000
    }
    return priority_colors.get(priority, 0xFFFF00)

def get_priority_emoji(priority: str) -> str:
    priority_emojis = {
        "Low": "🟢",
        "Medium": "🟡", 
        "High": "🟠",
        "Critical": "🔴"
    }
    return priority_emojis.get(priority, "🟡")

def get_status_emoji(status: str) -> str:
    status_emojis = {
        "open": "<a:green_circle2:1382704526057930794>",
        "closed": "<:icons_Wrong:1382701332955402341>",
        "locked": "<:icons_locked:1382701901685985361>",
        "claimed": "<:welcome:1382706419765350480>"
    }
    return status_emojis.get(status, "<:icons_help:1382704281945112645>")

def sanitize_channel_name(name: str) -> str:
    name = re.sub(r'[^a-zA-Z0-9\-_]', '-', name.lower())
    name = re.sub(r'-+', '-', name)
    name = name.strip('-')
    return name[:100] if len(name) > 100 else name

async def send_transcript_dm(user, channel_name, transcript_file):
    try:
        transcript_file.seek(0)
        file = discord.File(transcript_file, filename=f"{channel_name}-transcript.txt")

        transcript_embed = discord.Embed(
            title="<:clipboard1:1383857546410070117> Ticket Transcript",
            description=f"**Complete conversation log for your support ticket.**\n\n"
                       f"This transcript contains all messages, files, and interactions from your support session. "
                       f"Keep this for your records or future reference.\n\n"
                       f"**Channel:** {channel_name}\n"
                       f"**Generated:** <t:{int(datetime.now(timezone.utc).timestamp())}:F>",
            color=0x00D4FF,
            timestamp=datetime.now(timezone.utc)
        )
        transcript_embed.set_footer(text="Support System • Conversation Archive")

        await user.send(embed=transcript_embed, file=file)
        logger.info(f"Enhanced transcript sent to {user.id}")
    except discord.Forbidden:
        logger.warning(f"Could not send transcript to {user.id} - DMs disabled")
    except Exception as e:
        logger.error(f"Failed to send transcript to {user.id}: {e}")

def format_time_ago(dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    diff = now - dt

    if diff.days > 0:
        return f"{diff.days} day{'s' if diff.days != 1 else ''} ago"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    else:
        return "Just now"

def truncate_text(text: str, max_length: int = 100) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

def format_user_mention(user_id: int) -> str:
    return f"<@{user_id}>"

def format_channel_mention(channel_id: int) -> str:
    return f"<#{channel_id}>"

import discord
import logging

logger = logging.getLogger('discord')

def format_role_mention(role_id: int) -> str:
    return f"<@&{role_id}>"

async def send_error_embed(interaction_or_ctx, title: str, description: str):
    embed = discord.Embed(
        title=f"<:icons_Wrong:1382701332955402341> {title}",
        description=description,
        color=0xFF6B6B
    )

    try:
        if isinstance(interaction_or_ctx, discord.Interaction):
            if not interaction_or_ctx.response.is_done():
                await interaction_or_ctx.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction_or_ctx.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction_or_ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error sending error embed: {e}")

async def send_success_embed(interaction_or_ctx, title: str, description: str):
    embed = discord.Embed(
        title=f"<:j_icons_Correct:1382701297987485706> {title}",
        description=description,
        color=0x00D4FF
    )

    try:
        if isinstance(interaction_or_ctx, discord.Interaction):
            if not interaction_or_ctx.response.is_done():
                await interaction_or_ctx.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction_or_ctx.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction_or_ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error sending success embed: {e}")

async def create_ticket_channel(bot, guild, creator, category, subject, description, ticket_number):
    try:
        async with bot.db.cursor() as cur:
            await cur.execute(
                "SELECT category_id, role_id, ping_role_id FROM tickets WHERE guild_id = ?",
                (guild.id,)
            )
            result = await cur.fetchone()

            if not result:
                return None

            category_id, role_id, ping_role_id = result

        ticket_category = guild.get_channel(category_id) if category_id else None
        ticket_role = guild.get_role(role_id) if role_id else None
        ping_role = guild.get_role(ping_role_id) if ping_role_id else None

        channel_name = f"ticket-{ticket_number:04d}"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            creator: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )
        }

        if ticket_role:
            overwrites[ticket_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True
            )

        channel = await guild.create_text_channel(
            name=channel_name,
            category=ticket_category,
            overwrites=overwrites,
            topic=f"Support ticket for {creator.display_name} | {category} | {subject}"
        )

        async with bot.db.cursor() as cur:
            await cur.execute("""
                INSERT INTO ticket_instances 
                (guild_id, channel_id, creator_id, ticket_number, category, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'open', ?)
            """, (guild.id, channel.id, creator.id, ticket_number, category, 'open', datetime.now()))
            await bot.db.commit()

        embed = discord.Embed(
            title=f"<:Ticket_icons:1382703084815257610> Ticket #{ticket_number:04d}",
            description=f"**Category:** {category}\n**Subject:** {subject}\n**Description:** {description}",
            color=0x00D4FF
        )
        embed.add_field(name="Creator", value=creator.mention, inline=True)
        embed.add_field(name="Status", value="<a:green_circle2:1382704526057930794> Open", inline=True)
        embed.set_footer(text="Our team will be with you shortly!")

        ping_text = ""
        if ping_role:
            ping_text = f"{ping_role.mention}"

        await channel.send(content=ping_text, embed=embed)

        return channel

    except Exception as e:
        logger.error(f"Error creating ticket channel: {e}")
        return None