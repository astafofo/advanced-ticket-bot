import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncio
import re
from datetime import datetime, timezone, timedelta
from typing import Optional
import time
from utils.helpers import check_rate_limit, set_rate_limit, generate_transcript, utc_to_gmt
from utils.database import (
    check_database_connection, get_ticket_channel, get_ticket_role, get_ticket_category,
    get_ticket_log_channel, get_ping_role, get_ticket_categories, user_has_support_role,
    add_ticket_category, remove_ticket_category, reset_ticket_categories, get_user_open_tickets,
    check_user_ticket_limit
)
from utils.tickets import is_ticket_channel, get_ticket_creator
from views.ticket_views import TicketSetupView, TicketPanelView, TicketButtonPanelView, TicketChannelView


logger = logging.getLogger('discord')

async def update_ticket_panel(bot, guild_id: int, panel_type: str = None) -> tuple[bool, str]:
    try:
        if not await check_database_connection(bot):
            return False, "Database connection failed. Please try again later."

        async with bot.db.cursor() as cur:
            await cur.execute(
                "SELECT channel_id, embed_title, embed_description, embed_color, embed_image_url, embed_footer, panel_type FROM tickets WHERE guild_id = ?",
                (guild_id,)
            )
            result = await cur.fetchone()
            if not result:
                return False, "Support system is not set up. Use `/setup-tickets` first."

            channel_id, embed_title, embed_description, embed_color, embed_image_url, embed_footer, current_panel_type = result
            channel = bot.get_channel(channel_id)
            if not channel:
                return False, "Support channel not found. Please set up the support system again."

            panel_type = panel_type or current_panel_type
            if panel_type not in ("dropdown", "button"):
                return False, "Invalid panel type. Use `dropdown` or `button`."

            categories = await get_ticket_categories(bot, guild_id)
            if not categories:
                return False, "No ticket categories found. You must create categories first using `/add-category <name>` before sending a panel."

            def convert_color_to_int(color_value):
                if color_value is None:
                    return 0x00D4FF
                if isinstance(color_value, int):
                    return color_value
                if isinstance(color_value, str):
                    try:
                        color_str = color_value.strip()
                        if color_str.startswith('#'):
                            return int(color_str[1:], 16)
                        elif color_str.startswith('0x'):
                            return int(color_str, 16)
                        else:
                            return int(color_str, 16)
                    except (ValueError, AttributeError):
                        return 0x00D4FF
                return 0x00D4FF

            embed_color = convert_color_to_int(embed_color)

            embed = discord.Embed(
                title=embed_title,
                description=embed_description,
                color=embed_color
            )
            if embed_image_url:
                embed.set_image(url=embed_image_url)
            if embed_footer:
                embed.set_footer(text=embed_footer)

            try:
                async with bot.db.cursor() as cur:
                    await cur.execute("SELECT message_id FROM ticket_panels WHERE guild_id = ?", (guild_id,))
                    old_message = await cur.fetchone()
                    if old_message:
                        try:
                            message = await channel.fetch_message(old_message[0])
                            await message.delete()
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            logger.warning(f"Could not delete old panel message {old_message[0]} in guild {guild_id}")
                            pass

                if panel_type == "dropdown":
                    view = TicketPanelView(bot, categories, guild_id)
                else:
                    view = TicketButtonPanelView(bot, categories, guild_id)

                message = await channel.send(embed=embed, view=view)
                async with bot.db.cursor() as cur:
                    await cur.execute(
                        "INSERT OR REPLACE INTO ticket_panels (guild_id, channel_id, message_id) VALUES (?, ?, ?)",
                        (guild_id, channel_id, message.id)
                    )
                    await bot.db.commit()
                return True, f"Support panel has been sent to {channel.mention}."
            except discord.Forbidden as e:
                return False, f"I don't have permission to send messages in the support channel: {e}"
            except Exception as e:
                return False, f"An error occurred: {e}"
    except Exception as e:
        logger.error(f"Error updating ticket panel for guild {guild_id}: {e}")
        return False, f"Database error occurred: {str(e)}"

class SupportSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not hasattr(bot, 'active_setups'):
            bot.active_setups = {}

    async def cog_load(self):
        try:
            async with self.bot.db.cursor() as cur:
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS tickets (
                        guild_id INTEGER PRIMARY KEY,
                        channel_id INTEGER,
                        role_id INTEGER,
                        category_id INTEGER,
                        log_channel_id INTEGER,
                        ping_role_id INTEGER,
                        embed_title TEXT DEFAULT '<:Ticket_icons:1382703084815257610> Support Center',
                        embed_description TEXT DEFAULT 'Need help? Select a category below to create a support ticket. Our team will assist you shortly! <:UA_Rocket_icons:1382701592851124254>',
                        embed_color INTEGER DEFAULT 53247,
                        embed_image_url TEXT,
                        embed_footer TEXT DEFAULT 'Powered by Harly Xploitz™',
                        panel_type TEXT DEFAULT 'dropdown',
                        ticket_limit INTEGER DEFAULT 3
                    )
                """)

                try:
                    await cur.execute("ALTER TABLE tickets ADD COLUMN embed_footer TEXT DEFAULT 'Powered by Harly Xploitz™'")
                except:
                    pass  # Column already exists

                try:
                    await cur.execute("ALTER TABLE tickets ADD COLUMN embed_image_url TEXT")
                except:
                    pass  # Column already exists

                try:
                    await cur.execute("ALTER TABLE tickets ADD COLUMN maintenance_mode BOOLEAN DEFAULT 0")
                except:
                    pass  # Column already exists

                try:
                    await cur.execute("ALTER TABLE tickets ADD COLUMN panel_type TEXT DEFAULT 'dropdown'")
                except:
                    pass  # Column already exists

                try:
                    await cur.execute("ALTER TABLE tickets ADD COLUMN ticket_limit INTEGER DEFAULT 3")
                except:
                    pass  # Column already exists

                try:
                    await cur.execute("ALTER TABLE ticket_instances ADD COLUMN subject TEXT")
                except:
                    pass  # Column already exists

                try:
                    await cur.execute("ALTER TABLE ticket_instances ADD COLUMN description TEXT")
                except:
                    pass  # Column already exists

                try:
                    await cur.execute("ALTER TABLE ticket_instances ADD COLUMN claimed_by INTEGER")
                except:
                    pass  # Column already exists

                try:
                    await cur.execute("SELECT embed_color FROM tickets LIMIT 1")
                    result = await cur.fetchone()
                    if result and isinstance(result[0], str):
                        await cur.execute("SELECT guild_id, embed_color FROM tickets")
                        rows = await cur.fetchall()
                        for guild_id, color_str in rows:
                            try:
                                if color_str.startswith('#'):
                                    color_int = int(color_str[1:], 16)
                                elif color_str.startswith('0x'):
                                    color_int = int(color_str, 16)
                                else:
                                    color_int = int(color_str, 16) if color_str.isdigit() else 0x00D4FF
                            except (ValueError, AttributeError):
                                color_int = 0x00D4FF

                            await cur.execute("UPDATE tickets SET embed_color = ? WHERE guild_id = ?", (color_int, guild_id))
                        logger.info("Migrated color values from string to integer")
                except:
                    pass  # Column already properly configured

                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS ticket_categories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER,
                        category_name TEXT,
                        UNIQUE(guild_id, category_name)
                    )
                """)

                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS ticket_instances (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER,
                        channel_id INTEGER UNIQUE,
                        creator_id INTEGER,
                        ticket_number INTEGER,
                        category TEXT,
                        subject TEXT,
                        description TEXT,
                        priority TEXT DEFAULT 'Medium',
                        status TEXT DEFAULT 'open',
                        claimed_by INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        closed_at TIMESTAMP
                    )
                """)

                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS ticket_ratings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER,
                        ticket_number INTEGER,
                        user_id INTEGER,
                        rating INTEGER,
                        feedback TEXT,
                        staff_member TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS ticket_user_status (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER,
                        user_id INTEGER,
                        ticket_number INTEGER,
                        was_member_at_creation BOOLEAN DEFAULT 1,
                        display_name_at_creation TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(guild_id, user_id, ticket_number)
                    )
                """)

                try:
                    await cur.execute("ALTER TABLE ticket_ratings ADD COLUMN staff_member TEXT")
                except:
                    pass  # Column already exists

                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS ticket_panels (
                        guild_id INTEGER PRIMARY KEY,
                        channel_id INTEGER,
                        message_id INTEGER,
                        FOREIGN KEY (guild_id) REFERENCES tickets (guild_id)
                    )
                """)

                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS rate_limits (
                        user_id INTEGER PRIMARY KEY,
                        last_ticket_time REAL
                    )
                """)

                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS ticket_blacklist (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER,
                        user_id INTEGER,
                        blacklisted_by INTEGER,
                        blacklisted_at TEXT,
                        UNIQUE(guild_id, user_id)
                    )
                """)

                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS additional_support_roles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER,
                        role_id INTEGER,
                        UNIQUE(guild_id, role_id)
                    )
                """)

                await self.bot.db.commit()
        except Exception as e:
            logger.error(f"Error setting up database: {e}")
            raise





    @commands.Cog.listener()
    async def on_ready(self):
        """Register persistent views after bot is fully ready"""
        try:
            await self.register_persistent_views()
        except Exception as e:
            logger.error(f"Error in on_ready persistent view registration: {e}")

    async def register_persistent_views(self):
        """Register persistent views for all guilds with ticket systems"""
        try:
            self.bot.add_view(TicketChannelView(self.bot, {}, 0, "", 0, "", "", ""))

            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT DISTINCT guild_id FROM tickets")
                guilds = await cur.fetchall()

                for guild_row in guilds:
                    guild_id = guild_row[0]
                    try:
                        categories = await get_ticket_categories(self.bot, guild_id)
                        if categories:
                            panel_view = TicketPanelView(self.bot, categories, guild_id)
                            button_view = TicketButtonPanelView(self.bot, categories, guild_id)

                            self.bot.add_view(panel_view)
                            self.bot.add_view(button_view)
                        else:
                            logger.warning(f"No categories found for guild {guild_id}")
                    except Exception as e:
                        logger.error(f"Error registering views for guild {guild_id}: {e}")
                        import traceback
                        logger.error(traceback.format_exc())

        except Exception as e:
            logger.error(f"Error registering persistent views: {e}")
            import traceback
            logger.error(traceback.format_exc())

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        if message.guild.id in self.bot.active_setups:
            view = self.bot.active_setups[message.guild.id]
            if hasattr(view, 'handle_custom_message'):
                await view.handle_custom_message(message)

    @commands.hybrid_command(name="setup-tickets", description="Set up the support ticket system for this server.")
    @commands.has_permissions(administrator=True)
    async def setup_tickets(self, ctx: commands.Context):
        invoker = ctx.author if isinstance(ctx, commands.Context) else ctx.user
        logger.info(f"Setup tickets command invoked by {invoker}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if not await check_database_connection(self.bot):
                message = "<:icons_Wrong:1382701332955402341> | Database connection failed. Please try again later."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message, ephemeral=True)
                return

            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:UA_Rocket_icons:1382701592851124254>  Support Setup",
                description=f"**Welcome to the Advanced Ticket System Setup!**\n\n"
                            f"This wizard will guide you through configuring a  support system for your server.\n\n"
                            f"**<:clipboard1:1383857546410070117> Required Steps:**\n"
                            f"1. Select a support channel (where tickets will be announced)\n"
                            f"2. Choose a support role (staff who can manage tickets)\n"
                            f"3. Optionally select a category for ticket channels\n"
                            f"4. Customize your support panel appearance\n\n"
                            f"<:icons_clock:1382701751206936697> **Setup expires in 29 minutes**",
                color=0x00D4FF,
                timestamp=current_time
            )
            embed.add_field(
                name="<:lightbulb:1382701619753386035> Pro Tips",
                value="• Use dedicated channels for better organization\n"
                      "• Create specific roles for support staff\n"
                      "• Categories help organize active tickets",
                inline=False
            )
            embed.set_footer(text=f"Setup initiated at {current_time.strftime('%I:%M %p GMT')} • Step 1 of 4")
            view = TicketSetupView(self.bot, ctx)
            self.bot.active_setups[ctx.guild.id] = view
            if isinstance(ctx, discord.Interaction):
                message = await ctx.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                message = await ctx.send(embed=embed, view=view, ephemeral=True)
            await view.wait()
            for item in view.children:
                item.disabled = True
            await message.edit(view=view)
            if ctx.guild.id in self.bot.active_setups:
                del self.bot.active_setups[ctx.guild.id]

        except Exception as e:
            logger.error(f"Error in setup_tickets: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="add-category", description="Add a new support category.")
    @app_commands.describe(
        category="The category name to add",
        emoji="Optional emoji for the category (default: ticket icon)"
    )
    @commands.has_permissions(administrator=True)
    async def add_category(self, ctx: commands.Context, category: str, emoji: str = None):
        logger.info(f"Add category command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}: {category}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            original_category = category
            
            if isinstance(ctx, commands.Context) and "|" in category and not emoji:
                parts = category.split("|", 1)
                if len(parts) == 2:
                    emoji = parts[0].strip()
                    category = parts[1].strip()
            elif isinstance(ctx, commands.Context) and not emoji:
                words = category.split()
                if len(words) > 1:
                    potential_emoji = words[0]
                    if len(potential_emoji) <= 4 and not potential_emoji.isalpha():
                        emoji = potential_emoji
                        category = " ".join(words[1:])

            if len(category) > 25:
                message = "<:icons_Wrong:1382701332955402341> | Category name cannot exceed 25 characters."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message, ephemeral=True)
                return

            category = category.title()
            success, message = await add_ticket_category(self.bot, ctx.guild.id, category, emoji)

            if success:
                try:
                    category_name = f"🎫 {category} Tickets"
                    new_category = await ctx.guild.create_category(category_name)
                    message += f" Discord category '{category_name}' created."
                except discord.Forbidden:
                    message += " (Warning: Could not create Discord category - missing permissions)"
                except Exception as e:
                    message += f" (Warning: Could not create Discord category - {str(e)})"

            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:j_icons_Correct:1382701297987485706> Success" if success else "<:icons_Wrong:1382701332955402341> Error",
                description=message,
                color=0x00D4FF if success else 0xFF6B6B,
                timestamp=current_time
            )
            embed.set_footer(text=f"Action at {current_time.strftime('%I:%M %p GMT')}")
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

            if success:
                panel_success, panel_message = await update_ticket_panel(self.bot, ctx.guild.id)
                if not panel_success and "not set up" not in panel_message:
                    error_message = f"<:icons_Wrong:1382701332955402341> | Failed to update support panel: {panel_message}"
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(error_message, ephemeral=True)
                    else:
                        await ctx.send(error_message, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in add_category: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="remove-category", description="Remove a support category.")
    @app_commands.describe(category="The category name to remove")
    @commands.has_permissions(administrator=True)
    async def remove_category(self, ctx: commands.Context, *, category: str):
        logger.info(f"Remove category command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}: {category}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            category = category.title()
            success, message = await remove_ticket_category(self.bot, ctx.guild.id, category)

            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:j_icons_Correct:1382701297987485706> Success" if success else "<:icons_Wrong:1382701332955402341> Error",
                description=message,
                color=0x00D4FF if success else 0xFF6B6B,
                timestamp=current_time
            )
            embed.set_footer(text=f"Action at {current_time.strftime('%I:%M %p GMT')}")
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

            if success:
                panel_success, panel_message = await update_ticket_panel(self.bot, ctx.guild.id)
                if not panel_success and "not set up" not in panel_message:
                    error_message = f"<:icons_Wrong:1382701332955402341> | Failed to update support panel: {panel_message}"
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(error_message, ephemeral=True)
                    else:
                        await ctx.send(error_message, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in remove_category: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="list-categories", description="List all support categories.")
    async def list_categories(self, ctx: commands.Context):
        logger.info(f"List categories command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            invoker = ctx.author if isinstance(ctx, commands.Context) else ctx.user
            user_has_support = await user_has_support_role(self.bot, invoker)
            is_admin = invoker.guild_permissions.administrator

            if not (user_has_support or is_admin):
                embed = discord.Embed(
                    title="<:icons_locked:1382701901685985361> Permission Denied",
                    description="**You don't have permission to view the categories list.**\n\n"
                               "This command is restricted to support staff and administrators only.",
                    color=0xFF6B6B
                )
                embed.add_field(
                    name="<:Target:1382706193855942737> Required Permission",
                    value="• **Support Staff** - Members with the support role\n• **Administrator** - Server administrators",
                    inline=False
                )
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed, ephemeral=True)
                return

            categories = await get_ticket_categories(self.bot, ctx.guild.id)
            if not categories:
                message = "<:icons_Wrong:1382701332955402341> | No support categories found. Use `/add-category <category>` to add some."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            current_time = utc_to_gmt(discord.utils.utcnow())
            category_list = []
            for category_name, emoji in categories:
                display_emoji = emoji if emoji else "<:Ticket_icons:1382703084815257610>"
                category_list.append(f"• {display_emoji} {category_name}")
            
            embed = discord.Embed(
                title="<:clipboard1:1383857546410070117> Support Categories",
                description="\n".join(category_list),
                color=0x00D4FF,
                timestamp=current_time
            )
            embed.set_footer(text=f"Listed at {current_time.strftime('%I:%M %p GMT')}")
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in list_categories: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message)

    @commands.hybrid_command(name="send-panel", description="Send or update the support panel.")
    @app_commands.describe(type="The type of panel to send")
    @app_commands.choices(type=[
        app_commands.Choice(name="Dropdown", value="dropdown"),
        app_commands.Choice(name="Button", value="button")
    ])
    @app_commands.default_permissions(administrator=True)
    async def send_panel(self, ctx: commands.Context, type: str):
        logger.info(f"Send panel command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}: type={type}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            categories = await get_ticket_categories(self.bot, ctx.guild.id)
            if not categories:
                current_time = utc_to_gmt(discord.utils.utcnow())
                embed = discord.Embed(
                    title="<:icons_Wrong:1382701332955402341> No Categories Found",
                    description="You must create at least one ticket category before sending a panel.\n\n"
                              "**<:lightbulb:1382701619753386035> How to add categories:**\n"
                              "Use `/add-category <name>` to create categories.\n\n"
                              "**Examples:**\n"
                              "`/add-category Technical Support`\n"
                              "`/add-category General Help`\n"
                              "`/add-category Billing Issues`",
                    color=0xFF6B6B,
                    timestamp=current_time
                )
                embed.set_footer(text=f"Action at {current_time.strftime('%I:%M %p GMT')}")
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed, ephemeral=True)
                return

            success, message = await update_ticket_panel(self.bot, ctx.guild.id, panel_type=type)
            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:j_icons_Correct:1382701297987485706> Support Panel Sent" if success else "<:icons_Wrong:1382701332955402341> Error",
                description=message,
                color=0x00D4FF if success else 0xFF6B6B,
                timestamp=current_time
            )
            embed.set_footer(text=f"Action at {current_time.strftime('%I:%M %p GMT')}")
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

            if success:
                try:
                    async with self.bot.db.cursor() as cur:
                        await cur.execute(
                            "UPDATE tickets SET panel_type = ? WHERE guild_id = ?",
                            (type, ctx.guild.id)
                        )
                        await self.bot.db.commit()
                except Exception as e:
                    logger.error(f"Error updating panel type: {e}")

        except Exception as e:
            logger.error(f"Error in send_panel: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="close", description="Close the current support ticket.")
    async def close_ticket(self, ctx: commands.Context):
        logger.info(f"Close ticket command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if not await is_ticket_channel(self.bot, ctx.channel):
                message = "<:icons_Wrong:1382701332955402341> | This command can only be used in a support ticket channel."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            ticket_role = await get_ticket_role(self.bot, ctx.guild.id)
            if not ticket_role:
                message = "<:icons_Wrong:1382701332955402341> | Support system is not set up properly."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            ticket_creator_id = await get_ticket_creator(self.bot, ctx.channel.id)
            if not ticket_creator_id:
                message = "<:icons_Wrong:1382701332955402341> | Could not determine the ticket creator."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            from utils.tickets import get_ticket_creator_member
            ticket_creator = await get_ticket_creator_member(self.bot, ctx.guild, ctx.channel.id)

            if not ticket_creator:
                logger.warning(f"Ticket creator {ticket_creator_id} could not be retrieved for channel {ctx.channel.id}")
                class MockUser:
                    def __init__(self, user_id):
                        self.id = user_id
                        self.mention = f"<@{user_id}>"
                        self.display_name = "Unknown User"
                        self.name = "Unknown User"

                ticket_creator = MockUser(ticket_creator_id)

            invoker = ctx.author if isinstance(ctx, commands.Context) else ctx.user
            user_has_support = await user_has_support_role(self.bot, invoker)
            if not (invoker == ticket_creator or user_has_support):
                message = "<:icons_Wrong:1382701332955402341> | You do not have permission to close this ticket."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            from utils.tickets import get_ticket_info
            ticket_info = await get_ticket_info(self.bot, ctx.channel.id)

            if not ticket_info:
                message = "<:icons_Wrong:1382701332955402341> | Could not retrieve ticket information."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message, ephemeral=True)
                return

            ticket_data = {
                'creator_id': ticket_info['creator_id'],
                'ticket_number': ticket_info['ticket_number'],
                'category': ticket_info['category'],
                'subject': 'N/A',
                'description': 'N/A',
                'priority': ticket_info['priority']
            }

            confirmation_embed = discord.Embed(
                title="<:icons_locked:1382701901685985361> Close Ticket Confirmation",
                description="**Are you sure you want to close this ticket?**\n\nThis action cannot be undone.",
                color=0xFF6B6B
            )

            from views.ticket_views import TicketCloseConfirmationView
            view = TicketCloseConfirmationView(self.bot, ticket_data)

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=confirmation_embed, view=view, ephemeral=True)
            else:
                await ctx.send(embed=confirmation_embed, view=view, ephemeral=True)

        except discord.Forbidden as e:
            logger.error(f"Forbidden error in close_ticket: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | I don't have permission to delete the channel: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message)
        except Exception as e:
            logger.error(f"Error in close_ticket: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message)

    

    @commands.hybrid_command(name="set-limit", description="Set the ticket limit per user.")
    @app_commands.describe(limit="Maximum number of tickets a user can have open (1-10)")
    @commands.has_permissions(administrator=True)
    async def set_limit(self, ctx: commands.Context, limit: int):
        logger.info(f"Set limit command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}: {limit}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if limit < 1 or limit > 10:
                embed = discord.Embed(
                    title="<:icons_Wrong:1382701332955402341> Invalid Limit",
                    description="Ticket limit must be between 1 and 10.",
                    color=0xFF0000
                )
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed, ephemeral=True)
                return

            async with self.bot.db.cursor() as cur:
                await cur.execute(
                    "UPDATE tickets SET ticket_limit = ? WHERE guild_id = ?",
                    (limit, ctx.guild.id)
                )

                if cur.rowcount == 0:
                    embed = discord.Embed(
                        title="<:icons_Wrong:1382701332955402341> Setup Required",
                        description="Please run `/setup-tickets` first to configure the ticket system.",
                        color=0xFF0000
                    )
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(embed=embed, ephemeral=True)
                    else:
                        await ctx.send(embed=embed, ephemeral=True)
                    return

                await self.bot.db.commit()

            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:j_icons_Correct:1382701297987485706> Ticket Limit Updated",
                description=f"**New ticket limit:** {limit} tickets per user\n\nUsers can now have up to {limit} open tickets at once.",
                color=0x00D4FF,
                timestamp=current_time
            )
            embed.set_footer(text=f"Updated at {current_time.strftime('%I:%M %p GMT')}")

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in set_limit: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="reset-categories", description="Reset all ticket categories.")
    @commands.has_permissions(administrator=True)
    async def reset_categories(self, ctx: commands.Context):
        logger.info(f"Reset categories command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            success, message = await reset_ticket_categories(self.bot, ctx.guild.id)

            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:Icons_Trash:1382703995700645969> Categories Reset" if success else "<:icons_Wrong:1382701332955402341> Error",
                description=message,
                color=0x00D4FF if success else 0xFF6B6B,
                timestamp=current_time
            )
            embed.set_footer(text=f"Action at {current_time.strftime('%I:%M %p GMT')}")

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in reset_categories: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="transfer-ticket", description="Transfer ticket to another staff member.")
    @app_commands.describe(member="Staff member to transfer the ticket to")
    async def transfer_ticket(self, ctx: commands.Context, member: discord.Member):
        logger.info(f"Transfer ticket command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if not await is_ticket_channel(self.bot, ctx.channel):
                message = "<:icons_Wrong:1382701332955402341> | This command can only be used in a support ticket channel."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            invoker = ctx.author if isinstance(ctx, commands.Context) else ctx.user
            user_has_support = await user_has_support_role(self.bot, invoker)
            if not user_has_support:
                message = "<:icons_Wrong:1382701332955402341> | You do not have permission to transfer tickets."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            target_has_support = await user_has_support_role(self.bot, member)
            if not target_has_support:
                message = f"<:icons_Wrong:1382701332955402341> | {member.mention} does not have the support role."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:icons_Person:1382703571056853082> Ticket Transferred",
                description=f"**Transferred by:** {invoker.mention}\n"
                            f"**Transferred to:** {member.mention}\n"
                            f"**Transfer time:** {current_time.strftime('%I:%M %p GMT')}\n\n"
                            f"{member.mention}, this ticket has been assigned to you for handling.",
                color=0x00D4FF,
                timestamp=current_time
            )
            embed.set_footer(text=" Support System • Ticket Transfer")
            await ctx.channel.send(embed=embed)

            success_message = f"<:j_icons_Correct:1382701297987485706> | Ticket successfully transferred to {member.mention}."
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(success_message, ephemeral=True)
            else:
                await ctx.send(success_message, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in transfer_ticket: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="add-user", description="Add a user to the current ticket.")
    @app_commands.describe(user="User to add to the ticket")
    async def add_user(self, ctx: commands.Context, user: discord.Member):
        logger.info(f"Add user command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if not await is_ticket_channel(self.bot, ctx.channel):
                message = "<:icons_Wrong:1382701332955402341> | This command can only be used in a support ticket channel."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            invoker = ctx.author if isinstance(ctx, commands.Context) else ctx.user
            user_has_support = await user_has_support_role(self.bot, invoker)

            if not user_has_support:
                message = "<:icons_Wrong:1382701332955402341> | Only support staff can add users to tickets."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            await ctx.channel.set_permissions(
                user,
                view_channel=True,
                send_messages=True,
                reason=f"User added to ticket by {invoker}"
            )

            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:welcome:1382706419765350480> User Added to Ticket",
                description=f"**Added user:** {user.mention}\n"
                            f"**Added by:** {invoker.mention}\n"
                            f"**Added at:** {current_time.strftime('%I:%M %p GMT')}\n\n"
                            f"{user.mention}, you have been added to this support ticket.",
                color=0x00D4FF,
                timestamp=current_time
            )
            embed.set_footer(text=" Support System • User Management")
            await ctx.channel.send(embed=embed)

            success_message = f"<:j_icons_Correct:1382701297987485706> | {user.mention} has been added to the ticket."
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(success_message, ephemeral=True)
            else:
                await ctx.send(success_message, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in add_user: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="remove-user", description="Remove a user from the current ticket.")
    @app_commands.describe(user="User to remove from the ticket")
    async def remove_user(self, ctx: commands.Context, user: discord.Member):
        logger.info(f"Remove user command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if not await is_ticket_channel(self.bot, ctx.channel):
                message = "<:icons_Wrong:1382701332955402341> | This command can only be used in a support ticket channel."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            invoker = ctx.author if isinstance(ctx, commands.Context) else ctx.user
            user_has_support = await user_has_support_role(self.bot, invoker)

            if not user_has_support:
                message = "<:icons_Wrong:1382701332955402341> | Only support staff can remove users from tickets."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            ticket_creator_id = await get_ticket_creator(self.bot, ctx.channel.id)

            if user.id == ticket_creator_id:
                message = "<:icons_Wrong:1382701332955402341> | You cannot remove the ticket creator from their own ticket."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            ticket_role = await get_ticket_role(self.bot, ctx.guild.id)
            if ticket_role and ticket_role in user.roles:
                message = "<:icons_Wrong:1382701332955402341> | You cannot remove support staff from tickets."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            await ctx.channel.set_permissions(
                user,
                view_channel=False,
                send_messages=False,
                reason=f"User removed from ticket by {invoker}"
            )

            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> User Removed from Ticket",
                description=f"**Removed user:** {user.mention}\n"
                            f"**Removed by:** {invoker.mention}\n"
                            f"**Removed at:** {current_time.strftime('%I:%M %p GMT')}",
                color=0xFF6B6B,
                timestamp=current_time
            )
            embed.set_footer(text=" Support System • User Management")
            await ctx.channel.send(embed=embed)

            success_message = f"<:j_icons_Correct:1382701297987485706> | {user.mention} has been removed from the ticket."
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(success_message, ephemeral=True)
            else:
                await ctx.send(success_message, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in remove_user: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="ticket-info", description="Display detailed information about the current ticket.")
    async def ticket_info(self, ctx: commands.Context):
        logger.info(f"Ticket info command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if not await is_ticket_channel(self.bot, ctx.channel):
                message = "<:icons_Wrong:1382701332955402341> | This command can only be used in a support ticket channel."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            from utils.tickets import get_ticket_info
            ticket_info = await get_ticket_info(self.bot, ctx.channel.id)
            if not ticket_info:
                message = "<:icons_Wrong:1382701332955402341> | Could not retrieve ticket information."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return

            ticket_creator = ctx.guild.get_member(ticket_info['creator_id'])
            created_time = discord.utils.parse_time(ticket_info['created_at']) if ticket_info['created_at'] else discord.utils.utcnow()

            current_time = utc_to_gmt(discord.utils.utcnow())

            message_count = 0
            async for _ in ctx.channel.history(limit=None):
                message_count += 1

            accessible_users = []
            for member in ctx.guild.members:
                if ctx.channel.permissions_for(member).view_channel and not member.bot:
                    accessible_users.append(member)

            embed = discord.Embed(
                title=f"<:clipboard1:1383857546410070117> Ticket Information",
                description=f"**Channel:** {ctx.channel.mention}\n"
                            f"**Ticket ID:** `{ctx.channel.id}`",
                color=0x00D4FF,
                timestamp=current_time
            )

            embed.add_field(
                name="<:Ticket_icons:1382703084815257610> Ticket Details",
                value=f"**Number:** #{ticket_info['ticket_number']:04d}\n"
                      f"**Status:** <:j_icons_Correct:1382701297987485706> Open\n"
                      f"**Messages:** {message_count}",
                inline=True
            )

            embed.add_field(
                name="<:icons_Person:1382703571056853082> Creator Information",
                value=f"**User:** {ticket_creator.mention if ticket_creator else 'Unknown'}\n"
                      f"**ID:** `{ticket_info['creator_id']}`\n"
                      f"**Status:** {'Online' if ticket_creator and ticket_creator.status != discord.Status.offline else 'Offline'}",
                inline=True
            )

            embed.add_field(
                name="<:Icons_calender:1382703729504948265> Timeline",
                value=f"**Created:** {discord.utils.format_dt(created_time, 'R')}\n"
                      f"**Created Date:** {created_time.strftime('%B %d, %Y')}\n"
                      f"**Duration:** {discord.utils.format_dt(created_time, 'R')}",
                inline=False
            )

            embed.add_field(
                name="<:welcome:1382706419765350480> Access List",
                value=f"**Users with access:** {len(accessible_users)}\n" + 
                      (f"**Users:** " + ", ".join([user.mention for user in accessible_users[:5]]) + 
                       (f" and {len(accessible_users) - 5} more..." if len(accessible_users) > 5 else "")
                       if accessible_users else "No users with access"),
                inline=False
            )

            embed.set_footer(text=" Support System • Ticket Analytics")
            embed.set_thumbnail(url=ticket_creator.display_avatar.url if ticket_creator else ctx.guild.icon.url)

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in ticket_info: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)



    @commands.hybrid_command(name="rename", description="Rename the current ticket channel.")
    @app_commands.describe(name="New name for the ticket channel")
    async def rename_ticket(self, ctx: commands.Context, *, name: str):
        logger.info(f"Rename ticket command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if not await is_ticket_channel(self.bot, ctx.channel):
                embed = discord.Embed(
                    title="<:icons_Wrong:1382701332955402341> Not a Ticket Channel",
                    description="**This command can only be used in support ticket channels.**\n\n"
                               "<:Ticket_icons:1382703084815257610> This command is designed for ticket management and can only be used within active support tickets.",
                    color=0xFF6B6B
                )
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed, ephemeral=True)
                return

            invoker = ctx.author if isinstance(ctx, commands.Context) else ctx.user
            user_has_support = await user_has_support_role(self.bot, invoker)

            if not user_has_support:
                embed = discord.Embed(
                    title="<:icons_locked:1382701901685985361> Permission Denied",
                    description="**You don't have permission to rename this ticket.**\n\n"
                               "Only support staff members can rename tickets.",
                    color=0xFF6B6B
                )
                embed.add_field(
                    name="<:Target:1382706193855942737> Required Permission",
                    value="• **Support Staff** - Members with the support role",
                    inline=False
                )
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed, ephemeral=True)
                return

            if len(name) > 100:
                embed = discord.Embed(
                    title="<:icons_Wrong:1382701332955402341> Name Too Long",
                    description=f"**Channel name cannot exceed 100 characters.**\n\n"
                               f"**Your name:** {len(name)} characters\n"
                               f"**Maximum allowed:** 100 characters\n"
                               f"**Please shorten by:** {len(name) - 100} characters",
                    color=0xFF6B6B
                )
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed, ephemeral=True)
                return

            if len(name.strip()) == 0:
                embed = discord.Embed(
                    title="<:icons_Wrong:1382701332955402341> Invalid Name",
                    description="**Channel name cannot be empty.**\n\nPlease provide a valid name for the ticket channel.",
                    color=0xFF6B6B
                )
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed, ephemeral=True)
                return

            def sanitize_channel_name(input_name: str) -> str:
                sanitized = input_name.lower().strip()

                sanitized = re.sub(r'\s+', '-', sanitized)

                sanitized = re.sub(r'[^a-z0-9\-_]', '', sanitized)

                sanitized = re.sub(r'-+', '-', sanitized)

                sanitized = sanitized.strip('-_')

                if not sanitized:
                    sanitized = 'ticket-channel'

                if len(sanitized) > 100:
                    sanitized = sanitized[:100].rstrip('-_')

                return sanitized

            sanitized_name = sanitize_channel_name(name)

            if not sanitized_name:
                embed = discord.Embed(
                    title="<:icons_Wrong:1382701332955402341> Invalid Characters",
                    description="**The name contains only invalid characters.**\n\n"
                               "<:clipboard1:1383857546410070117> **Valid characters:**\n"
                               "• Letters (a-z)\n"
                               "• Numbers (0-9)\n"
                               "• Dashes (-)\n"
                               "• Underscores (_)\n\n"
                               "**Example:** `billing-issue` or `technical_support`",
                    color=0xFF6B6B
                )
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed, ephemeral=True)
                return

            old_name = ctx.channel.name

            if old_name == sanitized_name:
                embed = discord.Embed(
                    title="<:icons_Wrong:1382701332955402341> Same Name",
                    description=f"**The channel is already named `{sanitized_name}`.**\n\n"
                               "Please choose a different name for the ticket channel.",
                    color=0xFF6B6B
                )
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed, ephemeral=True)
                return

            name_changed = name.lower().replace(' ', '-') != sanitized_name
            if name_changed:
                preview_embed = discord.Embed(
                    title="<:clipboard1:1383857546410070117> Name Preview",
                    description="**Your channel name has been adjusted for Discord compatibility:**",
                    color=0xFF8C00
                )
                preview_embed.add_field(
                    name="Original Name",
                    value=f"`{name}`",
                    inline=True
                )
                preview_embed.add_field(
                    name="Discord-Compatible Name",
                    value=f"`{sanitized_name}`",
                    inline=True
                )
                preview_embed.add_field(
                    name="<:j_icons_Correct:1382701297987485706> Auto-Adjustments Made",
                    value="• Converted to lowercase\n• Replaced spaces with dashes\n• Removed special characters\n• Applied Discord naming rules",
                    inline=False
                )
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=preview_embed, ephemeral=True)
                else:
                    await ctx.send(embed=preview_embed, ephemeral=True)

            try:
                await ctx.channel.edit(
                    name=sanitized_name, 
                    reason=f"Ticket renamed by {invoker.display_name} ({invoker.id})"
                )
            except discord.HTTPException as e:
                error_msg = str(e).lower()
                if "name" in error_msg or "invalid" in error_msg:
                    embed = discord.Embed(
                        title="<:icons_Wrong:1382701332955402341> Invalid Channel Name",
                        description=f"**Discord rejected the channel name.**\n\n"
                                   f"**Error:** {str(e)}\n"
                                   f"**Attempted name:** `{sanitized_name}`\n\n"
                                   "Please try a different name with only letters, numbers, dashes, and underscores.",
                        color=0xFF6B6B
                    )
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(embed=embed, ephemeral=True)
                    else:
                        await ctx.send(embed=embed, ephemeral=True)
                    return
                else:
                    raise  # Re-raise if it's not a name-related error

            current_time = utc_to_gmt(discord.utils.utcnow())

            success_embed = discord.Embed(
                title="<:j_icons_Correct:1382701297987485706> Ticket Renamed Successfully",
                description=f"**Channel has been renamed to `{sanitized_name}`**",
                color=0x00FF88,
                timestamp=current_time
            )
            await ctx.channel.send(embed=success_embed)

            try:
                log_channel = await get_ticket_log_channel(self.bot, ctx.guild.id)
                if log_channel:
                    from utils.tickets import get_ticket_info
                    ticket_info = await get_ticket_info(self.bot, ctx.channel.id)

                    ticket_number_str = f"#{ticket_info['ticket_number']:04d}" if ticket_info else "#0000"

                    log_embed = discord.Embed(
                        title="<:clipboard1:1383857546410070117> Ticket Renamed",
                        description=f"Ticket `{ticket_number_str}` has been renamed by {invoker.mention}",
                        color=0x00D4FF,
                        timestamp=current_time
                    )
                    log_embed.add_field(
                        name="Channel Details",
                        value=f"**Channel:** {ctx.channel.mention} (`{ctx.channel.id}`)\n"
                              f"**Old Name:** `{old_name}`\n"
                              f"**New Name:** `{sanitized_name}`",
                        inline=False
                    )
                    log_embed.add_field(
                        name="Action Details", 
                        value=f"**Renamed By:** {invoker.display_name} (`{invoker.id}`)\n"
                              f"**Time:** {discord.utils.format_dt(current_time, 'F')}",
                        inline=False
                    )
                    log_embed.set_footer(text=" Support System • Channel Rename")

                    await log_channel.send(embed=log_embed)

            except Exception as log_error:
                logger.error(f"Error logging rename action: {log_error}")

            confirmation_message = f"<:j_icons_Correct:1382701297987485706> **Ticket successfully renamed to `{sanitized_name}`**"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(confirmation_message, ephemeral=True)

        except discord.Forbidden as e:
            logger.error(f"Permission error renaming ticket: {e}")
            embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Permission Error",
                description="**I don't have permission to rename this channel.**\n\n"
                           "<:icons_wrench:1382702984940617738> **Required Bot Permissions:**\n"
                           "• Manage Channels\n"
                           "• View Channel\n\n"
                           "Please ensure I have the proper permissions and try again.",
                color=0xFF6B6B
            )
            embed.add_field(
                name="🆘 Need Help?",
                value="Contact a server administrator to grant the bot 'Manage Channels' permission.",
                inline=False
            )
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

        except discord.HTTPException as e:
            logger.error(f"HTTP error renaming ticket: {e}")
            embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Discord API Error",
                description=f"**Discord rejected the rename request.**\n\n"
                           f"**Error:** {str(e)}\n\n"
                           "This might be due to rate limiting or invalid characters. Please try again in a moment.",
                color=0xFF6B6B
            )
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Unexpected error in rename_ticket: {e}")
            import traceback
            logger.error(traceback.format_exc())

            embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Unexpected Error",
                description=f"**An unexpected error occurred while renaming the ticket.**\n\n"
                           f"**Error:** {str(e)}\n\n"
                           "Please try again. If the issue persists, contact support.",
                color=0xFF6B6B
            )
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(name="claim", description="Claim the current ticket.")
    async def claim_ticket(self, ctx: commands.Context):
        logger.info(f"Claim ticket command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if not await is_ticket_channel(self.bot, ctx.channel):
                embed = discord.Embed(
                    title="<:icons_Wrong:1382701332955402341> Not a Ticket Channel",
                    description="**This command can only be used in support ticket channels.**\n\n"
                               "<:Ticket_icons:1382703084815257610> Use this command within an active support ticket to claim it for handling.",
                    color=0xFF6B6B
                )
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed, ephemeral=True)
                return

            invoker = ctx.author if isinstance(ctx, commands.Context) else ctx.user

            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT role_id FROM tickets WHERE guild_id = ?", (ctx.guild.id,))
                result = await cur.fetchone()

                if not result:
                    embed = discord.Embed(
                        title="<:icons_Wrong:1382701332955402341> System Configuration Error",
                        description="**Ticket system is not properly configured.**\n\n"
                                   "Please contact an administrator to resolve this issue.",
                        color=0xFF6B6B
                    )
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(embed=embed, ephemeral=True)
                    else:
                        await ctx.send(embed=embed, ephemeral=True)
                    return

                support_role_id = result[0]
                support_role = ctx.guild.get_role(support_role_id)

                has_support_role = support_role and support_role in invoker.roles
                is_admin = invoker.guild_permissions.administrator

                if not (has_support_role or is_admin):
                    embed = discord.Embed(
                        title="<:shield:1382703287891136564> Permission Denied",
                        description="**Only support staff can claim tickets.**\n\n"
                                   f"<:Target:1382706193855942737> **Required Role:** {support_role.mention if support_role else 'Support Role'}\n"
                                   f"<:icons_Person:1382703571056853082> **Your Roles:** {', '.join([role.mention for role in invoker.roles if role != ctx.guild.default_role][:3]) or 'No special roles'}\n\n"
                                   f"<:lightbulb:1382701619753386035> **Need access?** Contact an administrator to get the support role.",
                        color=0xFF6B6B
                    )
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(embed=embed, ephemeral=True)
                    else:
                        await ctx.send(embed=embed, ephemeral=True)
                    return

                await cur.execute("SELECT claimed_by, ticket_number, creator_id, category, priority FROM ticket_instances WHERE channel_id = ?", (ctx.channel.id,))
                ticket_result = await cur.fetchone()

                if not ticket_result:
                    embed = discord.Embed(
                        title="<:icons_Wrong:1382701332955402341> Ticket Not Found",
                        description="**Could not find ticket information.**\n\n"
                                   "This ticket may not be properly registered in the system.",
                        color=0xFF6B6B
                    )
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(embed=embed, ephemeral=True)
                    else:
                        await ctx.send(embed=embed, ephemeral=True)
                    return

                current_claimer_id, ticket_number, creator_id, category, priority = ticket_result

                if current_claimer_id:
                    if current_claimer_id == invoker.id:
                        embed = discord.Embed(
                            title="<:j_icons_Correct:1382701297987485706> Already Your Ticket",
                            description=f"**You have already claimed this ticket.**\n\n"
                                       f"<:Target:1382706193855942737> **Status:** This ticket is assigned to you\n"
                                       f"<:clipboard1:1383857546410070117> **Action:** Continue providing support\n"
                                       f"<:type_icons:1384042158801027136> **Next Step:** Assist the customer as normal",
                            color=0x00FF88
                        )
                        if isinstance(ctx, discord.Interaction):
                            await ctx.followup.send(embed=embed, ephemeral=True)
                        else:
                            await ctx.send(embed=embed, ephemeral=True)
                        return

                    claimer = ctx.guild.get_member(current_claimer_id)
                    embed = discord.Embed(
                        title="<:icons_locked:1382701901685985361> Ticket Already Claimed",
                        description=f"**This ticket is already being handled by another agent.**\n\n"
                                   f"<:Target:1382706193855942737> **Current Agent:** {claimer.mention if claimer else f'<@{current_claimer_id}>'}\n"
                                   f"<:label:1384044597386285121> **Agent Name:** {claimer.display_name if claimer else 'Unknown Agent'}\n"
                                   f"<:clipboard1:1383857546410070117> **Status:** 🟢 Currently Active\n\n"
                                   f"<:lightbulb:1382701619753386035> **Need to transfer?** Use `/transfer-ticket @new_agent` command",
                        color=0xFF8C00
                    )
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(embed=embed, ephemeral=True)
                    else:
                        await ctx.send(embed=embed, ephemeral=True)
                    return

                await cur.execute(
                    "UPDATE ticket_instances SET claimed_by = ? WHERE channel_id = ? AND claimed_by IS NULL",
                    (invoker.id, ctx.channel.id)
                )

                if cur.rowcount == 0:
                    embed = discord.Embed(
                        title="<a:lighting_icons:1383871485122449409> Claim Conflict",
                        description="**Another agent claimed this ticket at the same time.**\n\n"
                                   "Please refresh and try again if needed.",
                        color=0xFF8C00
                    )
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(embed=embed, ephemeral=True)
                    else:
                        await ctx.send(embed=embed, ephemeral=True)
                    return

                await self.bot.db.commit()

            ticket_creator = ctx.guild.get_member(creator_id)
            current_time = discord.utils.utcnow()

            if ticket_creator:
                creator_mention = ticket_creator.mention
            elif creator_id:
                creator_mention = f"<@{creator_id}>"
            else:
                creator_mention = "**Ticket Creator**"

            claim_message = f"{creator_mention} your ticket has been claimed by {invoker.mention}"

            await ctx.channel.send(claim_message)

            confirmation_msg = f"<:j_icons_Correct:1382701297987485706> You have successfully claimed ticket #{ticket_number:04d}!"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(confirmation_msg, ephemeral=True)
            else:
                try:
                    await invoker.send(confirmation_msg)
                except:
                    msg = await ctx.send(confirmation_msg)
                    await asyncio.sleep(3)
                    try:
                        await msg.delete()
                    except:
                        pass

            log_channel = await get_ticket_log_channel(self.bot, ctx.guild.id)
            if log_channel:
                try:
                    creator_name = ticket_creator.display_name if ticket_creator else "Unknown User"
                    creator_id_display = str(creator_id)

                    log_embed = discord.Embed(
                        title="Logs - Ticket Claimed!",
                        description=f"> Ticket `#{ticket_number:04d}` has been claimed {discord.utils.format_dt(current_time, 'R')}! ({discord.utils.format_dt(current_time, 'F')})\n\n"
                                   f"**Channel**\n```{ctx.channel.mention} ({ctx.channel.id})```"
                                   f"**Claimed By**\n```{invoker.display_name} ({invoker.id})```"
                                   f"**Ticket Creator**\n```{creator_name} ({creator_id_display})```"
                                   f"**Category**\n```{category}```"
                                   f"**Priority**\n```{priority}```",
                        color=0x00D4FF,
                        timestamp=current_time
                    )
                    log_embed.set_footer(text=" Support System • Ticket Claimed")
                    log_embed.set_thumbnail(url=invoker.display_avatar.url)

                    await log_channel.send(embed=log_embed)

                except Exception as log_error:
                    logger.error(f"Error logging claim action: {log_error}")

        except Exception as e:
            logger.error(f"Error in claim_ticket: {e}")
            import traceback
            logger.error(traceback.format_exc())

            error_embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Claim Error",
                description=f"**An error occurred while claiming the ticket.**\n\n"
                           f"**Error:** {str(e)}\n\n"
                           f"Please try again. If the issue persists, contact an administrator.",
                color=0xFF6B6B
            )
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=error_embed, ephemeral=True)
            else:
                await ctx.send(embed=error_embed, ephemeral=True)

    @commands.hybrid_command(name="blacklist-user", description="Blacklist a user from creating tickets.")
    @app_commands.describe(user="User to blacklist from creating tickets")
    @commands.has_permissions(administrator=True)
    async def blacklist_user(self, ctx: commands.Context, user: discord.Member):
        logger.info(f"Blacklist user command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}: {user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            async with self.bot.db.cursor() as cur:
                await cur.execute(
                    "SELECT 1 FROM ticket_blacklist WHERE guild_id = ? AND user_id = ?",
                    (ctx.guild.id, user.id)
                )
                if await cur.fetchone():
                    embed = discord.Embed(
                        title="<:icons_Wrong:1382701332955402341> Already Blacklisted",
                        description=f"**{user.mention} is already blacklisted.**\n\n"
                                   f"This user cannot create tickets in this server.",
                        color=0xFF6B6B
                    )
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(embed=embed, ephemeral=True)
                    else:
                        await ctx.send(embed=embed, ephemeral=True)
                    return

                await cur.execute(
                    "INSERT INTO ticket_blacklist (guild_id, user_id, blacklisted_by, blacklisted_at) VALUES (?, ?, ?, ?)",
                    (ctx.guild.id, user.id, ctx.author.id if isinstance(ctx, commands.Context) else ctx.user.id, discord.utils.utcnow().isoformat())
                )
                await self.bot.db.commit()

            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:icons_locked:1382701901685985361> User Blacklisted",
                description=f"**{user.mention} has been blacklisted from creating tickets.**\n\n"
                           f"<:Target:1382706193855942737> **User:** {user.display_name} (`{user.id}`)\n"
                           f"<:icons_Person:1382703571056853082> **Blacklisted by:** {ctx.author.mention if isinstance(ctx, commands.Context) else ctx.user.mention}\n"
                           f"<:Icons_calender:1382703729504948265> **Date:** {current_time.strftime('%B %d, %Y at %I:%M %p GMT')}",
                color=0xFF6B6B,
                timestamp=current_time
            )
            embed.add_field(
                name="<:lightbulb:1382701619753386035> Effect",
                value="• User cannot create new tickets\n"
                      "• Existing tickets remain unaffected\n"
                      "• Can be removed with `blacklist-remove-user`",
                inline=False
            )
            embed.set_footer(text=" Support System • User Blacklist")

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in blacklist_user: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="blacklist-remove-user", description="Remove a user from the ticket blacklist.")
    @app_commands.describe(user="User to remove from blacklist")
    @commands.has_permissions(administrator=True)
    async def blacklist_remove_user(self, ctx: commands.Context, user: discord.Member):
        logger.info(f"Blacklist remove user command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}: {user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            async with self.bot.db.cursor() as cur:
                await cur.execute(
                    "SELECT blacklisted_by, blacklisted_at FROM ticket_blacklist WHERE guild_id = ? AND user_id = ?",
                    (ctx.guild.id, user.id)
                )
                result = await cur.fetchone()
                
                if not result:
                    embed = discord.Embed(
                        title="<:icons_Wrong:1382701332955402341> User Not Blacklisted",
                        description=f"**{user.mention} is not currently blacklisted.**\n\n"
                                   f"This user can already create tickets normally.",
                        color=0xFF6B6B
                    )
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(embed=embed, ephemeral=True)
                    else:
                        await ctx.send(embed=embed, ephemeral=True)
                    return

                await cur.execute(
                    "DELETE FROM ticket_blacklist WHERE guild_id = ? AND user_id = ?",
                    (ctx.guild.id, user.id)
                )
                await self.bot.db.commit()

            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:j_icons_Correct:1382701297987485706> User Removed from Blacklist",
                description=f"**{user.mention} has been removed from the ticket blacklist.**\n\n"
                           f"<:Target:1382706193855942737> **User:** {user.display_name} (`{user.id}`)\n"
                           f"<:icons_Person:1382703571056853082> **Removed by:** {ctx.author.mention if isinstance(ctx, commands.Context) else ctx.user.mention}\n"
                           f"<:Icons_calender:1382703729504948265> **Removed on:** {current_time.strftime('%B %d, %Y at %I:%M %p GMT')}",
                color=0x00FF88,
                timestamp=current_time
            )
            embed.add_field(
                name="<:j_icons_Correct:1382701297987485706> Effect",
                value="• User can now create tickets normally\n"
                      "• Previous blacklist restrictions lifted\n"
                      "• Full access to support system restored",
                inline=False
            )
            embed.set_footer(text=" Support System • Blacklist Removal")

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in blacklist_remove_user: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="blacklist-list", description="View all blacklisted users in this server.")
    @commands.has_permissions(administrator=True)
    async def blacklist_list(self, ctx: commands.Context):
        logger.info(f"Blacklist list command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            async with self.bot.db.cursor() as cur:
                await cur.execute(
                    "SELECT user_id, blacklisted_by, blacklisted_at FROM ticket_blacklist WHERE guild_id = ? ORDER BY blacklisted_at DESC",
                    (ctx.guild.id,)
                )
                blacklisted = await cur.fetchall()

            if not blacklisted:
                embed = discord.Embed(
                    title="<:j_icons_Correct:1382701297987485706> No Blacklisted Users",
                    description="**No users are currently blacklisted from creating tickets.**\n\n"
                               "All members can create tickets normally.",
                    color=0x00FF88
                )
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed, ephemeral=True)
                return

            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:icons_locked:1382701901685985361> Blacklisted Users",
                description=f"**{len(blacklisted)} user(s) currently blacklisted from creating tickets.**",
                color=0xFF6B6B,
                timestamp=current_time
            )

            blacklist_text = ""
            for user_id, blacklisted_by, blacklisted_at in blacklisted[:10]:  # Limit to 10 for embed space
                user = ctx.guild.get_member(user_id)
                blacklister = ctx.guild.get_member(blacklisted_by)
                
                user_display = user.mention if user else f"<@{user_id}>"
                blacklister_display = blacklister.display_name if blacklister else "Unknown"
                
                try:
                    blacklist_date = discord.utils.parse_time(blacklisted_at)
                    date_display = discord.utils.format_dt(blacklist_date, 'R')
                except:
                    date_display = "Unknown date"
                
                blacklist_text += f"• {user_display} - by {blacklister_display} {date_display}\n"

            embed.add_field(
                name="<:clipboard1:1383857546410070117> Blacklisted Users",
                value=blacklist_text if blacklist_text else "No users found",
                inline=False
            )

            if len(blacklisted) > 10:
                embed.add_field(
                    name="<:lightbulb:1382701619753386035> Note",
                    value=f"Showing first 10 of {len(blacklisted)} blacklisted users.",
                    inline=False
                )

            embed.set_footer(text=" Support System • Blacklist Management")

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in blacklist_list: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="faq", description="Display frequently asked questions.")
    async def faq(self, ctx: commands.Context):
        logger.info(f"FAQ command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:icons_help:1382704281945112645> Frequently Asked Questions",
                description="**Welcome to our comprehensive FAQ section!**\n\nSelect a category below to find answers to common questions about our  support system.",
                color=0x00D4FF,
                timestamp=current_time
            )

            embed.add_field(
                name="<:icons_help:1382704281945112645> **Available Categories**",
                value="**<:Ticket_icons:1382703084815257610> Getting Started** - Creating tickets, basics\n"
                      "**<:icons_clock:1382701751206936697> Response & Priority** - Response times, urgency\n"
                      "**<:Target:1382706193855942737> Ticket Management** - Managing, closing, users\n"
                      "**<:clipboard1:1383857546410070117> Features & Settings** - Transcripts, limits, ratings\n"
                      "**<:icons_wrench:1382702984940617738> Troubleshooting** - Common issues, solutions",
                inline=False
            )

            embed.add_field(
                name="<:UA_Rocket_icons:1382701592851124254> **Quick Access**",
                value="Need immediate help? Create a support ticket for personalized assistance from our expert team!",
                inline=False
            )

            embed.set_footer(text="Harly Xploitz •  Support System • Interactive FAQ")
            embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else self.bot.user.display_avatar.url)

            view = FAQCategoryView(self.bot)
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                await ctx.send(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error in faq: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="maintenance-mode", description="Toggle maintenance mode to disable ticket creation.")
    @commands.has_permissions(administrator=True)
    async def maintenance_mode(self, ctx: commands.Context):
        logger.info(f"Maintenance mode command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT maintenance_mode FROM tickets WHERE guild_id = ?", (ctx.guild.id,))
                result = await cur.fetchone()

                if not result:
                    message = "<:icons_Wrong:1382701332955402341> | Support system is not set up. Use `/setup-tickets` first."
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(message, ephemeral=True)
                    else:
                        await ctx.send(message, ephemeral=True)
                    return

                current_mode = bool(result[0]) if result[0] is not None else False
                new_mode = not current_mode

                await cur.execute(
                    "UPDATE tickets SET maintenance_mode = ? WHERE guild_id = ?",
                    (new_mode, ctx.guild.id)
                )
                await self.bot.db.commit()

            current_time = utc_to_gmt(discord.utils.utcnow())
            status = "ENABLED" if new_mode else "DISABLED"
            color = 0xFF6B6B if new_mode else 0x00FF88
            emoji = "<:icons_wrench:1382702984940617738>" if new_mode else "<:j_icons_Correct:1382701297987485706>"

            embed = discord.Embed(
                title=f"{emoji} Maintenance Mode {status}",
                description=f"**Maintenance mode has been {status.lower()}.**\n\n"
                           f"{'<:warning:1382701413284446228> **Ticket creation is now disabled.** Users cannot create new tickets.' if new_mode else '<:j_icons_Correct:1382701297987485706> **Ticket creation is now enabled.** Users can create tickets normally.'}\n\n"
                           f"**Status:** {'<:icons_wrench:1382702984940617738> Under Maintenance' if new_mode else '🟢 Operational'}\n"
                           f"**Changed by:** {ctx.author.mention if isinstance(ctx, commands.Context) else ctx.user.mention}\n"
                           f"**Changed at:** {current_time.strftime('%I:%M %p GMT')}",
                color=color,
                timestamp=current_time
            )
            embed.set_footer(text=" Support System • Maintenance Control")

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in maintenance_mode: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="announce", description="Send an announcement to all open tickets.")
    @app_commands.describe(message="The announcement message to send to all open tickets")
    @commands.has_permissions(administrator=True)
    async def announce(self, ctx: commands.Context, *, message: str):
        logger.info(f"Announce command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if len(message) > 2000:
                error_message = "<:icons_Wrong:1382701332955402341> | Announcement message cannot exceed 2000 characters."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(error_message, ephemeral=True)
                else:
                    await ctx.send(error_message, ephemeral=True)
                return

            async with self.bot.db.cursor() as cur:
                await cur.execute(
                    "SELECT channel_id, ticket_number, creator_id FROM ticket_instances WHERE guild_id = ? AND status = 'open'",
                    (ctx.guild.id,)
                )
                tickets = await cur.fetchall()

            if not tickets:
                message_text = "<:megaphone:1382704888294936649> | No open tickets found to send announcements to."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(message_text, ephemeral=True)
                else:
                    await ctx.send(message_text, ephemeral=True)
                return

            current_time = utc_to_gmt(discord.utils.utcnow())
            announcement_embed = discord.Embed(
                title="<:megaphone:1382704888294936649> System Announcement",
                description=f"**Official announcement from {ctx.guild.name} support team:**\n\n{message}",
                color=0xFF8C00,
                timestamp=current_time
            )
            announcement_embed.add_field(
                name="<:clipboard1:1383857546410070117> Announcement Details",
                value=f"**Sent by:** {ctx.author.display_name if isinstance(ctx, commands.Context) else ctx.user.display_name}\n"
                      f"**Sent at:** {current_time.strftime('%I:%M %p GMT, %A, %B %d, %Y')}\n"
                      f"**Type:** System-wide notification",
                inline=False
            )
            announcement_embed.set_footer(text=" Support System • Official Announcement")
            if ctx.guild.icon:
                announcement_embed.set_thumbnail(url=ctx.guild.icon.url)

            success_count = 0
            failed_count = 0

            for channel_id, ticket_number, creator_id in tickets:
                try:
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        await channel.send(embed=announcement_embed)
                        success_count += 1
                except Exception as e:
                    logger.warning(f"Failed to send announcement to ticket #{ticket_number:04d}: {e}")
                    failed_count += 1

            result_embed = discord.Embed(
                title="<:megaphone:1382704888294936649> Announcement Sent",
                description=f"**Your announcement has been delivered to open tickets.**\n\n"
                           f"**<:stats_1:1382703019334045830> Delivery Summary:**\n"
                           f"<:j_icons_Correct:1382701297987485706> **Successfully sent:** {success_count} tickets\n"
                           f"<:icons_Wrong:1382701332955402341> **Failed to send:** {failed_count} tickets\n"
                           f"<:clipboard1:1383857546410070117> **Total tickets:** {len(tickets)} tickets\n\n"
                           f"**<:clipboard1:1383857546410070117> Message Preview:**\n*{message[:100]}{'...' if len(message) > 100 else ''}*",
                color=0x00D4FF,
                timestamp=current_time
            )
            result_embed.set_footer(text=" Support System • Announcement Complete")

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=result_embed, ephemeral=True)
            else:
                await ctx.send(embed=result_embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in announce: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="support-role-add", description="Add an additional support role.")
    @app_commands.describe(role="Role to add as additional support staff")
    @commands.has_permissions(administrator=True)
    async def support_role_add(self, ctx: commands.Context, role: discord.Role):
        logger.info(f"Support role add command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT role_id FROM tickets WHERE guild_id = ?", (ctx.guild.id,))
                primary_role = await cur.fetchone()
                
                if primary_role and primary_role[0] == role.id:
                    embed = discord.Embed(
                        title="<:icons_Wrong:1382701332955402341> Cannot Add Primary Role",
                        description=f"**{role.mention} is already the primary support role.**\n\nUse this command to add additional support roles only.",
                        color=0xFF6B6B
                    )
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(embed=embed, ephemeral=True)
                    else:
                        await ctx.send(embed=embed, ephemeral=True)
                    return

                await cur.execute(
                    "SELECT 1 FROM additional_support_roles WHERE guild_id = ? AND role_id = ?",
                    (ctx.guild.id, role.id)
                )
                if await cur.fetchone():
                    embed = discord.Embed(
                        title="<:icons_Wrong:1382701332955402341> Role Already Added",
                        description=f"**{role.mention} is already an additional support role.**\n\nThis role can already manage tickets.",
                        color=0xFF6B6B
                    )
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(embed=embed, ephemeral=True)
                    else:
                        await ctx.send(embed=embed, ephemeral=True)
                    return

            from utils.database import add_support_role
            success, message = await add_support_role(self.bot, ctx.guild.id, role.id)

            embed = discord.Embed(
                title="<:j_icons_Correct:1382701297987485706> Support Role Added" if success else "<:icons_Wrong:1382701332955402341> Error",
                description=f"**{role.mention} has been added as an additional support role.**\n\nMembers with this role can now manage tickets." if success else message,
                color=0x00FF88 if success else 0xFF6B6B,
                timestamp=discord.utils.utcnow()
            )

            if success:
                embed.add_field(
                    name="<:Target:1382706193855942737> Permissions Granted",
                    value="• Claim and transfer tickets\n• Close tickets\n• Change ticket priorities\n• Add/remove users from tickets\n• Rename ticket channels",
                    inline=False
                )

            embed.set_footer(text="Support System • Role Management")

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in support_role_add: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="support-role-remove", description="Remove an additional support role.")
    @app_commands.describe(role="Role to remove from additional support staff")
    @commands.has_permissions(administrator=True)
    async def support_role_remove(self, ctx: commands.Context, role: discord.Role):
        logger.info(f"Support role remove command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT role_id FROM tickets WHERE guild_id = ?", (ctx.guild.id,))
                primary_role = await cur.fetchone()
                
                if primary_role and primary_role[0] == role.id:
                    embed = discord.Embed(
                        title="<:icons_Wrong:1382701332955402341> Cannot Remove Primary Role",
                        description=f"**{role.mention} is the primary support role and cannot be removed.**\n\nUse `/setup-tickets` to change the primary support role.",
                        color=0xFF6B6B
                    )
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(embed=embed, ephemeral=True)
                    else:
                        await ctx.send(embed=embed, ephemeral=True)
                    return

            from utils.database import remove_support_role
            success, message = await remove_support_role(self.bot, ctx.guild.id, role.id)

            embed = discord.Embed(
                title="<:j_icons_Correct:1382701297987485706> Support Role Removed" if success else "<:icons_Wrong:1382701332955402341> Error",
                description=f"**{role.mention} has been removed from additional support roles.**\n\nMembers with this role can no longer manage tickets." if success else message,
                color=0x00FF88 if success else 0xFF6B6B,
                timestamp=discord.utils.utcnow()
            )

            embed.set_footer(text="Support System • Role Management")

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in support_role_remove: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="support-role-list", description="List all support roles.")
    @commands.has_permissions(administrator=True)
    async def support_role_list(self, ctx: commands.Context):
        logger.info(f"Support role list command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT role_id FROM tickets WHERE guild_id = ?", (ctx.guild.id,))
                primary_role_result = await cur.fetchone()

            from utils.database import get_additional_support_roles
            additional_roles = await get_additional_support_roles(self.bot, ctx.guild.id)

            embed = discord.Embed(
                title="<:people_icons:1384040549937451068> Support Roles",
                description="**All roles that can manage tickets in this server:**",
                color=0x00D4FF,
                timestamp=discord.utils.utcnow()
            )

            primary_role_text = "None configured"
            if primary_role_result and primary_role_result[0]:
                primary_role = ctx.guild.get_role(primary_role_result[0])
                primary_role_text = primary_role.mention if primary_role else f"<@&{primary_role_result[0]}> (Role deleted)"

            embed.add_field(
                name="<:shield:1382703287891136564> Primary Support Role",
                value=primary_role_text,
                inline=False
            )

            if additional_roles:
                additional_role_list = []
                for role_id in additional_roles:
                    role = ctx.guild.get_role(role_id)
                    if role:
                        additional_role_list.append(f"• {role.mention}")
                    else:
                        additional_role_list.append(f"• <@&{role_id}> (Role deleted)")

                embed.add_field(
                    name="<:Target:1382706193855942737> Additional Support Roles",
                    value="\n".join(additional_role_list) if additional_role_list else "None configured",
                    inline=False
                )
            else:
                embed.add_field(
                    name="<:Target:1382706193855942737> Additional Support Roles",
                    value="None configured",
                    inline=False
                )

            total_roles = 1 if primary_role_result and primary_role_result[0] else 0
            total_roles += len(additional_roles)

            embed.add_field(
                name="<:stats_1:1382703019334045830> Summary",
                value=f"**Total Support Roles:** {total_roles}\n**Primary Role:** {'✅ Configured' if primary_role_result and primary_role_result[0] else '❌ Not configured'}\n**Additional Roles:** {len(additional_roles)}",
                inline=False
            )

            embed.set_footer(text="Support System • Role Management")

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in support_role_list: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> An error occurred: {e}"
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_message, ephemeral=True)
            else:
                await ctx.send(error_message, ephemeral=True)

    @commands.hybrid_command(name="priority", description="Change the priority of the current ticket.")
    @app_commands.describe(priority="Priority level to set")
    @app_commands.choices(priority=[
        app_commands.Choice(name="🟢 Low Priority", value="Low"),
        app_commands.Choice(name="🟡 Medium Priority", value="Medium"),
        app_commands.Choice(name="🟠 High Priority", value="High"),
        app_commands.Choice(name="🔴 Critical Priority", value="Critical")
    ])
    async def priority_command(self, ctx: commands.Context, priority: str):
        logger.info(f"Priority command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if not await is_ticket_channel(self.bot, ctx.channel):
                embed = discord.Embed(
                    title="<:icons_Wrong:1382701332955402341> Not a Ticket Channel",
                    description="**This command can only be used in support ticket channels.**\n\n"
                               "<:Ticket_icons:1382703084815257610> Use this command within an active support ticket to change its priority.",
                    color=0xFF6B6B
                )
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed, ephemeral=True)
                return

            invoker = ctx.author if isinstance(ctx, commands.Context) else ctx.user
            user_has_support = await user_has_support_role(self.bot, invoker)
            is_admin = invoker.guild_permissions.administrator

            if not (user_has_support or is_admin):
                embed = discord.Embed(
                    title="<:icons_locked:1382701901685985361> Permission Denied",
                    description="**Only support staff can change ticket priority.**\n\n"
                               "You need to have at least one support role to modify ticket priorities.",
                    color=0xFF6B6B
                )
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed, ephemeral=True)
                return

            async with self.bot.db.cursor() as cur:
                await cur.execute(
                    "UPDATE ticket_instances SET priority = ? WHERE channel_id = ?",
                    (priority, ctx.channel.id)
                )
                await self.bot.db.commit()

            priority_emojis = {
                "Low": "🟢",
                "Medium": "🟡", 
                "High": "🟠",
                "Critical": "🔴"
            }
            
            priority_emoji = priority_emojis.get(priority, "🟡")

            current_name = ctx.channel.name
            clean_name = re.sub(r'^[🟢🟡🟠🔴]\s*', '', current_name)
            new_name = f"{priority_emoji} {clean_name}"
            
            try:
                await ctx.channel.edit(
                    name=new_name,
                    reason=f"Priority changed to {priority} by {invoker.display_name}"
                )
            except discord.HTTPException as e:
                logger.warning(f"Could not rename channel: {e}")

            try:
                async for message in ctx.channel.history(limit=50):
                    if (message.author == self.bot.user and 
                        message.embeds and 
                        len(message.embeds) > 0 and
                        ("Support Ticket" in message.embeds[0].title or "Ticket" in message.embeds[0].title) and
                        message.components):
                        
                        embed = discord.Embed(
                            title=message.embeds[0].title,
                            description=message.embeds[0].description,
                            color=message.embeds[0].color,
                            timestamp=message.embeds[0].timestamp
                        )
                        
                        for field in message.embeds[0].fields:
                            if "Ticket Information" in field.name:
                                field_lines = field.value.split('\n')
                                updated_lines = []
                                for line in field_lines:
                                    if line.startswith('**Priority:**'):
                                        updated_lines.append(f"**Priority:** {priority_emoji} {priority}")
                                    else:
                                        updated_lines.append(line)
                                embed.add_field(name=field.name, value='\n'.join(updated_lines), inline=field.inline)
                            else:
                                embed.add_field(name=field.name, value=field.value, inline=field.inline)
                        
                        if message.embeds[0].image:
                            embed.set_image(url=message.embeds[0].image.url)
                        if message.embeds[0].footer:
                            embed.set_footer(text=message.embeds[0].footer.text, icon_url=message.embeds[0].footer.icon_url)
                        if message.embeds[0].thumbnail:
                            embed.set_thumbnail(url=message.embeds[0].thumbnail.url)
                        
                        from views.ticket_views import TicketControlView
                        fresh_view = TicketControlView(self.bot, {'priority': priority}, priority_used=True)
                        await message.edit(embed=embed, view=fresh_view)
                        logger.info(f"Successfully updated control panel embed with new priority: {priority}")
                        break
                        
            except Exception as edit_error:
                logger.warning(f"Could not update control menu embed: {edit_error}")

            embed = discord.Embed(
                title=f"<:j_icons_Correct:1382701297987485706> Priority Updated",
                description=f"**{invoker.display_name}** changed this ticket priority to **{priority_emoji} {priority}**.\n\nChannel name and control panel updated with new priority.",
                color=0x00D4FF,
                timestamp=datetime.now(timezone.utc)
            )

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in priority command: {e}")
            error_embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Error",
                description=f"Failed to set priority: {str(e)}",
                color=0xFF6B6B
            )
            
            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(error_embed, ephemeral=True)
            else:
                await ctx.send(error_embed, ephemeral=True)

    @commands.hybrid_command(name="remind", description="Set an advanced reminder for ticket follow-up.")
    @app_commands.describe(
        time="Time format: 5m, 1h, 2d (minutes, hours, days)",
        message="Reminder message (optional)"
    )
    async def remind(self, ctx: commands.Context, time: str, *, message: Optional[str] = None):
        logger.info(f"Remind command invoked by {ctx.author if isinstance(ctx, commands.Context) else ctx.user}")
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            user_has_support = await user_has_support_role(self.bot, ctx.author if isinstance(ctx, commands.Context) else ctx.user)
            is_ticket_channel = await is_ticket_channel(self.bot, ctx.channel)

            if not (user_has_support or is_ticket_channel):
                error_message = "<:icons_Wrong:1382701332955402341> | You can only set reminders in ticket channels or if you have the support role."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(error_message, ephemeral=True)
                else:
                    await ctx.send(error_message, ephemeral=True)
                return

            import re
            time_pattern = r'^(\d+)([mhd])$'
            match = re.match(time_pattern, time.lower())

            if not match:
                error_message = "<:icons_Wrong:1382701332955402341> | Invalid time format. Use: 5m (minutes), 1h (hours), 2d (days)"
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(error_message, ephemeral=True)
                else:
                    await ctx.send(error_message, ephemeral=True)
                return

            amount = int(match.group(1))
            unit = match.group(2)

            multipliers = {'m': 60, 'h': 3600, 'd': 86400}
            delay_seconds = amount * multipliers[unit]

            if delay_seconds < 60:  # Minimum 1 minute
                error_message = "<:icons_Wrong:1382701332955402341> | Reminder time must be at least 1 minute."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(error_message, ephemeral=True)
                else:
                    await ctx.send(error_message, ephemeral=True)
                return

            if delay_seconds > 604800:  # Maximum 7 days
                error_message = "<:icons_Wrong:1382701332955402341> | Reminder time cannot exceed 7 days."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(error_message, ephemeral=True)
                else:
                    await ctx.send(error_message, ephemeral=True)
                return

            if not message:
                message = "<:icons_clock:1382701751206936697> **Reminder:** This is your scheduled follow-up reminder."

            current_time = utc_to_gmt(discord.utils.utcnow())
            remind_time = current_time + timedelta(seconds=delay_seconds)

            time_units = {'m': 'minutes', 'h': 'hours', 'd': 'days'}
            embed = discord.Embed(
                title="<:icons_clock:1382701751206936697> Advanced Reminder Set",
                description=f"**Your reminder has been scheduled successfully!**\n\n"
                           f"<:Icons_calender:1382703729504948265> **Reminder Details:**\n"
                           f"<:icons_clock:1382701751206936697> **Trigger Time:** {discord.utils.format_dt(remind_time, 'F')}\n"
                           f"📍 **In:** {amount} {time_units[unit]}\n"
                           f"📍 **Relative:** {discord.utils.format_dt(remind_time, 'R')}\n"
                           f"<:clipboard1:1383857546410070117> **Channel:** {ctx.channel.mention}\n"
                           f"<:icons_Person:1382703571056853082> **Set by:** {ctx.author.mention if isinstance(ctx, commands.Context) else ctx.user.mention}\n\n"
                           f"<:type_icons:1384042158801027136> **Reminder Message:**\n*{message}*",
                color=0x00D4FF,
                timestamp=current_time
            )
            embed.set_footer(text=" Support System • Advanced Reminder System")

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)

            await asyncio.sleep(delay_seconds)

            reminder_embed = discord.Embed(
                title="<:icons_clock:1382701751206936697> Scheduled Reminder",
                description=f"**This is your scheduled reminder!**\n\n"
                           f"<:clipboard1:1383857546410070117> **Message:** {message}\n\n"
                           f"<:clipboard1:1383857546410070117> **Reminder Details:**\n"
                           f"<:icons_Person:1382703571056853082> **Set by:** {ctx.author.mention if isinstance(ctx, commands.Context) else ctx.user.mention}\n"
                           f"<:icons_clock:1382701751206936697> **Set at:** {discord.utils.format_dt(current_time, 'F')}\n"
                           f"<:icons_clock:1382701751206936697> **Triggered after:** {amount} {time_units[unit]}\n"
                           f"📍 **Channel:** {ctx.channel.mention}",
                color=0xFF8C00,
                timestamp=discord.utils.utcnow()
            )
            reminder_embed.set_footer(text=" Support System • Reminder Alert")

            try:
                await ctx.channel.send(embed=reminder_embed)

                user = ctx.author if isinstance(ctx, commands.Context) else ctx.user
                await ctx.channel.send(f"{user.mention} - Your reminder is here!")

            except Exception as e:
                logger.warning(f"Failed to send reminder: {e}")

        except Exception as e:
            logger.error(f"Error in remind: {e}")
            error_message = f"<:icons_Wrong:1382701332955402341> | An error occurred: {str(e)}"
            
            try:
                if isinstance(ctx, discord.Interaction):
                    if ctx.response.is_done():
                        await ctx.followup.send(error_message, ephemeral=True)
                    else:
                        await ctx.response.send_message(error_message, ephemeral=True)
                else:
                    await ctx.send(error_message)
            except Exception as send_error:
                logger.error(f"Failed to send error message: {send_error}")

class FAQCategoryView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=300)
        self.bot = bot

    @discord.ui.select(
        placeholder="Select FAQ category",
        options=[
            discord.SelectOption(
                label="Getting Started",
                value="getting_started",
                emoji="<:Ticket_icons:1382703084815257610>",
                description="Creating tickets, basics & first steps"
            ),
            discord.SelectOption(
                label="Response & Priority",
                value="response_priority",
                emoji="<:icons_clock:1382701751206936697>",
                description="Response times, priority levels & urgency"
            ),
            discord.SelectOption(
                label="Ticket Management",
                value="ticket_management",
                emoji="<:Target:1382706193855942737>",
                description="Managing tickets, closing & user access"
            ),
            discord.SelectOption(
                label="Features & Settings",
                value="features_settings",
                emoji="<:clipboard1:1383857546410070117>",
                description="Transcripts, limits, ratings & features"
            ),
            discord.SelectOption(
                label="Troubleshooting",
                value="troubleshooting",
                emoji="<:icons_wrench:1382702984940617738>",
                description="Common issues, solutions & fixes"
            )
        ]
    )
    async def faq_category_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        try:
            category = select.values[0]
            current_time = utc_to_gmt(discord.utils.utcnow())

            if category == "getting_started":
                embed = discord.Embed(
                    title="<:Ticket_icons:1382703084815257610> Getting Started with Support Tickets",
                    description="Everything you need to know about creating and using support tickets.",
                    color=0x00FF88,
                    timestamp=current_time
                )

                embed.add_field(
                    name="<:UA_Rocket_icons:1382701592851124254> **How do I create a ticket?**",
                    value="• Look for the support panel in your server\n"
                          "• Click the dropdown or button for your issue type\n"
                          "• Fill out the ticket creation form\n"
                          "• Submit and wait for your private channel to be created\n"
                          "• Start chatting with our support team!",
                    inline=False
                )

                embed.add_field(
                    name="<:j_icons_Correct:1382701297987485706> **What happens after I create a ticket?**",
                    value="• A private channel is created just for you\n"
                          "• Only you and support staff can see it\n"
                          "• You'll receive a confirmation message\n"
                          "• Support team gets notified immediately\n"
                          "• You can chat freely about your issue",
                    inline=False
                )

                embed.add_field(
                    name="<:lightbulb:1382701619753386035> **Pro Tips for New Users**",
                    value="• Be clear and detailed in your ticket description\n"
                          "• Choose the right category for faster help\n"
                          "• Set appropriate priority level\n"
                          "• Stay in your ticket channel for updates\n"
                          "• Rate your experience when done! <:j_icons_Correct:1382701297987485706>",
                    inline=False
                )

            elif category == "response_priority":
                embed = discord.Embed(
                    title="<:icons_clock:1382701751206936697> Response Times & Priority Levels",
                    description="Understanding how we prioritize and respond to tickets.",
                    color=0xFFAA00,
                    timestamp=current_time
                )

                embed.add_field(
                    name="<a:lighting_icons:1383871485122449409> **Priority Levels Explained**",
                    value="**🟢 Low** - General questions, non-urgent issues\n"
                          "**🟡 Medium** - Standard support requests (default)\n"
                          "**🟠 High** - Important issues affecting functionality\n"
                          "**🔴 Critical** - Urgent problems, server outages, security",
                    inline=False
                )

                embed.add_field(
                    name="<:icons_clock:1382701751206936697> **Expected Response Times**",
                    value="**🟢 Low Priority:** 12-24 hours\n"
                          "**🟡 Medium Priority:** 4-12 hours\n"
                          "**🟠 High Priority:** 1-4 hours\n"
                          "**🔴 Critical Priority:** 15 minutes - 1 hour\n\n"
                          "*Times may vary based on support team availability*",
                    inline=False
                )

                embed.add_field(
                    name="<:Target:1382706193855942737> **How to Choose Priority**",
                    value="• **Critical**: Server down, security breach, data loss\n"
                          "• **High**: Features broken, unable to use service\n"
                          "• **Medium**: General issues, questions, minor bugs\n"
                          "• **Low**: Feature requests, casual questions",
                    inline=False
                )

            elif category == "ticket_management":
                embed = discord.Embed(
                    title="<:Target:1382706193855942737> Ticket Management Guide",
                    description="Learn how to manage your tickets effectively.",
                    color=0x9932CC,
                    timestamp=current_time
                )

                embed.add_field(
                    name="<:j_icons_Correct:1382701297987485706> **Managing Your Tickets**",
                    value="• **View ticket info** - Use `/ticket-info` command\n"
                          "• **Add users** - Use `/add-user @username`\n"
                          "• **Rename ticket** - Use `/rename New Name Here`\n"
                          "• **Close ticket** - Use `/close` command\n"
                          "• **Transfer ownership** - Use `/transfer-ticket @user`",
                    inline=False
                )

                embed.add_field(
                    name="<:icons_clock:1382701751206936697> **Ticket Limits & Rules**",
                    value="• Each user can have multiple open tickets (server limit)\n"
                          "• Tickets auto-close after extended inactivity\n"
                          "• Rate limiting prevents ticket spam\n"
                          "• Only ticket creator and staff can close tickets\n"
                          "• Transcripts are saved when tickets close",
                    inline=False
                )

                embed.add_field(
                    name="<:lightbulb:1382701619753386035> **Best Practices**",
                    value="• Keep conversations in your ticket channel\n"
                          "• Provide screenshots or files when helpful\n"
                          "• Update your ticket if situation changes\n"
                          "• Close tickets when issue is resolved\n"
                          "• Leave feedback to help improve service",
                    inline=False
                )

            elif category == "features_settings":
                embed = discord.Embed(
                    title="<:clipboard1:1383857546410070117> Features & Settings",
                    description="Discover all the powerful features available.",
                    color=0x5865F2,
                    timestamp=current_time
                )

                embed.add_field(
                    name="<:clipboard1:1383857546410070117> **Transcript System**",
                    value="• Full conversation logs saved automatically\n"
                          "• Sent to your DMs when ticket closes\n"
                          "• Includes all messages, files, and embeds\n"
                          "• Perfect for record keeping\n"
                          "• Formatted for easy reading",
                    inline=False
                )

                embed.add_field(
                    name="<:icons_star:1382705271591272471> **Rating System**",
                    value="• Rate your support experience (1-5 stars)\n"
                          "• Provide feedback to help us improve\n"
                          "• Helps train our support team\n"
                          "• Optional but greatly appreciated\n"
                          "• Anonymous feedback option available",
                    inline=False
                )

                embed.add_field(
                    name="<:Target:1382706193855942737> **Advanced Features**",
                    value="• **Categories** - Organized support types\n"
                          "• **Staff Assignment** - Claim and transfer tickets\n"
                          "• **User Management** - Add/remove ticket participants\n"
                          "• **Analytics** - Track support performance\n"
                          "• **Custom Branding** - Server-specific appearance",
                    inline=False
                )

            elif category == "troubleshooting":
                embed = discord.Embed(
                    title="<:icons_wrench:1382702984940617738> Troubleshooting Common Issues",
                    description="Solutions to frequently encountered problems.",
                    color=0xFF0000,
                    timestamp=current_time
                )

                embed.add_field(
                    name="<:icons_Wrong:1382701332955402341> **Common Problems & Solutions**",
                    value="• **Can't create ticket:** Check if you've reached the limit\n"
                          "• **No response:** Verify correct priority and wait time\n"
                          "• **Can't see transcript:** Check your DM privacy settings\n"
                          "• **Permission errors:** Contact server administrators\n"
                          "• **Bot not responding:** Try again in a few moments",
                    inline=False
                )

                embed.add_field(
                    name="<:icons_wrench:1382702984940617738> **Quick Fixes**",
                    value="• **Refresh Discord** - Close and reopen the app\n"
                          "• **Clear Cache** - Clear Discord's cache and restart\n"
                          "• **Check Permissions** - Verify bot has required permissions\n"
                          "• **Wait and Retry** - Some issues resolve automatically\n"
                          "• **Contact Support** - Use our support server for help\n"
                          "• **Check permissions** - Ensure bot has proper access\n"
                          "• **Wait for sync** - Commands may take time to update\n"
                          "• **Clear cache** - Restart Discord if needed\n"
                          "• **Update Discord** - Use the latest version",
                    inline=False
                )

                embed.add_field(
                    name="<:UA_Rocket_icons:1382701592851124254> **Still need help?**",
                    value="Can't find what you're looking for?\n"
                          "• Create a ticket for personalized assistance\n"
                          "• Our expert support team is here to help\n"
                          "• We're committed to resolving your issues\n"
                          "•  service guaranteed! <:j_icons_Correct:1382701297987485706>",
                    inline=False
                )

            embed.set_footer(text=f"Harly Xploitz • {category.replace('_', ' ').title()} FAQ")

            view = FAQCategoryView(self.bot)
            await interaction.response.edit_message(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error in FAQ category select: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"<:icons_Wrong:1382701332955402341> | An error occurred: {e}",
                    ephemeral=True
                )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

async def setup(bot):
    await bot.add_cog(SupportSystem(bot))