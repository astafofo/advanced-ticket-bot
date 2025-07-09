import discord
import logging
from datetime import datetime, timezone
from utils.helpers import check_rate_limit, set_rate_limit, utc_to_gmt
from utils.database import get_user_open_tickets, get_ticket_categories
from views.modals import TicketModal

logger = logging.getLogger('discord')

class TicketPanelView(discord.ui.View):
    def __init__(self, bot, categories, guild_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.categories = categories
        self.guild_id = guild_id

        if len(categories) <= 25:
            self.add_item(TicketCategorySelect(bot, categories, guild_id))

class TicketCategorySelect(discord.ui.Select):
    def __init__(self, bot, categories, guild_id):
        self.bot = bot
        self.guild_id = guild_id

        options = []
        for category_name, emoji in categories:
            try:
                display_emoji = "🎫"
                if emoji and emoji.strip():
                    if emoji.startswith('<:') and emoji.endswith('>') and ':' in emoji:
                        display_emoji = emoji
                    elif len(emoji) <= 4 and not emoji.startswith('<'):
                        display_emoji = emoji
                
                options.append(discord.SelectOption(
                    label=category_name,
                    value=category_name,
                    emoji=display_emoji,
                    description=f"Create a {category_name.lower()} ticket"
                ))
            except Exception as e:
                logger.error(f"Error creating option for category {category_name}: {e}")
                options.append(discord.SelectOption(
                    label=category_name,
                    value=category_name,
                    emoji="🎫",
                    description=f"Create a {category_name.lower()} ticket"
                ))

        super().__init__(
            placeholder="Select a category",
            options=options,
            custom_id="ticket_category_select"
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            logger.info(f"Category select callback triggered by {interaction.user.id} in guild {interaction.guild.id}")
            
            if not self.values:
                await interaction.response.send_message(
                    "<:icons_Wrong:1382701332955402341> No category selected. Please try again.",
                    ephemeral=True
                )
                return

            category = self.values[0]
            logger.info(f"Selected category: {category}")

            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT maintenance_mode FROM tickets WHERE guild_id = ?", (interaction.guild.id,))
                result = await cur.fetchone()
                maintenance_mode = bool(result[0]) if result and result[0] is not None else False

            if maintenance_mode:
                await interaction.response.send_message(
                    "<:icons_wrench:1382702984940617738> The ticket system is currently under maintenance. Please try again later.",
                    ephemeral=True
                )
                return

            if await check_rate_limit(self.bot, interaction.user.id):
                await interaction.response.send_message(
                    "<:icons_Wrong:1382701332955402341> You're creating tickets too quickly. Please wait 60 seconds before creating another ticket.",
                    ephemeral=True
                )
                return

            async with self.bot.db.cursor() as cur:
                await cur.execute(
                    "SELECT 1 FROM ticket_blacklist WHERE guild_id = ? AND user_id = ?",
                    (interaction.guild.id, interaction.user.id)
                )
                if await cur.fetchone():
                    await interaction.response.send_message(
                        "<:icons_Wrong:1382701332955402341> You are blacklisted from creating tickets in this server.",
                        ephemeral=True
                    )
                    return

            open_tickets = await get_user_open_tickets(self.bot, interaction.guild.id, interaction.user.id)

            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT ticket_limit FROM tickets WHERE guild_id = ?", (interaction.guild.id,))
                result = await cur.fetchone()
                ticket_limit = result[0] if result else 3

            if open_tickets >= ticket_limit:
                await interaction.response.send_message(
                    f"<:Ticket_icons:1382703084815257610> You already have {open_tickets} open tickets. Please close some before creating new ones.",
                    ephemeral=True
                )
                return

            modal = TicketModal(self.bot, category, interaction.guild.id)
            await interaction.response.send_modal(modal)
            logger.info(f"Modal sent successfully for category {category}")

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"DETAILED ERROR in category select callback:")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {str(e)}")
            logger.error(f"Full traceback: {error_details}")
            logger.error(f"Interaction user: {interaction.user.id}")
            logger.error(f"Guild: {interaction.guild.id}")
            logger.error(f"Selected values: {getattr(self, 'values', 'None')}")
            
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"<:icons_Wrong:1382701332955402341> Error: {type(e).__name__}: {str(e)[:150]}",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"<:icons_Wrong:1382701332955402341> Error: {type(e).__name__}: {str(e)[:150]}",
                        ephemeral=True
                    )
            except Exception as follow_error:
                logger.error(f"Failed to send error message: {follow_error}")
                logger.error(f"Follow error traceback: {traceback.format_exc()}")

class TicketButtonPanelView(discord.ui.View):
    def __init__(self, bot, categories, guild_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.categories = categories
        self.guild_id = guild_id

        for idx, (category_name, emoji) in enumerate(categories[:25]):
            self.add_item(TicketCategoryButton(bot, category_name, emoji, idx, guild_id))

class TicketCategoryButton(discord.ui.Button):
    def __init__(self, bot, category, emoji, row, guild_id):
        display_emoji = "🎫"
        if emoji and emoji.strip():
            if emoji.startswith('<:') and emoji.endswith('>') and ':' in emoji:
                display_emoji = emoji
            elif len(emoji) <= 4 and not emoji.startswith('<'):
                display_emoji = emoji
        
        super().__init__(
            label=category,
            style=discord.ButtonStyle.primary,
            emoji=display_emoji,
            custom_id=f"ticket_button_{category}",
            row=row // 5  # 5 buttons per row
        )
        self.bot = bot
        self.category = category
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        try:
            logger.info(f"Category button callback triggered by {interaction.user.id} for category {self.category}")
            
            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT maintenance_mode FROM tickets WHERE guild_id = ?", (interaction.guild.id,))
                result = await cur.fetchone()
                maintenance_mode = bool(result[0]) if result and result[0] is not None else False

            if maintenance_mode:
                await interaction.response.send_message(
                    "<:icons_wrench:1382702984940617738> The ticket system is currently under maintenance. Please try again later.",
                    ephemeral=True
                )
                return

            if await check_rate_limit(self.bot, interaction.user.id):
                await interaction.response.send_message(
                    "<:icons_Wrong:1382701332955402341> You're creating tickets too quickly. Please wait 60 seconds before creating another ticket.",
                    ephemeral=True
                )
                return

            async with self.bot.db.cursor() as cur:
                await cur.execute(
                    "SELECT 1 FROM ticket_blacklist WHERE guild_id = ? AND user_id = ?",
                    (interaction.guild.id, interaction.user.id)
                )
                if await cur.fetchone():
                    await interaction.response.send_message(
                        "<:icons_Wrong:1382701332955402341> You are blacklisted from creating tickets in this server.",
                        ephemeral=True
                    )
                    return

            open_tickets = await get_user_open_tickets(self.bot, interaction.guild.id, interaction.user.id)

            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT ticket_limit FROM tickets WHERE guild_id = ?", (interaction.guild.id,))
                result = await cur.fetchone()
                ticket_limit = result[0] if result else 3

            if open_tickets >= ticket_limit:
                await interaction.response.send_message(
                    f"<:Ticket_icons:1382703084815257610> You already have {open_tickets} open tickets. Please close some before creating new ones.",
                    ephemeral=True
                )
                return

            modal = TicketModal(self.bot, self.category, interaction.guild.id)
            await interaction.response.send_modal(modal)
            logger.info(f"Modal sent successfully for category {self.category}")

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"DETAILED ERROR in category button callback:")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {str(e)}")
            logger.error(f"Full traceback: {error_details}")
            logger.error(f"Interaction user: {interaction.user.id}")
            logger.error(f"Guild: {interaction.guild.id}")
            logger.error(f"Category: {self.category}")
            
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"<:icons_Wrong:1382701332955402341> Error: {type(e).__name__}: {str(e)[:150]}",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"<:icons_Wrong:1382701332955402341> Error: {type(e).__name__}: {str(e)[:150]}",
                        ephemeral=True
                    )
            except Exception as follow_error:
                logger.error(f"Failed to send error message: {follow_error}")
                logger.error(f"Follow error traceback: {traceback.format_exc()}")

class TicketButtonView(discord.ui.View):
    def __init__(self, bot, categories, guild_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.categories = categories
        self.guild_id = guild_id

        for idx, (category_name, emoji) in enumerate(categories):
            if idx >= 25:  # Discord limit
                break
            category_emoji = emoji if emoji else None
            self.add_item(TicketCategoryButton(bot, category_name, category_emoji, idx, guild_id))