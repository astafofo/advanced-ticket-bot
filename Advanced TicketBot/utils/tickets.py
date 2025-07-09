import logging
from typing import Optional, Tuple, Dict, Any
import discord
import re
import asyncio

logger = logging.getLogger('discord')

async def is_ticket_channel(bot, channel) -> bool:
    """Check if a channel is a ticket channel by querying the database"""
    try:
        if not channel or not hasattr(channel, 'id'):
            return False

        async with bot.db.cursor() as cur:
            await cur.execute("SELECT 1 FROM ticket_instances WHERE channel_id = ? AND status = 'open'", (channel.id,))
            result = await cur.fetchone()
            return result is not None
    except Exception as e:
        logger.error(f"Error checking if channel {getattr(channel, 'id', 'unknown')} is ticket: {e}")
        return False

async def get_ticket_creator(bot, channel_id: int) -> Optional[int]:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT creator_id FROM ticket_instances WHERE channel_id = ?", (channel_id,))
            result = await cur.fetchone()
            return result[0] if result else None
    except Exception as e:
        logger.error(f"Error getting ticket creator: {e}")
        return None

async def get_ticket_creator_member(bot, guild, channel_id: int):
    try:
        creator_id = await get_ticket_creator(bot, channel_id)
        if not creator_id:
            return None

        member = guild.get_member(creator_id)
        if member:
            return member

        user = bot.get_user(creator_id)
        if user:
            return user

        try:
            user = await bot.fetch_user(creator_id)
            return user
        except discord.NotFound:
            logger.warning(f"User {creator_id} not found on Discord")
            return None

    except Exception as e:
        logger.error(f"Error getting ticket creator member: {e}")
        return None

async def get_ticket_info(bot, channel_id: int) -> Optional[Dict[str, Any]]:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("""
                SELECT creator_id, ticket_number, category, subject, description, 
                       priority, status, created_at, closed_at, claimed_by
                FROM ticket_instances 
                WHERE channel_id = ?
            """, (channel_id,))
            result = await cur.fetchone()

            if result:
                return {
                    'creator_id': result[0],
                    'ticket_number': result[1],
                    'category': result[2],
                    'subject': result[3],
                    'description': result[4],
                    'priority': result[5],
                    'status': result[6],
                    'created_at': result[7],
                    'closed_at': result[8],
                    'claimed_by': result[9]
                }
            return None
    except Exception as e:
        logger.error(f"Error getting ticket info: {e}")
        return None



async def get_user_tickets(bot, guild_id: int, user_id: int) -> list:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("""
                SELECT channel_id, category, subject, priority, status, ticket_number, created_at
                FROM ticket_instances 
                WHERE guild_id = ? AND creator_id = ?
                ORDER BY created_at DESC
            """, (guild_id, user_id))
            results = await cur.fetchall()

            tickets = []
            for row in results:
                tickets.append({
                    'channel_id': row[0],
                    'category': row[1],
                    'subject': row[2],
                    'priority': row[3],
                    'status': row[4],
                    'ticket_number': row[5],
                    'created_at': row[6]
                })
            return tickets
    except Exception as e:
        logger.error(f"Error getting user tickets: {e}")
        return []

async def get_user_open_tickets(bot, guild_id: int, user_id: int) -> list:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("""
                SELECT channel_id, category, subject, priority, status, 
                       ticket_number, created_at
                FROM ticket_instances 
                WHERE guild_id = ? AND creator_id = ? AND status = 'open'
            """, (guild_id, user_id))
            results = await cur.fetchall()

            tickets = []
            for row in results:
                tickets.append({
                    'channel_id': row[0],
                    'category': row[1],
                    'subject': row[2],
                    'priority': row[3],
                    'status': row[4],
                    'ticket_number': row[5],
                    'created_at': row[6]
                })
            return tickets
    except Exception as e:
        logger.error(f"Error getting user tickets: {e}")
        return []

async def get_guild_ticket_stats(bot, guild_id: int) -> dict:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM ticket_instances WHERE guild_id = ?", (guild_id,))
            total = (await cur.fetchone())[0]

            await cur.execute("SELECT COUNT(*) FROM ticket_instances WHERE guild_id = ? AND status = 'open'", (guild_id,))
            open_count = (await cur.fetchone())[0]

            await cur.execute("SELECT COUNT(*) FROM ticket_instances WHERE guild_id = ? AND status = 'closed'", (guild_id,))
            closed = (await cur.fetchone())[0]

            await cur.execute("SELECT COUNT(*) FROM ticket_categories WHERE guild_id = ?", (guild_id,))
            categories = (await cur.fetchone())[0]

            return {
                'total': total,
                'open': open_count,
                'closed': closed,
                'categories': categories
            }
    except Exception as e:
        logger.error(f"Error getting guild stats: {e}")
        return {'total': 0, 'open': 0, 'closed': 0, 'categories': 0}




async def get_ticket_log_channel(bot, guild_id: int):
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT log_channel_id FROM tickets WHERE guild_id = ?", (guild_id,))
            result = await cur.fetchone()
            if result and result[0]:
                return bot.get_channel(result[0])
            return None
    except Exception as e:
        logger.error(f"Error getting log channel: {e}")
        return None

async def create_ticket_channel(bot, guild: discord.Guild, user: discord.Member, category_channel, category: str, subject: str, description: str, priority: str) -> Tuple[bool, str]:
    try:
        if not await check_database_connection(bot):
            return False, "Database connection failed. Please try again later."

        from utils.database import get_ticket_role, get_ticket_category, get_ticket_log_channel, get_ping_role, ensure_database_connection

        if not await ensure_database_connection(bot):
            return False, "Database connection failed. Please try again later."
            
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT MAX(ticket_number) FROM ticket_instances WHERE guild_id = ?", (guild.id,))
            result = await cur.fetchone()
            ticket_number = (result[0] or 0) + 1

        support_role_id = await get_ticket_role(bot, guild.id)
        category_id = await get_ticket_category(bot, guild.id)
        ping_role_id = await get_ping_role(bot, guild.id)

        support_role = guild.get_role(support_role_id.id) if support_role_id else None
        ping_role = guild.get_role(ping_role_id.id) if ping_role_id else None

        priority_emojis = {"Low": "🟢", "Medium": "🟡", "High": "🟠", "Critical": "🔴"}
        emoji = priority_emojis.get(priority, "🟡")
        channel_name = f"{emoji} ticket-{ticket_number:04d}"

        ticket_category = None
        category_name = f"🎫 {category} Tickets"

        for cat in guild.categories:
            if cat.name == category_name:
                ticket_category = cat
                break

        if not ticket_category:
            try:
                ticket_category = await guild.create_category(
                    category_name,
                    reason=f"Auto-created category for {category} tickets"
                )
            except discord.Forbidden:
                logger.warning(f"Could not create category {category_name}")
                ticket_category = guild.get_channel(category_id.id) if category_id else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )
        }

        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True
            )

        channel = await guild.create_text_channel(
            channel_name,
            category=ticket_category,
            overwrites=overwrites,
            reason=f"Ticket created by {user.display_name}"
        )

        async with bot.db.cursor() as cur:
            await cur.execute("""
                INSERT INTO ticket_instances 
                (guild_id, channel_id, creator_id, ticket_number, category, subject, description, priority, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """, (guild.id, channel.id, user.id, ticket_number, category, subject, description, priority))
            await bot.db.commit()

        current_time = discord.utils.utcnow()
        embed = discord.Embed(
            title=f"<:Ticket_icons:1382703084815257610> Support Ticket",
            description=f"**Welcome to your support ticket, {user.mention}!**\n\n"
                       f"Our support team has been notified and will assist you shortly.\n"
                       f"Please provide any additional details about your issue below.",
            color=0x5865F2,
            timestamp=current_time
        )

        embed.add_field(
            name="<:clipboard1:1383857546410070117> **Ticket Information**",
            value=f"**Category:** {category}\n"
                  f"**Subject:** {subject}\n"
                  f"**Priority:** {get_priority_emoji(priority)} {priority}\n"
                  f"**Created:** {discord.utils.format_dt(current_time, 'R')}",
            inline=True
        )

        embed.add_field(
            name="<:icon_write:1382704744782499882> **Issue Description**",
            value=f"```{description[:200]}{'...' if len(description) > 200 else ''}```",
            inline=False
        )

        embed.set_footer(
            text="Support System • Ticket Management",
            icon_url=bot.user.display_avatar.url
        )

        embed.set_image(url="https://i.ibb.co/8DjgL2Px/De-Watermark-ai-1750050237119.jpg")

        from views.ticket_views import TicketControlView
        ticket_data = {
            'channel_id': channel.id,
            'creator_id': user.id,
            'ticket_number': ticket_number,
            'category': category,
            'subject': subject,
            'description': description,
            'priority': priority
        }

        view = TicketControlView(bot, ticket_data)

        await channel.send(embed=embed, view=view)

        if ping_role:
            await channel.send(f"{ping_role.mention} - New {priority.lower()} priority ticket!")

        log_channel = await get_ticket_log_channel(bot, guild.id)
        if log_channel:
            try:
                log_embed = discord.Embed(
                    title="Logs - New Ticket Created!",
                    description=f"> Ticket `#{ticket_number:04d}` created {discord.utils.format_dt(current_time, 'R')}\n\n"
                               f"**Channel**\n```{channel.mention} ({channel.id})```"
                               f"**Ticket Creator**\n```{user.display_name} ({user.id})```"
                               f"**Category**\n```{category}```"
                               f"**Priority**\n```{priority}```"
                               f"**Subject**\n```{subject}```",
                    color=0x00D4FF,
                    timestamp=discord.utils.utcnow()
                )
                log_embed.set_footer(text="Support System • Ticket Created")
                await log_channel.send(embed=log_embed)
            except Exception as log_error:
                logger.error(f"Error sending ticket creation log: {log_error}")

        return True, f"Ticket #{ticket_number:04d} created in {channel.mention}"

        async with bot.db.cursor() as cur:
            await cur.execute("SELECT role_id, category_id FROM tickets WHERE guild_id = ?", (guild.id,))
            result = await cur.fetchone()

            if not result:
                return False, "Ticket system not configured."

            support_role_id, category_id = result
            support_role = guild.get_role(support_role_id) if support_role_id else None

            await cur.execute("""
                SELECT COALESCE(MAX(ticket_number), 0) + 1 
                FROM ticket_instances WHERE guild_id = ?
            """, (guild.id,))
            ticket_number = (await cur.fetchone())[0]

            await cur.execute("SELECT emoji FROM ticket_categories WHERE guild_id = ? AND category_name = ?", (guild.id, category))
            emoji_result = await cur.fetchone()
            category_emoji = emoji_result[0] if emoji_result and emoji_result[0] else "<:Ticket_icons:1382703084815257610>"

            priority_emojis = {
                "Low": "🟢",
                "Medium": "🟡", 
                "High": "🟠",
                "Critical": "🔴"
            }

            priority_emoji = priority_emojis.get(priority, "🟡")
            channel_name = f"{priority_emoji} ticket-{ticket_number:04d}-{re.sub(r'[^a-zA-Z0-9]', '', user.display_name.lower())}"

            ticket_category = None
            category_name = f"{category_emoji} {category} Tickets"

            for cat in guild.categories:
                if cat.name == category_name:
                    ticket_category = cat
                    break

            if not ticket_category:
                try:
                    ticket_category = await guild.create_category(
                        category_name,
                        reason=f"Auto-created category for {category} tickets"
                    )
                    logger.info(f"Created new category: {category_name}")
                except discord.Forbidden:
                    logger.warning(f"Could not create category {category_name} - using fallback")
                    ticket_category = guild.get_channel(category_id) if category_id else None
                except Exception as e:
                    logger.error(f"Error creating category {category_name}: {e}")
                    ticket_category = guild.get_channel(category_id) if category_id else None

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                user: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
            }

            if support_role_id:
                support_role = guild.get_role(support_role_id)
                if support_role:
                    overwrites[support_role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        manage_messages=True
                    )

            channel = await guild.create_text_channel(
                name=channel_name,
                category=ticket_category,
                overwrites=overwrites,
                topic=f"Ticket #{ticket_number:04d} - {category} | Created by {user.display_name}"
            )

            await cur.execute("""
                INSERT INTO ticket_instances 
                (guild_id, channel_id, creator_id, category, subject, description, priority, ticket_number, claimed_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (guild.id, channel.id, user.id, category, subject, description, priority, ticket_number, None))
            await bot.db.commit()

            if support_role:
                try:
                    ping_message = await channel.send(f"{support_role.mention}")
                    await ping_message.delete()
                except:
                    pass

            current_time = discord.utils.utcnow()
            embed = discord.Embed(
                title=f"<:Ticket_icons:1382703084815257610> Ticket",
                description=f"**Welcome to your support ticket, {user.mention}!**\n\n"
                           f"Our team has been notified and will assist you shortly.\n"
                           f"Please provide any additional details about your issue.",
                color=0x00D4FF,
                timestamp=current_time
            )

            embed.add_field(
                name="<:clipboard1:1383857546410070117> Ticket Information",
                value=f"**Category:** {category}\n"
                      f"**Subject:** {subject}\n"
                      f"**Priority:** {get_priority_emoji(priority)} {priority}\n"
                      f"**Created:** {discord.utils.format_dt(current_time, 'R')}",
                inline=True
            )

            embed.add_field(
                name="<:lightbulb:1382701619753386035> Description",
                value=description[:1000] + "..." if len(description) > 1000 else description,
                inline=False
            )

            embed.add_field(
                name="<:Target:1382706193855942737> Next Steps",
                value="• Support staff will be with you shortly\n"
                      "• Use the buttons below to manage your ticket\n"
                      "• Add any additional information as needed",
                inline=False
            )

            embed.set_footer(text=" Support System • Ticket Created")
            embed.set_thumbnail(url=user.display_avatar.url)

            ticket_data = {
                'creator_id': user.id,
                'ticket_number': ticket_number,
                'category': category,
                'subject': subject,
                'description': description,
                'priority': priority,
                'channel_id': channel.id
            }

            from views.ticket_views import TicketControlView
            view = TicketControlView(bot, ticket_data)
            await channel.send(embed=embed, view=view)

            asyncio.create_task(log_ticket_creation(bot, guild, channel, user, ticket_number, category, priority, subject, current_time))

            return True, channel.mention

    except Exception as e:
        logger.error(f"Error creating ticket channel: {e}")
        return False, f"Failed to create ticket: {str(e)}"

async def get_user_open_ticket_count(bot, guild_id: int, user_id: int) -> int:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("""
                SELECT COUNT(*) FROM ticket_instances 
                WHERE guild_id = ? AND creator_id = ? AND status = 'open'
            """, (guild_id, user_id))
            result = await cur.fetchone()
            return result[0] if result else 0
    except Exception as e:
        logger.error(f"Error getting user open ticket count: {e}")
        return 0

async def get_ticket_limit(bot, guild_id: int) -> int:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT ticket_limit FROM tickets WHERE guild_id = ?", (guild_id,))
            result = await cur.fetchone()
            return result[0] if result else 3
    except Exception as e:
        logger.error(f"Error getting ticket limit: {e}")
        return 3

async def check_database_connection(bot):
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT 1")
            return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False

def get_priority_emoji(priority: str) -> str:
    priority_emojis = {
        "Low": "🟢",
        "Medium": "🟡",
        "High": "🟠",
        "Critical": "🔴"
    }
    return priority_emojis.get(priority, "🟡")

async def log_ticket_creation(bot, guild, channel, user, ticket_number, category, priority, subject, current_time):
    try:
        async with bot.db.cursor() as log_cur:
            await log_cur.execute("SELECT log_channel_id FROM tickets WHERE guild_id = ?", (guild.id,))
            log_result = await log_cur.fetchone()

            if log_result and log_result[0]:
                log_channel = guild.get_channel(log_result[0])
                if log_channel:
                    log_embed = discord.Embed(
                        title="Logs - New Ticket Created!",
                        description=f"> Ticket `#{ticket_number:04d}` created {discord.utils.format_dt(current_time, 'R')}\n\n"
                                   f"**Channel**\n```{channel.mention} ({channel.id})```"
                                   f"**Ticket Creator**\n```{user.display_name} ({user.id})```"
                                   f"**Category**\n```{category}```"
                                   f"**Priority**\n```{priority}```"
                                   f"**Subject**\n```{subject}```",
                        color=0x00FF88,
                        timestamp=current_time
                    )
                    log_embed.set_footer(text="Support System • Ticket Created")
                    log_embed.set_thumbnail(url=user.display_avatar.url)

                    await log_channel.send(embed=log_embed)
    except Exception as log_error:
        logger.error(f"Error sending ticket creation log: {log_error}")