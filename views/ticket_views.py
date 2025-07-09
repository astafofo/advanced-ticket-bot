import discord
import logging
import asyncio
import re
from datetime import datetime, timezone
from utils.helpers import (
    check_rate_limit, set_rate_limit, validate_ticket_setup,
    generate_transcript, send_transcript_dm, sanitize_channel_name,
    get_priority_emoji, send_error_embed, send_success_embed
)
from utils.database import get_user_open_tickets
from views.modals import TicketModal
from views.panel_views import TicketPanelView, TicketButtonView, TicketCategorySelect, TicketCategoryButton, TicketButtonPanelView

logger = logging.getLogger('discord')

class TicketControlView(discord.ui.View):
    def __init__(self, bot, ticket_data, priority_used=False):
        super().__init__(timeout=None)
        self.bot = bot
        self.ticket_data = ticket_data
        self.priority_used = priority_used
        
        if not self.priority_used:
            self.add_priority_selector()

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="<:welcome:1382706419765350480>", custom_id="close_ticket_btn", row=0)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:

            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT role_id FROM tickets WHERE guild_id = ?", (interaction.guild.id,))
                result = await cur.fetchone()

                if not result:
                    embed = discord.Embed(
                        title="<:icons_Wrong:1382701332955402341> System Configuration Error",
                        description="**The ticket system is not properly configured.**\n\n"
                                   "<:icons_wrench:1382702984940617738> **Issue:** Missing system configuration\n"
                                   "<:lightbulb:1382701619753386035> **Solution:** Contact an administrator to resolve this issue\n"
                                   "📞 **Support:** Use `/setup-tickets` to reconfigure",
                        color=0xFF6B6B
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

                support_role_id = result[0]
                support_role = interaction.guild.get_role(support_role_id)


                is_creator = self.ticket_data.get('creator_id') == interaction.user.id
                is_support = support_role in interaction.user.roles if support_role else False
                is_admin = interaction.user.guild_permissions.administrator

                if not (is_creator or is_support or is_admin):
                    embed = discord.Embed(
                        title="<:icons_locked:1382701901685985361> Access Restricted",
                        description="**You don't have permission to close this ticket.**\n\n"
                                   "This ticket can only be closed by authorized users for security and organization.",
                        color=0xFF6B6B
                    )

                    embed.add_field(
                        name="<:Target:1382706193855942737> Authorized Users",
                        value=f"**<:icons_Person:1382703571056853082> Ticket Creator:** Original requester\n"
                              f"**<:shield:1382703287891136564> Support Staff:** {support_role.mention if support_role else 'Support Role'}\n"
                              f"**<:LM_Icons_Crown:1384043659330191390> Administrators:** Server administrators",
                        inline=False
                    )

                    embed.add_field(
                        name="<:lightbulb:1382701619753386035> Need Help?",
                        value="• **Resolve your issue:** Work with support to solve your problem\n"
                              "• **Request closure:** Ask support staff to close when resolved\n"
                              "• **Contact admin:** Get help if you have permission issues",
                        inline=False
                    )

                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return


            confirmation_embed = discord.Embed(
                title="<:icons_locked:1382701901685985361> Ticket Closure Confirmation",
                description=f"**Are you sure you want to close this support ticket?**\n\n"
                           f"<:warning:1382701413284446228> **Important:** This action is permanent and cannot be undone.\n\n"
                           f"**What happens when you close:**\n"
                           f"• <:clipboard1:1383857546410070117> Complete conversation transcript will be generated\n"
                           f"• <:icons_email:1384043381570670682> Transcript sent to ticket creator's DMs\n"
                           f"• <:icons_folder:1382703979754160169> Ticket logged in support system\n"
                           f"• <:type_icons:1384042158801027136> Channel will be permanently deleted\n"
                           f"• <:icons_star:1382705271591272471> Rating request sent to customer",
                color=0xFF6B6B,
                timestamp=discord.utils.utcnow()
            )

            confirmation_embed.add_field(
                name="<:Ticket_icons:1382703084815257610> Ticket Information",
                value=f"**Channel:** {interaction.channel.mention}\n"
                      f"**Closing User:** {interaction.user.mention}\n"
                      f"**Action Type:** {'Creator Closure' if is_creator else 'Staff Closure' if is_support else 'Admin Closure'}",
                inline=False
            )

            confirmation_embed.set_footer(text="Support System • Ticket Closure • Confirm Action")

            view = TicketCloseConfirmationView(self.bot, self.ticket_data)
            await interaction.response.send_message(embed=confirmation_embed, view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in close button: {e}")
            error_embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Error",
                description=f"**An error occurred:** {str(e)}",
                color=0xFF6B6B
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.success, emoji="<:bye:1382701701399707709>", custom_id="claim_ticket_btn", row=0)
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:

            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT role_id FROM tickets WHERE guild_id = ?", (interaction.guild.id,))
                result = await cur.fetchone()

                if not result:
                    embed = discord.Embed(
                        title="<:icons_Wrong:1382701332955402341> System Error",
                        description="**Ticket system is not properly configured.**\n\nPlease contact an administrator to resolve this issue.",
                        color=0xFF6B6B
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

                support_role_id = result[0]
                support_role = interaction.guild.get_role(support_role_id)


                from utils.database import user_has_support_role
                has_support_access = await user_has_support_role(self.bot, interaction.user)
                
                if not has_support_access:
                    embed = discord.Embed(
                        title="<:shield:1382703287891136564> Access Restricted",
                        description="**Only support staff members can claim tickets.**\n\n"
                                   f"<:Target:1382706193855942737> **Required Role:** {support_role.mention if support_role else 'Support Role'}\n"
                                   f"<:clipboard1:1383857546410070117> **Your Roles:** {', '.join([role.mention for role in interaction.user.roles if role != interaction.guild.default_role][:3])}\n\n"
                                   f"<:lightbulb:1382701619753386035> **Need access?** Contact an administrator to get the support role.",
                        color=0xFF6B6B
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return


                await cur.execute("SELECT claimed_by FROM ticket_instances WHERE channel_id = ?", (interaction.channel.id,))
                claim_result = await cur.fetchone()

                if claim_result and claim_result[0]:

                    if claim_result[0] == interaction.user.id:
                        embed = discord.Embed(
                            title="<:j_icons_Correct:1382701297987485706> Already Your Ticket",
                            description=f"**You have already claimed this ticket.**\n\n"
                                       f"<:Target:1382706193855942737> **Status:** This ticket is assigned to you\n"
                                       f"<:clipboard1:1383857546410070117> **Action:** No further action needed\n"
                                       f"<:type_icons:1384042158801027136> **Continue:** Assist the customer as normal",
                            color=0x00FF88
                        )
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return

                    claimer = interaction.guild.get_member(claim_result[0])
                    embed = discord.Embed(
                        title="<:icons_locked:1382701901685985361> Already Claimed",
                        description=f"**This ticket has already been claimed and is being handled.**\n\n"
                                   f"<:Target:1382706193855942737> **Assigned Agent:** {claimer.mention if claimer else 'Unknown Agent'}\n"
                                   f"<:label:1384044597386285121> **Agent Name:** {claimer.display_name if claimer else 'Unknown'}\n"
                                   f"<:clipboard1:1383857546410070117> **Status:** 🟢 Active Support\n\n"
                                   f"<:lightbulb:1382701619753386035> **Need to reassign?** Use `/transfer-ticket @new_agent` command",
                        color=0xFF8C00
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return


            ticket_number = self.ticket_data.get('ticket_number', 0)
            category = self.ticket_data.get('category', 'Unknown')
            ticket_creator_id = self.ticket_data.get('creator_id')
            ticket_creator = interaction.guild.get_member(ticket_creator_id)
            
            if ticket_creator:
                creator_mention = ticket_creator.mention
            elif ticket_creator_id:
                creator_mention = f"<@{ticket_creator_id}>"
            else:
                creator_mention = "**Ticket Creator**"

            claim_message = f"{creator_mention} your ticket has been claimed by {interaction.user.mention}"

            await interaction.response.send_message(claim_message, ephemeral=False)

            async with self.bot.db.cursor() as cur:
                await cur.execute(
                    "UPDATE ticket_instances SET claimed_by = ? WHERE channel_id = ?",
                    (interaction.user.id, interaction.channel.id)
                )
                await self.bot.db.commit()


            async def get_ticket_log_channel(bot, guild_id):
                async with bot.db.cursor() as cur:
                    await cur.execute("SELECT log_channel_id FROM tickets WHERE guild_id = ?", (guild_id,))
                    result = await cur.fetchone()
                    return bot.get_channel(result[0]) if result and result[0] else None

            ticket_creator_id = self.ticket_data['creator_id']
            ticket_creator = interaction.guild.get_member(ticket_creator_id)
            if not ticket_creator:
                ticket_creator = self.bot.get_user(ticket_creator_id)

            current_time = discord.utils.utcnow()


            log_channel = await get_ticket_log_channel(self.bot, interaction.guild.id)
            if log_channel:

                from utils.tickets import get_ticket_info
                ticket_info = await get_ticket_info(self.bot, interaction.channel.id)


                created_time = discord.utils.parse_time(ticket_info['created_at']) if ticket_info and ticket_info.get('created_at') else discord.utils.utcnow()
                time_to_claim = discord.utils.utcnow() - created_time
                claim_time_str = f"{time_to_claim.seconds//3600}h {(time_to_claim.seconds//60)%60}m"

                creator_name = "Unknown User"
                creator_id_display = "Unknown"
                if ticket_creator:
                    creator_name = getattr(ticket_creator, 'display_name', None) or getattr(ticket_creator, 'name', 'Unknown User')
                    creator_id_display = str(ticket_creator.id)

                ticket_number_display = f"#{ticket_info['ticket_number']:04d}" if ticket_info else "#0000"
                log_embed = discord.Embed(
                    title="Logs - Ticket Claimed!",
                    description=f"> Ticket `{ticket_number_display}` has been claimed {discord.utils.format_dt(current_time, 'R')}! ({discord.utils.format_dt(current_time, 'F')})\n\n"
                               f"**Channel**\n```{interaction.channel.mention} ({interaction.channel.id})```"
                               f"**Claimed By**\n```{interaction.user.display_name} ({interaction.user.id})```"
                               f"**Ticket Creator**\n```{creator_name} ({creator_id_display})```"
                               f"**Category**\n```{ticket_info.get('category', 'Unknown') if ticket_info else 'Unknown'}```"
                               f"**Priority**\n```{ticket_info.get('priority', 'Medium') if ticket_info else 'Medium'}```",
                    color=0x00D4FF,
                    timestamp=current_time
                )

                log_embed.set_footer(text="Support System • Ticket Claimed")
                log_embed.set_thumbnail(url=interaction.user.display_avatar.url)

                await log_channel.send(embed=log_embed)

        except Exception as e:
            logger.error(f"Error claiming ticket: {e}")
            embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Claim Error",
                description=f"**We encountered an issue claiming this ticket.**\n\n**Error:** {str(e)}\n\nPlease try again or contact an administrator.",
                color=0xFF6B6B
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)



    def add_priority_selector(self):
        """Add priority selector to the view"""
        priority_select = discord.ui.Select(
            placeholder="⚡ Change Priority Level...",
            options=[
                discord.SelectOption(label="🟢 Low Priority", value="Low", emoji="🟢", description="Non-urgent issues"),
                discord.SelectOption(label="🟡 Medium Priority", value="Medium", emoji="🟡", description="Standard priority"),
                discord.SelectOption(label="🟠 High Priority", value="High", emoji="🟠", description="Important issues"),
                discord.SelectOption(label="🔴 Critical Priority", value="Critical", emoji="🔴", description="Urgent/emergency issues")
            ],
            custom_id="priority_select_menu",
            row=1
        )
        priority_select.callback = self.priority_select_callback
        self.add_item(priority_select)

    async def priority_select_callback(self, interaction: discord.Interaction):
        try:
            select = None
            for item in self.children:
                if isinstance(item, discord.ui.Select) and item.custom_id == "priority_select_menu":
                    select = item
                    break
            
            if not select:
                return
                
            priority = select.values[0]

            from utils.database import user_has_support_role

            invoker = interaction.user
            has_support_role = await user_has_support_role(self.bot, invoker)
            is_admin = invoker.guild_permissions.administrator

            if not (has_support_role or is_admin):
                embed = discord.Embed(
                    title="<:icons_locked:1382701901685985361> Permission Denied",
                    description="**Only support staff can change priority.**\n\nYou need to have at least one support role to modify ticket priorities.",
                    color=0xFF6B6B
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            async with self.bot.db.cursor() as cur:
                await cur.execute(
                    "UPDATE ticket_instances SET priority = ? WHERE channel_id = ?",
                    (priority, interaction.channel.id)
                )
                await self.bot.db.commit()

            priority_emojis = {
                "Low": "🟢",
                "Medium": "🟡", 
                "High": "🟠",
                "Critical": "🔴"
            }
            
            priority_emoji = priority_emojis.get(priority, "🟡")

            current_name = interaction.channel.name
            clean_name = re.sub(r'^[🟢🟡🟠🔴]\s*', '', current_name)
            new_name = f"{priority_emoji} {clean_name}"
            
            try:
                await interaction.channel.edit(
                    name=new_name,
                    reason=f"Priority changed to {priority} by {interaction.user.display_name}"
                )
            except discord.HTTPException as e:
                logger.warning(f"Could not rename channel: {e}")

            self.ticket_data['priority'] = priority

            try:
                async for message in interaction.channel.history(limit=50):
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
                        
                        fresh_view = TicketControlView(self.bot, self.ticket_data, priority_used=True)
                        
                        await message.edit(embed=embed, view=fresh_view)
                        logger.info(f"Successfully updated control panel embed with new priority: {priority}")
                        break
                        
            except Exception as edit_error:
                logger.warning(f"Could not update control menu embed: {edit_error}")
                try:
                    notification = await interaction.channel.send(
                        f"⚠️ **Priority updated to {priority_emoji} {priority}** (control panel refresh required)",
                        delete_after=15
                    )
                except Exception as send_error:
                    logger.error(f"Could not send fallback notification: {send_error}")

            embed = discord.Embed(
                title=f"<:j_icons_Correct:1382701297987485706> Priority Updated",
                description=f"**{interaction.user.display_name}** changed this ticket priority to **{priority_emoji} {priority}**.\n\nChannel name and control panel updated with new priority.",
                color=0x00D4FF,
                timestamp=datetime.now(timezone.utc)
            )

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error setting priority: {e}")
            error_embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Error",
                description=f"Failed to set priority: {str(e)}",
                color=0xFF6B6B
            )
            
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(embed=error_embed, ephemeral=True)
                else:
                    await interaction.followup.send(embed=error_embed, ephemeral=True)
            except:
                pass

class PrioritySelectView(discord.ui.View):
    def __init__(self, bot, ticket_data):
        super().__init__(timeout=300)
        self.bot = bot
        self.ticket_data = ticket_data

    @discord.ui.select(
        placeholder="Select priority level...",
        options=[
            discord.SelectOption(label="Low", value="Low", emoji="🟢"),
            discord.SelectOption(label="Medium", value="Medium", emoji="🟡"),
            discord.SelectOption(label="High", value="High", emoji="🟠"),
            discord.SelectOption(label="Critical", value="Critical", emoji="🔴")
        ]
    )
    async def priority_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        try:
            priority = select.values[0]


            async with self.bot.db.cursor() as cur:
                await cur.execute(
                    "UPDATE ticket_instances SET priority = ? WHERE channel_id = ?",
                    (priority, self.ticket_data['channel_id'])
                )
                await self.bot.db.commit()

            priority_emoji = get_priority_emoji(priority)

            await interaction.response.send_message(
                f"{priority_emoji} **Priority Updated**\nThis ticket has been set to **{priority}** priority.",
                ephemeral=True
            )

            embed = discord.Embed(
                title=f"{priority_emoji} Priority Updated",
                description=f"**{interaction.user.display_name}** set this ticket to **{priority}** priority.",
                color=0x00D4FF,
                timestamp=datetime.now(timezone.utc)
            )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error setting priority: {e}")
            await send_error_embed(interaction, "Error", f"Failed to set priority: {str(e)}")

class SetupWizardView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=1800)  # 30 minutes timeout
        self.bot = bot
        self.guild_id = guild_id
        self.setup_data = {
            'channel_id': None,
            'role_id': None,
            'category_id': None,
            'log_channel_id': None,
            'ping_role_id': None,
            'embed_title': ' Support Center',
            'embed_description': 'Need assistance? Select a category below to create a support ticket. Our expert team will help you shortly!',
            'embed_color': 0x2F3136,
            'embed_footer': 'Powered by Harly Xploitz™ • Support System',
            'embed_image_url': None,
            'panel_type': 'dropdown',
            'ticket_limit': 3
        }
        self.waiting_for_custom = None  # Track what custom input we're waiting for

        self.add_item(PanelChannelSelect())
        self.add_item(LogChannelSelect())
        self.add_item(SupportRoleSelect())

        self.add_item(CustomRoleButton())
        self.add_item(CustomPanelChannelButton())

        self.add_item(CustomLogChannelButton())
        self.add_item(PanelCustomizationButton())

        self.add_item(ConfirmSetupButton())

    async def start_setup(self, interaction):
        self.bot.active_setups[self.guild_id] = self

        current_time = discord.utils.utcnow()
        embed = discord.Embed(
            title="<:icons_wrench:1382702984940617738> Ticket Setup Wizard",
            description="**Configure your support system with our advanced setup wizard**\n\n"
                       "**<:clipboard1:1383857546410070117> Required Configuration:**\n"
                       "• Select ticket panel channel from dropdown\n"
                       "• Choose logs channel for transcripts\n" 
                       "• Assign support role for staff\n\n"
                       "**<:gear_icons:1384042417975464046> Advanced Options:**\n"
                       "• Use custom buttons for unlimited choices\n"
                       "• Customize panel appearance and branding\n"
                       "•  embed styling options\n\n"
                       f"<:icons_clock:1382701751206936697> **Setup expires in 30 minutes**",
            color=0x5865F2,
            timestamp=current_time
        )
        embed.add_field(
            name="<:lightbulb:1382701619753386035> **Pro Setup Tips**",
            value="• **Required:** Panel channel, logs channel, support role\n"
                  "• **Custom Options:** Use buttons for channels/roles not in dropdown\n"
                  "• **Branding:** Customize colors, titles, and descriptions\n"
                  "• **Preview:** See your setup before confirming",
            inline=False
        )
        embed.set_footer(text="Harly Xploitz™ • Setup Wizard • Step 1 of 1")
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)

        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    async def handle_custom_message(self, message):
        """Handle custom input from user messages"""
        if message.author.id != message.guild.get_member(message.author.id).id:
            return

        if self.waiting_for_custom == "role":
            if message.role_mentions:
                role = message.role_mentions[0]
                self.setup_data['role_id'] = role.id
                await message.reply(f"<:j_icons_Correct:1382701297987485706> Custom support role set to {role.mention}")
            else:
                await message.reply("<:icons_Wrong:1382701332955402341> Please mention a valid role!")
        elif self.waiting_for_custom == "panel_channel":
            if message.channel_mentions:
                channel = message.channel_mentions[0]
                self.setup_data['channel_id'] = channel.id
                await message.reply(f"<:j_icons_Correct:1382701297987485706> Custom panel channel set to {channel.mention}")
            else:
                await message.reply("<:icons_Wrong:1382701332955402341> Please mention a valid channel!")
        elif self.waiting_for_custom == "log_channel":
            if message.channel_mentions:
                channel = message.channel_mentions[0]
                self.setup_data['log_channel_id'] = channel.id
                await message.reply(f"<:j_icons_Correct:1382701297987485706> Custom log channel set to {channel.mention}")
            else:
                await message.reply("<:icons_Wrong:1382701332955402341> Please mention a valid channel!")

        self.waiting_for_custom = None

    async def finish_setup(self):
        try:
            async with self.bot.db.cursor() as cur:
                await cur.execute("""
                    INSERT OR REPLACE INTO tickets 
                    (guild_id, channel_id, role_id, category_id, log_channel_id, ping_role_id,
                     embed_title, embed_description, embed_color, embed_footer, embed_image_url, panel_type, ticket_limit)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.guild_id,
                    self.setup_data['channel_id'],
                    self.setup_data['role_id'],
                    self.setup_data['category_id'],
                    self.setup_data['log_channel_id'],
                    self.setup_data['ping_role_id'],
                    self.setup_data['embed_title'],
                    self.setup_data['embed_description'],
                    self.setup_data['embed_color'],
                    self.setup_data['embed_footer'],
                    self.setup_data['embed_image_url'],
                    self.setup_data['panel_type'],
                    self.setup_data['ticket_limit']
                ))
                await self.bot.db.commit()

            if self.guild_id in self.bot.active_setups:
                del self.bot.active_setups[self.guild_id]

            return True, "<:j_icons_Correct:1382701297987485706> Setup completed successfully!"

        except Exception as e:
            logger.error(f"Error finishing setup: {e}")
            return False, f"<:icons_Wrong:1382701332955402341> Setup failed: {str(e)}"

class PanelChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="<:Ticket_icons:1382703084815257610> Select Ticket Panel Channel...",
            channel_types=[discord.ChannelType.text],
            custom_id="panel_channel_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        view: SetupWizardView = self.view
        view.setup_data['channel_id'] = self.values[0].id

        embed = discord.Embed(
            title="<:j_icons_Correct:1382701297987485706> Panel Channel Selected",
            description=f"**Ticket Panel Channel:** {self.values[0].mention}\n\nUsers will create tickets from this channel.",
            color=0x00FF88
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class LogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="<:clipboard1:1383857546410070117> Select Logs Channel...",
            channel_types=[discord.ChannelType.text],
            custom_id="log_channel_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        view: SetupWizardView = self.view
        view.setup_data['log_channel_id'] = self.values[0].id

        embed = discord.Embed(
            title="<:j_icons_Correct:1382701297987485706> Log Channel Selected", 
            description=f"**Log Channel:** {self.values[0].mention}\n\nTicket transcripts and logs will be sent here.",
            color=0x00FF88
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class SupportRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="👥 Select Support Role...",
            custom_id="support_role_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        view: SetupWizardView = self.view
        view.setup_data['role_id'] = self.values[0].id

        embed = discord.Embed(
            title="<:j_icons_Correct:1382701297987485706> Support Role Selected",
            description=f"**Support Role:** {self.values[0].mention}\n\nMembers with this role can manage tickets.",
            color=0x00FF88
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class CustomRoleButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Custom Role",
            style=discord.ButtonStyle.secondary,
            emoji="<:shield:1382703287891136564>",
            custom_id="custom_role_btn",
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        view: SetupWizardView = self.view
        view.waiting_for_custom = "role"

        embed = discord.Embed(
            title="<:shield:1382703287891136564> Custom Support Role",
            description="**Please mention the role in chat**\n\nExample: `@Support Team`\n\nI'll automatically detect and set it as your support role.",
            color=0xFF8C00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class CustomPanelChannelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Custom Panel Channel",
            style=discord.ButtonStyle.secondary,
            emoji="<:megaphone:1382704888294936649>",
            custom_id="custom_panel_channel_btn",
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        view: SetupWizardView = self.view
        view.waiting_for_custom = "panel_channel"

        embed = discord.Embed(
            title="<:megaphone:1382704888294936649> Custom Panel Channel",
            description="**Please mention the channel in chat**\n\nExample: `#support`\n\nI'll set it as your ticket panel channel.",
            color=0xFF8C00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class CustomLogChannelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Custom Log Channel", 
            style=discord.ButtonStyle.secondary,
            emoji="<:stats_1:1382703019334045830>",
            custom_id="custom_log_channel_btn",
            row=2
        )

    async def callback(self, interaction: discord.Interaction):
        view: SetupWizardView = self.view
        view.waiting_for_custom = "log_channel"

        embed = discord.Embed(
            title="<:stats_1:1382703019334045830> Custom Log Channel",
            description="**Please mention the channel in chat**\n\nExample: `#ticket-logs`\n\nI'll set it as your transcript log channel.",
            color=0xFF8C00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class PanelCustomizationButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Panel Customization",
            style=discord.ButtonStyle.primary,
            emoji="<:paint_icons:1383849816022581332>",
            custom_id="panel_customization_btn",
            row=2
        )

    async def callback(self, interaction: discord.Interaction):
        modal = NewPanelCustomizationModal(self.view)
        await interaction.response.send_modal(modal)

class ConfirmSetupButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Confirm Setup",
            style=discord.ButtonStyle.success,
            emoji="<:j_icons_Correct:1382701297987485706>",
            custom_id="confirm_setup_btn",
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        view: SetupWizardView = self.view

        if not view.setup_data['channel_id']:
            embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Missing Panel Channel",
                description="Please select a ticket panel channel first!",
                color=0xFF0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not view.setup_data['role_id']:
            embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Missing Support Role",
                description="Please select a support role first!",
                color=0xFF0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        guild = interaction.guild
        panel_channel = guild.get_channel(view.setup_data['channel_id'])
        support_role = guild.get_role(view.setup_data['role_id'])
        log_channel = guild.get_channel(view.setup_data['log_channel_id']) if view.setup_data['log_channel_id'] else None

        embed = discord.Embed(
            title="<:j_icons_Correct:1382701297987485706> Setup Configuration Preview",
            description="**Review your configuration before confirming**\n\nEverything looks good? Click **Finish Setup** to complete!",
            color=0x00D4FF,
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(
            name="<:Ticket_icons:1382703084815257610> **Panel Configuration**",
            value=f"**Channel:** {panel_channel.mention}\n**Style:** {view.setup_data['panel_type'].title()}",
            inline=True
        )

        embed.add_field(
            name="<:people_icons:1384040549937451068> **Support Configuration**", 
            value=f"**Support Role:** {support_role.mention}\n**Ticket Limit:** {view.setup_data['ticket_limit']}",
            inline=True
        )

        embed.add_field(
            name="<:stats_1:1382703019334045830> **Logging Configuration**",
            value=f"**Log Channel:** {log_channel.mention if log_channel else 'None'}\n**Transcripts:** {'Enabled' if log_channel else 'Disabled'}",
            inline=True
        )

        embed.add_field(
            name="<:paint_icons:1383849816022581332> **Panel Appearance**",
            value=f"**Title:** {view.setup_data['embed_title']}\n**Color:** #{hex(view.setup_data['embed_color'])[2:].upper()}",
            inline=False
        )

        embed.set_footer(text="Harly Xploitz™ • Configuration Preview")

        confirm_view = FinalConfirmView(view)
        await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)

class FinalConfirmView(discord.ui.View):
    def __init__(self, setup_view):
        super().__init__(timeout=300)
        self.setup_view = setup_view

    @discord.ui.button(label="Finish Setup", style=discord.ButtonStyle.success, emoji="<:UA_Rocket_icons:1382701592851124254>")
    async def finish_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        success, message = await self.setup_view.finish_setup()

        if success:
            embed = discord.Embed(
                title="<:giveaway_icons:1383874296727732317> Setup Complete!",
                description="**Your ticket system is ready!**\n\n"
                           "**Next Steps:**\n"
                           "1️⃣ Add categories: `/add-category <name>`\n"
                           "2️⃣ Send panel: `/send-panel dropdown`\n"
                           "3️⃣ Test the system: Create a ticket!\n\n"
                           "**<:glowingstar:1384041798669828098> Pro Tips:**\n"
                           "• Add multiple categories for organization\n"
                           "• Train your support team on ticket commands\n"
                           "• Monitor the log channel for ticket activities",
                color=0x00FF88,
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="Harly Xploitz™ • Support System Active")
        else:
            embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Setup Failed",
                description=f"**Error:** {message}\n\nPlease try the setup again or contact support.",
                color=0xFF0000
            )

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="<:icons_Wrong:1382701332955402341>")
    async def cancel_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="<:icons_Wrong:1382701332955402341> Setup Cancelled",
            description="Setup has been cancelled. No changes were made.\n\nYou can restart setup anytime with `/setup-tickets`.",
            color=0xFF6B6B
        )

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

class TicketSetupView(discord.ui.View):
    def __init__(self, bot, ctx):
        super().__init__(timeout=1800)  # 30 minutes timeout
        self.bot = bot
        self.ctx = ctx
        self.setup_data = {
            'channel_id': None,
            'role_id': None,
            'log_channel_id': None,
            'embed_title': 'Support Center',
            'embed_description': 'Need assistance? Select a category below to create a support ticket. Our expert team will help you shortly!',
            'embed_color': 0x2F3136,
            'embed_image_url': None,
            'embed_footer': 'Powered by Harly Xploitz™ • Support System',
            'ticket_limit': 3
        }
        self.waiting_for_custom = None

        self.add_item(SetupSupportRoleSelect(ctx.guild))

        self.add_item(SetupPanelChannelSelect(ctx.guild))

        self.add_item(SetupLogChannelSelect(ctx.guild))

        self.add_item(SetupPanelCustomizationButton())
        self.add_item(SetupConfirmButton())

    async def handle_custom_message(self, message):
        """Handle custom input from user messages"""
        if message.author.id != self.ctx.author.id:
            return

        if self.waiting_for_custom == "role":
            if message.role_mentions:
                role = message.role_mentions[0]
                self.setup_data['role_id'] = role.id
                await message.reply(f"<:j_icons_Correct:1382701297987485706> **Custom support role set to {role.mention}**")
            else:
                await message.reply("<:icons_Wrong:1382701332955402341> Please mention a valid role!")
        elif self.waiting_for_custom == "panel_channel":
            if message.channel_mentions:
                channel = message.channel_mentions[0]
                self.setup_data['channel_id'] = channel.id
                await message.reply(f"<:j_icons_Correct:1382701297987485706> **Custom panel channel set to {channel.mention}**")
            else:
                await message.reply("<:icons_Wrong:1382701332955402341> Please mention a valid channel!")
        elif self.waiting_for_custom == "log_channel":
            if message.channel_mentions:
                channel = message.channel_mentions[0]
                self.setup_data['log_channel_id'] = channel.id
                await message.reply(f"<:j_icons_Correct:1382701297987485706> **Custom log channel set to {channel.mention}**")
            else:
                await message.reply("<:icons_Wrong:1382701332955402341> Please mention a valid channel!")

        self.waiting_for_custom = None

    async def finish_setup(self):
        try:
            async with self.bot.db.cursor() as cur:
                await cur.execute("""
                    INSERT OR REPLACE INTO tickets 
                    (guild_id, channel_id, role_id, log_channel_id,
                     embed_title, embed_description, embed_color, embed_image_url, embed_footer, ticket_limit)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.ctx.guild.id,
                    self.setup_data['channel_id'],
                    self.setup_data['role_id'],
                    self.setup_data['log_channel_id'],
                    self.setup_data['embed_title'],
                    self.setup_data['embed_description'],
                    self.setup_data['embed_color'],
                    self.setup_data['embed_image_url'],
                    self.setup_data['embed_footer'],
                    self.setup_data['ticket_limit']
                ))
                await self.bot.db.commit()

            if self.ctx.guild.id in self.bot.active_setups:
                del self.bot.active_setups[self.ctx.guild.id]

            return True, "<:j_icons_Correct:1382701297987485706> Setup completed successfully!"

        except Exception as e:
            logger.error(f"Error finishing setup: {e}")
            return False, f"<:icons_Wrong:1382701332955402341> Setup failed: {str(e)}"

class SetupPanelChannelSelect(discord.ui.Select):
    def __init__(self, guild):
        text_channels = [ch for ch in guild.channels if isinstance(ch, discord.TextChannel)]

        options = []
        for channel in text_channels[:24]:
            options.append(discord.SelectOption(
                label=f"#{channel.name}",
                value=str(channel.id),
                description=f"ID: {channel.id}"
            ))

        if len(text_channels) > 24:
            options.append(discord.SelectOption(
                label="Custom Channel",
                value="custom_channel",
                description="Mention a channel in chat",
                emoji="<:megaphone:1382704888294936649>"
            ))

        super().__init__(
            placeholder="🎫 Select Panel Channel...",
            options=options,
            custom_id="setup_panel_channel_select",
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        view: TicketSetupView = self.view

        if self.values[0] == "custom_channel":
            view.waiting_for_custom = "panel_channel"
            embed = discord.Embed(
                title="<:megaphone:1382704888294936649> Custom Panel Channel",
                description="**Please mention the channel in chat**\n\nExample: `#support`\n\nI'll set it as your ticket panel channel.",
                color=0xFF8C00
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            channel_id = int(self.values[0])
            channel = interaction.guild.get_channel(channel_id)
            view.setup_data['channel_id'] = channel_id

            embed = discord.Embed(
                title="<:Ticket_icons:1382703084815257610> Panel Channel Selected",
                description=f"**Ticket Panel Channel:** {channel.mention}\n\nUsers will create tickets from this channel.",
                color=0x00FF88
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

class SetupLogChannelSelect(discord.ui.Select):
    def __init__(self, guild):
        text_channels = [ch for ch in guild.channels if isinstance(ch, discord.TextChannel)]

        options = []
        for channel in text_channels[:24]:
            options.append(discord.SelectOption(
                label=f"#{channel.name}",
                value=str(channel.id),
                description=f"ID: {channel.id}"
            ))

        if len(text_channels) > 24:
            options.append(discord.SelectOption(
                label="Custom Log Channel",
                value="custom_log_channel",
                description="Mention a channel in chat",
                emoji="<:stats_1:1382703019334045830>"
            ))

        super().__init__(
            placeholder="📋 Select Log Channel...",
            options=options,
            custom_id="setup_log_channel_select",
            row=2
        )

    async def callback(self, interaction: discord.Interaction):
        view: TicketSetupView = self.view

        if self.values[0] == "custom_log_channel":
            view.waiting_for_custom = "log_channel"
            embed = discord.Embed(
                title="<:stats_1:1382703019334045830> Custom Log Channel",
                description="**Please mention the channel in chat**\n\nExample: `#ticket-logs`\n\nI'll set it as your transcript log channel.",
                color=0xFF8C00
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            channel_id = int(self.values[0])
            channel = interaction.guild.get_channel(channel_id)
            view.setup_data['log_channel_id'] = channel_id

            embed = discord.Embed(
                title="<:clipboard1:1383857546410070117> Log Channel Selected", 
                description=f"**Log Channel:** {channel.mention}\n\nTicket transcripts and logs will be sent here.",
                color=0x00FF88
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

class SetupSupportRoleSelect(discord.ui.Select):
    def __init__(self, guild):
        roles = [role for role in guild.roles if role != guild.default_role]

        options = []
        for role in roles[:24]:
            options.append(discord.SelectOption(
                label=f"@{role.name}",
                value=str(role.id),
                description=f"ID: {role.id}"
            ))

        if len(roles) > 24:
            options.append(discord.SelectOption(
                label="Custom Role",
                value="custom_role",
                description="Mention a role in chat",
                emoji="<:shield:1382703287891136564>"
            ))

        super().__init__(
            placeholder="👥 Select Support Role...",
            options=options,
            custom_id="setup_support_role_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        view: TicketSetupView = self.view

        if self.values[0] == "custom_role":
            view.waiting_for_custom = "role"
            embed = discord.Embed(
                title="<:shield:1382703287891136564> Custom Support Role",
                description="**Please mention the role in chat**\n\nExample: `@Support Team`\n\nI'll automatically detect and set it as your support role.",
                color=0xFF8C00
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            role_id = int(self.values[0])
            role = interaction.guild.get_role(role_id)
            view.setup_data['role_id'] = role_id

            embed = discord.Embed(
                title="<:people_icons:1384040549937451068> Support Role Selected",
                description=f"**Support Role:** {role.mention}\n\nMembers with this role can manage tickets.",
                color=0x00FF88
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


class NewPanelCustomizationModal(discord.ui.Modal):
    def __init__(self, setup_view):
        super().__init__(title="🎨 Panel Customization")
        self.setup_view = setup_view

    panel_title = discord.ui.TextInput(
        label="Panel Title",
        placeholder="Enter your custom panel title...",
        default="🎫 Support Center",
        max_length=100,
        required=True
    )

    panel_description = discord.ui.TextInput(
        label="Panel Description",
        style=discord.TextStyle.paragraph,
        placeholder="Describe what users should expect...",
        default="Need assistance? Select a category below to create a support ticket. Our expert team will help you shortly!",
        max_length=500,
        required=True
    )

    panel_color = discord.ui.TextInput(
        label="Panel Color (Hex Code)",
        placeholder="e.g., #5865F2 or 0x5865F2",
        default="#5865F2",
        max_length=10,
        required=False
    )

    panel_footer = discord.ui.TextInput(
        label="Panel Footer Text",
        placeholder="Footer text for your panel...",
        default="Powered by Harly Xploitz™ • Support System",
        max_length=100,
        required=False
    )

    panel_image = discord.ui.TextInput(
        label="Panel Image URL (Optional)",
        placeholder="https://example.com/image.png",
        max_length=200,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)

            self.setup_view.setup_data['embed_title'] = self.panel_title.value
            self.setup_view.setup_data['embed_description'] = self.panel_description.value
            self.setup_view.setup_data['embed_footer'] = self.panel_footer.value
            
            if self.panel_image.value.strip():
                image_url = self.panel_image.value.strip()
                if image_url.startswith(('http://', 'https://')):
                    self.setup_view.setup_data['embed_image_url'] = image_url
                else:
                    self.setup_view.setup_data['embed_image_url'] = None
            else:
                self.setup_view.setup_data['embed_image_url'] = None

            color_value = self.panel_color.value.strip()
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

            embed = discord.Embed(
                title="<:j_icons_Correct:1382701297987485706> Panel Customization Saved",
                description="**Your panel customization has been applied successfully!**\n\n"
                           "The changes will be visible when you deploy your panel.",
                color=0x00FF88,
                timestamp=discord.utils.utcnow()
            )

            embed.add_field(
                name="🎨 Preview",
                value=f"**Title:** {self.panel_title.value}\n"
                      f"**Color:** #{hex(self.setup_view.setup_data['embed_color'])[2:].upper()}\n"
                      f"**Footer:** {self.panel_footer.value[:50]}{'...' if len(self.panel_footer.value) > 50 else ''}\n"
                      f"**Image:** {'✅ Set' if self.setup_view.setup_data.get('embed_image_url') else '❌ None'}",
                inline=False
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in panel customization modal: {e}")
            error_embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Customization Error",
                description=f"**Failed to save customization:** {str(e)}",
                color=0xFF6B6B
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)

class SetupPanelCustomizationButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Customise Panel",
            style=discord.ButtonStyle.primary,
            emoji="<:paint_icons:1383849816022581332>",
            custom_id="setup_panel_customization_btn",
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        modal = NewPanelCustomizationModal(self.view)
        await interaction.response.send_modal(modal)

class SetupConfirmButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Confirm",
            style=discord.ButtonStyle.success,
            emoji="<:j_icons_Correct:1382701297987485706>",
            custom_id="setup_confirm_btn",
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        view: TicketSetupView = self.view

        if not view.setup_data['channel_id']:
            embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Missing Panel Channel",
                description="Please select a ticket panel channel first!",
                color=0xFF0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not view.setup_data['role_id']:
            embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Missing Support Role",
                description="Please select a support role first!",
                color=0xFF0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        guild = interaction.guild
        panel_channel = guild.get_channel(view.setup_data['channel_id'])
        support_role = guild.get_role(view.setup_data['role_id'])
        log_channel = guild.get_channel(view.setup_data['log_channel_id']) if view.setup_data['log_channel_id'] else None

        embed = discord.Embed(
            title="<:j_icons_Correct:1382701297987485706> Setup Configuration Preview",
            description="**Review your configuration before confirming**\n\nEverything looks good? Click **Finish Setup** to complete!",
            color=0x00D4FF,
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(
            name="<:Ticket_icons:1382703084815257610> **Panel Configuration**",
            value=f"**Channel:** {panel_channel.mention}\n**Ticket Limit:** {view.setup_data['ticket_limit']}",
            inline=True
        )

        embed.add_field(
            name="<:people_icons:1384040549937451068> **Support Configuration**", 
            value=f"**Support Role:** {support_role.mention}",
            inline=True
        )

        embed.add_field(
            name="<:stats_1:1382703019334045830> **Logging Configuration**",
            value=f"**Log Channel:** {log_channel.mention if log_channel else 'None'}\n**Transcripts:** {'Enabled' if log_channel else 'Disabled'}",
            inline=True
        )

        embed.add_field(
            name="<:paint_icons:1383849816022581332> **Panel Appearance**",
            value=f"**Title:** {view.setup_data['embed_title']}\n**Color:** #{hex(view.setup_data['embed_color'])[2:].upper()}",
            inline=False
        )

        embed.set_footer(text="Harly Xploitz™ • Configuration Preview")

        confirm_view = SetupFinalConfirmView(view)
        await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)

class SetupFinalConfirmView(discord.ui.View):
    def __init__(self, setup_view):
        super().__init__(timeout=300)
        self.setup_view = setup_view

    @discord.ui.button(label="Finish Setup", style=discord.ButtonStyle.success, emoji="<:UA_Rocket_icons:1382701592851124254>")
    async def finish_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        success, message = await self.setup_view.finish_setup()

        if success:
            embed = discord.Embed(
                title="<:giveaway_icons:1383874296727732317> Setup Complete!",
                description="**Your ticket system is ready!**\n\n"
                           "**Next Steps:**\n"
                           "1️⃣ Add categories: `/add-category <name>`\n"
                           "2️⃣ Send panel: `/send-panel dropdown`\n"
                           "3️⃣ Test the system: Create a ticket!\n\n"
                           "**<:glowingstar:1384041798669828098> Pro Tips:**\n"
                           "• Add multiple categories for organization\n"
                           "• Train your support team on ticket commands\n"
                           "• Monitor the log channel for ticket activities",
                color=0x00FF88,
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="Harly Xploitz™ • Support System Active")
        else:
            embed = discord.Embed(
                title="<:icons_Wrong:1382701332955402341> Setup Failed",
                description=f"**Error:** {message}\n\nPlease try the setup again or contact support.",
                color=0xFF0000
            )

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="<:icons_Wrong:1382701332955402341>")
    async def cancel_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="<:icons_Wrong:1382701332955402341> Setup Cancelled",
            description="Setup has been cancelled. No changes were made.\n\nYou can restart setup anytime with `/setup-tickets`.",
            color=0xFF6B6B
        )

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)



class TicketChannelView(discord.ui.View):
    def __init__(self, bot, ticket_data, creator_id=None, category="", ticket_number=0, subject="", description="", priority="Medium", priority_used=False):
        super().__init__(timeout=None)
        self.bot = bot
        self.priority_used = priority_used

        if isinstance(ticket_data, dict):
            self.ticket_data = ticket_data
        else:
            self.ticket_data = {
                'channel_id': None,
                'creator_id': creator_id,
                'category': category,
                'ticket_number': ticket_number,
                'subject': subject,
                'description': description,
                'priority': priority
            }

        self.add_close_button()
        self.add_claim_button()
        self.add_info_button()
        if not self.priority_used:
            self.add_priority_select()
        self.add_management_buttons()

    def add_close_button(self):
        """Add close ticket button"""
        close_button = discord.ui.Button(
            label="Close Ticket",
            style=discord.ButtonStyle.danger,
            emoji="<:welcome:1382706419765350480>",
            custom_id="close_ticket_btn",
            row=0
        )
        
        async def close_callback(interaction):
            control_view = TicketControlView(self.bot, self.ticket_data)
            await control_view.close_button.callback(interaction)
            
        close_button.callback = close_callback
        self.add_item(close_button)

    def add_claim_button(self):
        """Add claim ticket button"""
        claim_button = discord.ui.Button(
            label="Claim Ticket",
            style=discord.ButtonStyle.success,
            emoji="<:bye:1382701701399707709>",
            custom_id="claim_ticket_btn",
            row=0
        )
        
        async def claim_callback(interaction):
            control_view = TicketControlView(self.bot, self.ticket_data)
            await control_view.claim_button.callback(interaction)
            
        claim_button.callback = claim_callback
        self.add_item(claim_button)

    def add_info_button(self):
        """Add ticket info button"""
        info_button = discord.ui.Button(
            label="📊 Ticket Info",
            style=discord.ButtonStyle.secondary,
            emoji="📋",
            custom_id="ticket_info_btn",
            row=0
        )
        
        async def info_callback(interaction):
            await interaction.response.defer(ephemeral=True)
            
            from utils.tickets import get_ticket_info
            ticket_info = await get_ticket_info(self.bot, interaction.channel.id)
            
            if ticket_info:
                embed = discord.Embed(
                    title="📊 Detailed Ticket Information",
                    description=f"**Complete overview of Ticket #{ticket_info['ticket_number']:04d}**",
                    color=0x5865F2,
                    timestamp=discord.utils.utcnow()
                )
                
                embed.add_field(
                    name="🎫 **Basic Information**",
                    value=f"**🆔 Ticket ID:** `{interaction.channel.id}`\n"
                          f"**🔢 Number:** #{ticket_info['ticket_number']:04d}\n"
                          f"**📂 Category:** {ticket_info['category']}\n"
                          f"**⚡ Priority:** {ticket_info['priority']}\n"
                          f"**📊 Status:** {ticket_info['status'].title()}",
                    inline=True
                )
                
                creator = interaction.guild.get_member(ticket_info['creator_id'])
                embed.add_field(
                    name="👤 **Creator Details**",
                    value=f"**👤 User:** {creator.mention if creator else 'Unknown'}\n"
                          f"**🆔 ID:** `{ticket_info['creator_id']}`\n"
                          f"**📊 Status:** {'🟢 Online' if creator and creator.status != discord.Status.offline else '🔴 Offline'}\n"
                          f"**📅 Joined:** {discord.utils.format_dt(creator.joined_at, 'R') if creator else 'Unknown'}",
                    inline=True
                )
                
                message_count = 0
                async for _ in interaction.channel.history(limit=None):
                    message_count += 1
                
                created_time = discord.utils.parse_time(ticket_info['created_at']) if ticket_info['created_at'] else discord.utils.utcnow()
                duration = discord.utils.utcnow() - created_time
                
                embed.add_field(
                    name="📈 **Statistics**",
                    value=f"**💬 Messages:** {message_count}\n"
                          f"**⏰ Duration:** {duration.days}d {duration.seconds//3600}h {(duration.seconds//60)%60}m\n"
                          f"**📅 Created:** {discord.utils.format_dt(created_time, 'F')}\n"
                          f"**🕒 Relative:** {discord.utils.format_dt(created_time, 'R')}",
                    inline=False
                )
                
                embed.set_thumbnail(url=creator.display_avatar.url if creator else interaction.guild.icon.url)
                embed.set_footer(text="📊 Ticket Analytics • Real-time Data")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                error_embed = discord.Embed(
                    title="❌ Error",
                    description="Could not retrieve ticket information.",
                    color=0xFF0000
                )
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            
        info_button.callback = info_callback
        self.add_item(info_button)

    def add_priority_select(self):
        """Add priority selection dropdown"""
        priority_select = discord.ui.Select(
            placeholder="⚡ Change Priority Level...",
            options=[
                discord.SelectOption(label="🟢 Low Priority", value="Low", emoji="🟢", description="Non-urgent issues"),
                discord.SelectOption(label="🟡 Medium Priority", value="Medium", emoji="🟡", description="Standard priority"),
                discord.SelectOption(label="🟠 High Priority", value="High", emoji="🟠", description="Important issues"),
                discord.SelectOption(label="🔴 Critical Priority", value="Critical", emoji="🔴", description="Urgent/emergency issues")
            ],
            custom_id="priority_select_menu",
            row=1
        )
        
        async def priority_callback(interaction):
            try:
                priority = priority_select.values[0]

                from utils.database import user_has_support_role

                invoker = interaction.user
                has_support_role = await user_has_support_role(self.bot, invoker)
                is_admin = invoker.guild_permissions.administrator

                if not (has_support_role or is_admin):
                    embed = discord.Embed(
                        title="<:icons_locked:1382701901685985361> Permission Denied",
                        description="**Only support staff can change priority.**\n\nYou need to have at least one support role to modify ticket priorities.",
                        color=0xFF6B6B
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

                async with self.bot.db.cursor() as cur:
                    await cur.execute(
                        "UPDATE ticket_instances SET priority = ? WHERE channel_id = ?",
                        (priority, interaction.channel.id)
                    )
                    await self.bot.db.commit()

                priority_emojis = {
                    "Low": "🟢",
                    "Medium": "🟡", 
                    "High": "🟠",
                    "Critical": "🔴"
                }
                
                priority_emoji = priority_emojis.get(priority, "🟡")

                self.ticket_data['priority'] = priority

                current_name = interaction.channel.name
                clean_name = re.sub(r'^[🟢🟡🟠🔴]\s*', '', current_name)
                new_name = f"{priority_emoji} {clean_name}"
                
                try:
                    await interaction.channel.edit(
                        name=new_name,
                        reason=f"Priority changed to {priority} by {interaction.user.display_name}"
                    )
                except discord.HTTPException as e:
                    logger.warning(f"Could not rename channel: {e}")

                try:
                    async for message in interaction.channel.history(limit=50):
                        if (message.author == self.bot.user and 
                            message.embeds and 
                            len(message.embeds) > 0 and
                            "Support Ticket" in message.embeds[0].title and
                            message.components):
                            
                            original_embed = message.embeds[0]
                            
                            for i, field in enumerate(original_embed.fields):
                                if "Ticket Information" in field.name:
                                    field_lines = field.value.split('\n')
                                    updated_lines = []
                                    for line in field_lines:
                                        if line.startswith('**Priority:**'):
                                            updated_lines.append(f"**Priority:** {priority_emoji} {priority}")
                                        else:
                                            updated_lines.append(line)
                                    
                                    original_embed.set_field_at(i, name=field.name, value='\n'.join(updated_lines), inline=field.inline)
                                    break
                            
                            fresh_view = TicketChannelView(self.bot, self.ticket_data, priority_used=True)
                            await message.edit(embed=original_embed, view=fresh_view)
                            break
                            
                except Exception as edit_error:
                    logger.warning(f"Could not update control panel embed: {edit_error}")

                embed = discord.Embed(
                    title=f"<:j_icons_Correct:1382701297987485706> Priority Updated",
                    description=f"**{interaction.user.display_name}** changed this ticket priority to **{priority_emoji} {priority}**.\n\nChannel name and control panel updated with new priority.",
                    color=0x00D4FF,
                    timestamp=datetime.now(timezone.utc)
                )

                await interaction.response.send_message(embed=embed)

            except Exception as e:
                logger.error(f"Error setting priority: {e}")
                error_embed = discord.Embed(
                    title="<:icons_Wrong:1382701332955402341> Error",
                    description=f"Failed to set priority: {str(e)}",
                    color=0xFF6B6B
                )
                
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(embed=error_embed, ephemeral=True)
                    else:
                        await interaction.followup.send(embed=error_embed, ephemeral=True)
                except:
                    pass
            
        priority_select.callback = priority_callback
        self.add_item(priority_select)

    def add_management_buttons(self):
        """Add additional management buttons"""
        add_user_button = discord.ui.Button(
            label="👥 Add User",
            style=discord.ButtonStyle.secondary,
            emoji="➕",
            custom_id="add_user_btn",
            row=2
        )
        
        async def add_user_callback(interaction):
            embed = discord.Embed(
                title="👥 Add User to Ticket",
                description="**Use the command below to add a user to this ticket:**\n\n"
                           "```/add-user @username```\n\n"
                           "🔹 **Only support staff** can add users\n"
                           "🔹 **Added users** will have full access to this ticket\n"
                           "🔹 **Use responsibly** - only add relevant users",
                color=0x5865F2
            )
            embed.set_footer(text="💡 Tip: You can also mention users directly in the ticket")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        add_user_button.callback = add_user_callback
        self.add_item(add_user_button)
        
        transcript_button = discord.ui.Button(
            label="📄 Get Transcript",
            style=discord.ButtonStyle.secondary,
            emoji="📋",
            custom_id="transcript_btn",
            row=2
        )
        
        async def transcript_callback(interaction):
            await interaction.response.defer(ephemeral=True)
            
            try:
                from utils.helpers import generate_transcript
                transcript_content, transcript_file = await generate_transcript(interaction.channel)
                
                embed = discord.Embed(
                    title="📄 Ticket Transcript Generated",
                    description=f"**Complete conversation log for this ticket**\n\n"
                               f"🔹 **Channel:** {interaction.channel.mention}\n"
                               f"🔹 **Generated:** {discord.utils.format_dt(discord.utils.utcnow(), 'F')}\n"
                               f"🔹 **Format:** Plain text file\n\n"
                               f"📎 **Download attached transcript file below**",
                    color=0x00D4FF,
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="📄 Transcript Service • Complete Conversation Log")
                
                transcript_file.seek(0)
                await interaction.followup.send(
                    embed=embed,
                    file=discord.File(transcript_file, filename=f"ticket-transcript-{interaction.channel.id}.txt"),
                    ephemeral=True
                )
                
            except Exception as e:
                error_embed = discord.Embed(
                    title="❌ Transcript Error",
                    description=f"Failed to generate transcript: {str(e)}",
                    color=0xFF0000
                )
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            
        transcript_button.callback = transcript_callback
        self.add_item(transcript_button)



class TicketCloseConfirmationView(discord.ui.View):
    def __init__(self, bot, ticket_data):
        super().__init__(timeout=60)
        self.bot = bot
        self.ticket_data = ticket_data

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.danger, emoji="<:j_icons_Correct:1382701297987485706>")
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)

            channel = interaction.channel
            creator_id = self.ticket_data.get('creator_id')

            from utils.tickets import get_ticket_creator_member
            creator = await get_ticket_creator_member(self.bot, interaction.guild, channel.id) if creator_id else None

            if not creator and creator_id:
                class MockUser:
                    def __init__(self, user_id):
                        self.id = user_id
                        self.mention = f"<@{user_id}>"
                        self.display_name = "Unknown User"
                        self.name = "Unknown User"

                creator = MockUser(creator_id)

            ticket_number = self.ticket_data.get('ticket_number', 0)
            closer_name = interaction.user.display_name

            transcript_content, transcript_file = await generate_transcript(channel)

            if creator:
                try:
                    closure_embed = discord.Embed(
                        title="<:icons_locked:1382701901685985361> Your Ticket Has Been Closed",
                        description=f"**Ticket #{ticket_number:04d}** has been closed by **{closer_name}**.\n\n"
                                   f"**Category:** {self.ticket_data.get('category', 'Unknown')}\n"
                                   f"**Subject:** {self.ticket_data.get('subject', 'No subject')}\n\n"
                                   f"Thank you for using our support system! Your complete transcript is attached below.",
                        color=0x00D4FF,
                        timestamp=discord.utils.utcnow()
                    )
                    closure_embed.set_footer(text="Transcript attached • Rating request will follow")

                    await creator.send(embed=closure_embed)
                    logger.info(f"Sent closure embed to user {creator.id}")
                    
                    await send_transcript_dm(creator, channel.name, transcript_file)
                    logger.info(f"Sent transcript to user {creator.id}")

                    try:
                        from utils.rating_system import send_rating_request
                        await send_rating_request(self.bot, creator, ticket_number, closer_name, interaction.guild.id)
                        logger.info(f"Sent rating request to user {creator.id}")
                    except Exception as rating_error:
                        logger.error(f"Error sending rating request: {rating_error}")

                    

                except discord.Forbidden:
                    logger.warning(f"Could not send DMs to user {creator.id} - DMs are disabled")
                except Exception as e:
                    logger.error(f"Error sending closure embed or transcript to user {creator.id}: {e}")
                    try:
                        fallback_embed = discord.Embed(
                            title="<:icons_Wrong:1382701332955402341> DM Error",
                            description=f"{creator.mention}, there was an error sending your transcript. "
                                       f"Please contact support if you need a copy of your ticket transcript.",
                            color=0xFF6B6B
                        )
                        await channel.send(embed=fallback_embed)
                    except:
                        pass

            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT log_channel_id FROM tickets WHERE guild_id = ?", (interaction.guild.id,))
                result = await cur.fetchone()

                if result and result[0]:
                    log_channel = interaction.guild.get_channel(result[0])
                    if log_channel:
                        close_time = discord.utils.utcnow()

                        creator_name = "Unknown User"
                        if creator:
                            creator_name = getattr(creator, 'display_name', None) or getattr(creator, 'name', 'Unknown User')

                        close_embed = discord.Embed(
                            title="Logs - Ticket Closed!",
                            description=f"> Ticket `#{ticket_number:04d}` has been closed {discord.utils.format_dt(close_time, 'R')}! ({discord.utils.format_dt(close_time, 'F')})\n\n"
                                       f"**Ticket's Author**\n```{creator_name} ({self.ticket_data.get('creator_id')})```"
                                       f"**Closed By**\n```{interaction.user.display_name} ({interaction.user.id})```"
                                       f"**Ticket ID**\n```{channel.id}```",
                            color=0xFF6B6B,
                            timestamp=close_time
                        )

                        from utils.author_info import TicketClosedLogView
                        view = TicketClosedLogView(self.bot, self.ticket_data)

                        await log_channel.send(embed=close_embed, view=view)

                        transcript_file.seek(0)
                        await log_channel.send(file=discord.File(transcript_file, filename=f"ticket-{ticket_number:04d}-transcript.txt"))

            async with self.bot.db.cursor() as cur:
                await cur.execute(
                    "UPDATE ticket_instances SET status = 'closed', closed_at = CURRENT_TIMESTAMP WHERE channel_id = ?",
                    (channel.id,)
                )
                await self.bot.db.commit()

            await interaction.followup.send("<:j_icons_Correct:1382701297987485706> Ticket closed successfully.", ephemeral=True)
            await asyncio.sleep(1)
            await channel.delete(reason=f"Ticket #{ticket_number:04d} closed by {interaction.user}")

        except Exception as e:
            logger.error(f"Error closing ticket: {e}")
            await interaction.followup.send(f"<:icons_Wrong:1382701332955402341> Error closing ticket: {str(e)}", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="<:icons_Wrong:1382701332955402341>")
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("<:icons_Wrong:1382701332955402341> Ticket close cancelled.", ephemeral=True)

class TicketClosedLogView(discord.ui.View):
    def __init__(self, bot, ticket_data):
        super().__init__(timeout=None)
        self.bot = bot
        self.ticket_data = ticket_data