import discord
import logging
from datetime import datetime, timezone
from utils.helpers import sanitize_channel_name, utc_to_gmt

logger = logging.getLogger('discord')

import discord
import logging
from utils.database import check_user_ticket_limit, is_user_blacklisted
from utils.helpers import check_rate_limit, set_rate_limit

logger = logging.getLogger('discord')

class TicketModal(discord.ui.Modal):
    def __init__(self, bot, category, guild_id, emoji=None):
        super().__init__(title=f"🎫 Create {category} Ticket", timeout=300)
        self.bot = bot
        self.category = category
        self.guild_id = guild_id
        self.emoji = emoji

    subject = discord.ui.TextInput(
        label="Ticket Subject",
        placeholder="Brief description of your issue...",
        max_length=100,
        required=True
    )

    description = discord.ui.TextInput(
        label="Detailed Description",
        style=discord.TextStyle.paragraph,
        placeholder="Provide detailed information about your issue, error messages, and steps taken...",
        max_length=1000,
        required=True
    )

    priority = discord.ui.TextInput(
        label="Priority Level (Low/Medium/High/Critical)",
        placeholder="Medium",
        default="Medium",
        max_length=10,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)

            subject = self.subject.value.strip()
            description = self.description.value.strip()
            priority_input = self.priority.value.strip().title() if self.priority.value else "Medium"

            if priority_input not in ["Low", "Medium", "High", "Critical"]:
                priority_input = "Medium"

            from utils.database import check_user_ticket_limit
            from utils.helpers import check_rate_limit, set_rate_limit

            user_id = interaction.user.id
            if await check_rate_limit(self.bot, user_id):
                await interaction.followup.send(
                    "<:icons_Wrong:1382701332955402341> You're creating tickets too quickly. Please wait 60 seconds before creating another ticket.",
                    ephemeral=True
                )
                return

            ticket_limit_ok, current_tickets, max_tickets = await check_user_ticket_limit(self.bot, self.guild_id, user_id)
            if not ticket_limit_ok:
                await interaction.followup.send(
                    f"<:icons_Wrong:1382701332955402341> You have reached the maximum ticket limit ({current_tickets}/{max_tickets}). Please close existing tickets before creating new ones.",
                    ephemeral=True
                )
                return

            async with self.bot.db.cursor() as cur:
                await cur.execute(
                    "SELECT 1 FROM ticket_blacklist WHERE guild_id = ? AND user_id = ?",
                    (self.guild_id, user_id)
                )
                if await cur.fetchone():
                    await interaction.followup.send(
                        "<:icons_Wrong:1382701332955402341> You are blacklisted from creating tickets in this server.",
                        ephemeral=True
                    )
                    return

            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT maintenance_mode FROM tickets WHERE guild_id = ?", (self.guild_id,))
                result = await cur.fetchone()
                if result and result[0]:
                    await interaction.followup.send(
                        "<:icons_wrench:1382702984940617738> The ticket system is currently under maintenance. Please try again later.",
                        ephemeral=True
                    )
                    return

            from utils.tickets import create_ticket_channel
            try:
                success, message = await create_ticket_channel(
                    self.bot, interaction.guild, interaction.user, None,
                    self.category, subject, description, priority_input
                )

                if success:
                    await set_rate_limit(self.bot, user_id)
                    await interaction.followup.send(
                        f"<:j_icons_Correct:1382701297987485706> {message}",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"<:icons_Wrong:1382701332955402341> {message}",
                        ephemeral=True
                    )
            except Exception as ticket_error:
                logger.error(f"Error creating ticket: {ticket_error}")
                await interaction.followup.send(
                    f"<:icons_Wrong:1382701332955402341> Failed to create ticket: {str(ticket_error)}",
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error in ticket modal submission: {e}")
            try:
                await interaction.followup.send(
                    "<:icons_Wrong:1382701332955402341> An error occurred while creating your ticket. Please try again.",
                    ephemeral=True
                )
            except:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"Modal error: {error}")
        try:
            await interaction.response.send_message(
                "<:icons_Wrong:1382701332955402341> An error occurred. Please try again.",
                ephemeral=True
            )
        except:
            pass

class PanelCustomizationModal(discord.ui.Modal):
    def __init__(self, setup_view):
        super().__init__(title="<:paint_icons:1383849816022581332> Panel Customization")
        self.setup_view = setup_view

    embed_title = discord.ui.TextInput(
        label="Panel Title",
        placeholder="e.g., <:Ticket_icons:1382703084815257610> Support Center",
        default="<:Ticket_icons:1382703084815257610> Support Center",
        max_length=100,
        required=True
    )

    embed_description = discord.ui.TextInput(
        label="Panel Description",
        placeholder="e.g., Need assistance? Our expert team is here to help!",
        style=discord.TextStyle.paragraph,
        default="Need assistance? Select a category below to create a support ticket. Our expert team will help you shortly! <:UA_Rocket_icons:1382701592851124254>",
        max_length=500,
        required=True
    )

    embed_color = discord.ui.TextInput(
        label="Panel Color (Hex Code)",
        placeholder="e.g., #5865F2 or 0x5865F2",
        default="0x5865F2",
        max_length=10,
        required=False
    )

    embed_footer = discord.ui.TextInput(
        label="Panel Footer",
        placeholder="e.g., Powered by Harly Xploitz™",
        default="Powered by Harly Xploitz™ • Support System",
        max_length=100,
        required=False
    )

    embed_image_url = discord.ui.TextInput(
        label="Panel Image URL (Optional)",
        placeholder="e.g., https://example.com/image.png",
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)

            self.setup_view.setup_data['embed_title'] = self.embed_title.value
            self.setup_view.setup_data['embed_description'] = self.embed_description.value
            self.setup_view.setup_data['embed_footer'] = self.embed_footer.value
            self.setup_view.setup_data['embed_image_url'] = self.embed_image_url.value if self.embed_image_url.value else None

            color_value = self.embed_color.value.strip()
            try:
                if color_value.startswith('#'):
                    color_int = int(color_value[1:], 16)
                elif color_value.startswith('0x'):
                    color_int = int(color_value, 16)
                else:
                    color_int = int(color_value, 16)
                self.setup_view.setup_data['embed_color'] = color_int
            except (ValueError, AttributeError):
                self.setup_view.setup_data['embed_color'] = 0x5865F2

            current_time = utc_to_gmt(discord.utils.utcnow())
            embed = discord.Embed(
                title="<:j_icons_Correct:1382701297987485706> Panel Customization Saved",
                description="**Your panel customization has been applied!**\n\n"
                           "The changes will be visible when you finish the setup and deploy your panel.",
                color=0x00FF88,
                timestamp=current_time
            )

            embed.add_field(
                name="<:paint_icons:1383849816022581332> Customization Preview",
                value=f"**Title:** {self.embed_title.value}\n"
                      f"**Color:** #{hex(self.setup_view.setup_data['embed_color'])[2:].upper()}\n"
                      f"**Footer:** {self.embed_footer.value[:50]}{'...' if len(self.embed_footer.value) > 50 else ''}",
                inline=False
            )

            embed.set_footer(text=f"Saved at {current_time.strftime('%I:%M %p GMT')}")
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in panel customization modal: {e}")
            error_embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Customization Error",
                description=f"**Failed to save customization:** {str(e)}",
                color=0xFF6B6B
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)

class TicketSetupModal(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title="Ticket System Configuration")
        self.bot = bot

    support_channel = discord.ui.TextInput(
        label="Support Channel ID",
        placeholder="Enter the channel ID where tickets will be created",
        required=True
    )

    support_role = discord.ui.TextInput(
        label="Support Role ID", 
        placeholder="Enter the role ID for support staff",
        required=True
    )

    log_channel = discord.ui.TextInput(
        label="Log Channel ID (Optional)",
        placeholder="Enter the channel ID for ticket logs",
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)

            channel_id = int(str(self.support_channel.value))
            role_id = int(str(self.support_role.value))
            log_channel_id = int(str(self.log_channel.value)) if self.log_channel.value else None

            channel = interaction.guild.get_channel(channel_id)
            role = interaction.guild.get_role(role_id)
            log_channel = interaction.guild.get_channel(log_channel_id) if log_channel_id else None

            if not channel:
                await interaction.followup.send("<:icons_Wrong:1382701332955402341> Support channel not found!", ephemeral=True)
                return

            if not role:
                await interaction.followup.send("<:icons_Wrong:1382701332955402341> Support role not found!", ephemeral=True)
                return

            async with self.bot.db.cursor() as cur:
                await cur.execute("""
                    INSERT OR REPLACE INTO tickets 
                    (guild_id, channel_id, role_id, log_channel_id)
                    VALUES (?, ?, ?, ?)
                """, (interaction.guild.id, channel_id, role_id, log_channel_id))
                await self.bot.db.commit()

            embed = discord.Embed(
                title="<:j_icons_Correct:1382701297987485706> Setup Complete",
                description=f"**Ticket system configured successfully!**\n\n"
                           f"**Support Channel:** {channel.mention}\n"
                           f"**Support Role:** {role.mention}\n"
                           f"**Log Channel:** {log_channel.mention if log_channel else 'None'}",
                color=0x00D4FF
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        except ValueError:
            await interaction.followup.send("<:icons_Wrong:1382701332955402341> Invalid ID format! Please use numbers only.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in setup modal: {e}")
            await interaction.followup.send(f"<:icons_Wrong:1382701332955402341> Setup failed: {str(e)}", ephemeral=True)

class TicketLimitModal(discord.ui.Modal):
    def __init__(self, setup_view):
        super().__init__(title="Set Ticket Limit")
        self.setup_view = setup_view

    ticket_limit = discord.ui.TextInput(
        label="Maximum Tickets Per User",
        placeholder="Enter a number between 1-10 (default: 3)",
        default="3",
        min_length=1,
        max_length=2,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(self.ticket_limit.value)
            if limit < 1 or limit > 10:
                embed = discord.Embed(
                    title="<:icons_Wrong:1382701332955402341> Invalid Limit",
                    description="Ticket limit must be between 1 and 10.",
                    color=0xFF0000
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            self.setup_view.setup_data['ticket_limit'] = limit

            embed = discord.Embed(
                title="🔢 Ticket Limit Set",
                description=f"**Maximum tickets per user:** {limit}\n\nUsers can now create up to {limit} tickets at the same time.",
                color=0x00FF88
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except ValueError:
            embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Invalid Input",
                description="Please enter a valid number between 1 and 10.",
                color=0xFF0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

class SetupModal(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title="Ticket System Configuration")
        self.bot = bot