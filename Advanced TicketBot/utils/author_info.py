
import discord
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger('discord')

class TicketAuthorInfoSystem:
    """Advanced ticket author information system"""
    
    def __init__(self, bot):
        self.bot = bot
    
    async def get_user_info(self, guild, user_id, fetch_from_api=True):
        """Get comprehensive user information - DIRECT guild member check first"""
        try:
            member = guild.get_member(user_id)
            
            if member:
                logger.info(f"<:j_icons_Correct:1382701297987485706> Direct guild lookup found member {user_id} in server {guild.id}")
                return await self._get_member_info(member)
            
            logger.info(f"🔄 Member {user_id} not in cache, forcing guild chunk for {guild.id}")
            try:
                if not guild.chunked:
                    await guild.chunk()
                    logger.info(f"📥 Guild {guild.id} chunked successfully")
                
                member = guild.get_member(user_id)
                if member:
                    logger.info(f"<:j_icons_Correct:1382701297987485706> Found member {user_id} after chunking guild {guild.id}")
                    return await self._get_member_info(member)
                else:
                    logger.info(f"<:icons_Wrong:1382701332955402341> Member {user_id} definitively not in guild {guild.id} after chunking")
                    
            except Exception as chunk_error:
                logger.warning(f"<:warning:1382701413284446228> Failed to chunk guild {guild.id}: {chunk_error}")
            
            logger.info(f"🔍 Performing manual member search for {user_id} in guild {guild.id}")
            for member in guild.members:
                if member.id == user_id:
                    logger.info(f"<:j_icons_Correct:1382701297987485706> Manual search found member {user_id} in guild {guild.id}")
                    return await self._get_member_info(member)
            
            logger.info(f"<:icons_Wrong:1382701332955402341> User {user_id} confirmed NOT in server {guild.id} - trying API")
            if fetch_from_api:
                try:
                    user = await self.bot.fetch_user(user_id)
                    if user:
                        logger.info(f"📡 API fetch successful for user {user_id} - user left server")
                        return await self._get_left_user_info(user, guild)
                except discord.NotFound:
                    logger.info(f"<:Icons_Trash:1382703995700645969> User {user_id} account deleted")
                    return await self._get_deleted_user_info(user_id)
                except discord.HTTPException as e:
                    logger.warning(f"<:warning:1382701413284446228> HTTP error fetching user {user_id}: {e}")
                    return await self._get_unknown_user_info(user_id)
            
            logger.info(f"❓ Could not determine status of user {user_id}")
            return await self._get_unknown_user_info(user_id)
            
        except Exception as e:
            logger.error(f"<:icons_Wrong:1382701332955402341> Error getting user info for {user_id}: {e}")
            return await self._get_error_info(user_id, str(e))
    
    async def _get_member_info(self, member):
        """Get detailed information for current guild member"""
        return {
            'type': 'member',
            'user': member,
            'id': member.id,
            'name': member.name,
            'display_name': member.display_name,
            'mention': member.mention,
            'avatar_url': member.display_avatar.url,
            'joined_at': member.joined_at,
            'created_at': member.created_at,
            'status': member.status,
            'activity': member.activity,
            'roles': [role for role in member.roles if role != member.guild.default_role],
            'permissions': member.guild_permissions,
            'is_bot': member.bot,
            'is_system': member.system,
            'premium_since': getattr(member, 'premium_since', None),
            'pending': getattr(member, 'pending', False),
            'timed_out_until': getattr(member, 'timed_out_until', None),
            'in_server': True
        }
    
    async def _get_left_user_info(self, user, guild):
        """Get information for user who left the guild"""
        return {
            'type': 'left_user',
            'user': user,
            'id': user.id,
            'name': user.name,
            'display_name': user.display_name,
            'mention': user.mention,
            'avatar_url': user.display_avatar.url,
            'created_at': user.created_at,
            'is_bot': user.bot,
            'is_system': user.system,
            'in_server': False,
            'left_guild': True
        }
    
    async def _get_deleted_user_info(self, user_id):
        """Get information for deleted user account"""
        return {
            'type': 'deleted',
            'id': user_id,
            'mention': f"<@{user_id}>",
            'in_server': False,
            'account_deleted': True
        }
    
    async def _get_unknown_user_info(self, user_id):
        """Get minimal information for unknown user"""
        return {
            'type': 'unknown',
            'id': user_id,
            'mention': f"<@{user_id}>",
            'in_server': False,
            'unknown': True
        }
    
    async def _get_error_info(self, user_id, error):
        """Get error information"""
        return {
            'type': 'error',
            'id': user_id,
            'mention': f"<@{user_id}>",
            'error': error
        }
    
    def create_user_info_embed(self, user_info):
        """Create embed with user information"""
        if user_info['type'] == 'member':
            return self._create_member_embed(user_info)
        elif user_info['type'] == 'left_user':
            return self._create_left_user_embed(user_info)
        elif user_info['type'] == 'deleted':
            return self._create_deleted_embed(user_info)
        elif user_info['type'] == 'unknown':
            return self._create_unknown_embed(user_info)
        else:
            return self._create_error_embed(user_info)
    
    def _create_member_embed(self, info):
        """Create embed for current guild member"""
        member = info['user']
        embed = discord.Embed(
            title=f"Ticket author {info['name']}'s user info",
            description="> :identification_card: Information about the Ticket's author.",
            color=0x00D4FF,
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(
            name="Identificators",
            value=f"``{info['id']}`` {info['mention']}",
            inline=False
        )
        
        if info['joined_at']:
            embed.add_field(
                name="Joined",
                value=f"```{info['joined_at'].strftime('%a, %b %d, %Y %I:%M %p')}```",
                inline=False
            )
        
        embed.add_field(
            name="Registered",
            value=f"```{info['created_at'].strftime('%a, %b %d, %Y %I:%M %p')}```",
            inline=False
        )
        
        perms = info['permissions']
        key_perms = []
        perm_checks = [
            ('kick_members', 'Kick Members'),
            ('ban_members', 'Ban Members'),
            ('administrator', 'Administrator'),
            ('manage_channels', 'Manage Channels'),
            ('view_channel', 'View Channel'),
            ('send_messages', 'Send Messages'),
            ('manage_messages', 'Manage Messages'),
            ('mention_everyone', 'Mention Everyone'),
            ('manage_nicknames', 'Manage Nicknames'),
            ('moderate_members', 'Moderate Members'),
            ('use_soundboard', 'Use Soundboard'),
            ('send_voice_messages', 'Send Voice Messages')
        ]
        
        for perm_attr, perm_name in perm_checks:
            if getattr(perms, perm_attr, False):
                key_perms.append(perm_name)
        
        embed.add_field(
            name="Key Permissions",
            value=f"```{', '.join(key_perms) if key_perms else 'No special permissions'}```",
            inline=False
        )
        
        acknowledgements = []
        if perms.administrator:
            acknowledgements.append("Server Admin")
        
        if info['roles']:
            high_roles = [role for role in info['roles'] if role.permissions.administrator or role.permissions.manage_guild]
            if high_roles:
                acknowledgements.extend([f"{role.name}" for role in high_roles[:3]])
        
        if acknowledgements:
            embed.add_field(
                name="Acknowledgements",
                value=f"```{', '.join(acknowledgements)}```",
                inline=False
            )
        
        status_info = []
        if info['status'] != discord.Status.offline:
            status_info.append(f"Status: {info['status'].name.title()}")
        
        if info['activity']:
            status_info.append(f"Activity: {info['activity'].name if hasattr(info['activity'], 'name') else str(info['activity'])}")
        
        if info['premium_since']:
            status_info.append("Server Booster")
        
        if info['timed_out_until']:
            status_info.append("Currently Timed Out")
        
        if status_info:
            embed.add_field(
                name="Status",
                value=f"```{' | '.join(status_info)}```",
                inline=False
            )
        
        if info['roles']:
            top_roles = sorted(info['roles'], key=lambda r: r.position, reverse=True)[:5]
            embed.add_field(
                name="Top Roles",
                value=" ".join([role.mention for role in top_roles]),
                inline=False
            )
        
        embed.set_thumbnail(url=info['avatar_url'])
        embed.set_footer(text="Support System • User Information • Currently in Server ✅")
        
        return embed
    
    def _create_left_user_embed(self, info):
        """Create embed for user who left the server"""
        embed = discord.Embed(
            title=f"Ticket author {info['name']}'s user info",
            description="> :identification_card: Information about the Ticket's author.",
            color=0xFF8C00,
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(
            name="Identificators",
            value=f"``{info['id']}`` {info['mention']}",
            inline=False
        )
        
        embed.add_field(
            name="Registered",
            value=f"```{info['created_at'].strftime('%a, %b %d, %Y %I:%M %p')}```",
            inline=False
        )
        
        embed.add_field(
            name="Account Type",
            value=f"```{'Bot Account' if info['is_bot'] else 'User Account'}```",
            inline=False
        )
        
        embed.add_field(
            name="Status",
            value="```<:warning:1382701413284446228> User has left the server```",
            inline=False
        )
        
        embed.set_thumbnail(url=info['avatar_url'])
        embed.set_footer(text="Support System • User Information • Left Server")
        
        return embed
    
    def _create_deleted_embed(self, info):
        """Create embed for deleted user account"""
        embed = discord.Embed(
            title="Ticket author info",
            description="> :identification_card: Information about the Ticket's author.",
            color=0xFF6B6B,
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(
            name="Identificators",
            value=f"``{info['id']}`` {info['mention']}",
            inline=False
        )
        
        embed.add_field(
            name="Status",
            value="```<:icons_Wrong:1382701332955402341> User account has been deleted```",
            inline=False
        )
        
        embed.add_field(
            name="Information",
            value="```This Discord account no longer exists```",
            inline=False
        )
        
        embed.set_footer(text="Support System • User Information • Account Deleted")
        
        return embed
    
    def _create_unknown_embed(self, info):
        """Create embed for unknown user"""
        embed = discord.Embed(
            title="Ticket author info",
            description="> :identification_card: Information about the Ticket's author.",
            color=0xFF6B6B,
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(
            name="Identificators",
            value=f"``{info['id']}`` {info['mention']}",
            inline=False
        )
        
        embed.add_field(
            name="Status",
            value="```<:warning:1382701413284446228> User has left the server```",
            inline=False
        )
        
        embed.add_field(
            name="Information",
            value="```Could not fetch additional user information```",
            inline=False
        )
        
        embed.set_footer(text="Support System • User Information • Left Server")
        
        return embed
    
    def _create_error_embed(self, info):
        """Create embed for error case"""
        embed = discord.Embed(
            title="Ticket author info",
            description="> :identification_card: Information about the Ticket's author.",
            color=0xFF0000,
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(
            name="Error",
            value=f"```{info['error']}```",
            inline=False
        )
        
        embed.add_field(
            name="User ID",
            value=f"``{info['id']}``",
            inline=False
        )
        
        embed.set_footer(text="Support System • User Information • Error")
        
        return embed

class UserAvatarView(discord.ui.View):
    """Advanced avatar view with multiple options"""
    
    def __init__(self, user_info):
        super().__init__(timeout=300)
        self.user_info = user_info
    
    @discord.ui.button(label="View Avatar", style=discord.ButtonStyle.primary, emoji="<:icons_heart:1382705238619984005>")
    async def view_avatar(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if self.user_info['type'] in ['member', 'left_user']:
                user = self.user_info['user']
                avatar_embed = discord.Embed(
                    title=f"{self.user_info['display_name']}'s Avatar",
                    color=0x00D4FF,
                    timestamp=datetime.now(timezone.utc)
                )
                avatar_embed.set_image(url=self.user_info['avatar_url'])
                
                avatar_formats = []
                base_url = str(user.display_avatar.url).split('?')[0]
                
                formats = ['png', 'jpg', 'webp']
                if user.display_avatar.is_animated():
                    formats.insert(0, 'gif')
                
                for fmt in formats:
                    avatar_formats.append(f"[{fmt.upper()}]({base_url}.{fmt}?size=1024)")
                
                avatar_embed.add_field(
                    name="Download Links",
                    value=" • ".join(avatar_formats),
                    inline=False
                )
                
                avatar_embed.set_footer(text="Support System • Avatar Viewer")
                await interaction.response.send_message(embed=avatar_embed, ephemeral=True)
            else:
                await interaction.response.send_message("<:icons_Wrong:1382701332955402341> Avatar not available for this user", ephemeral=True)
        except Exception as e:
            logger.error(f"Error displaying avatar: {e}")
            await interaction.response.send_message(f"<:icons_Wrong:1382701332955402341> Error displaying avatar: {str(e)}", ephemeral=True)

class TicketClosedLogView(discord.ui.View):
    """Enhanced ticket closed log view with advanced author info"""
    
    def __init__(self, bot, ticket_data):
        super().__init__(timeout=None)
        self.bot = bot
        self.ticket_data = ticket_data
        self.author_system = TicketAuthorInfoSystem(bot)
    
    @discord.ui.button(label="Ticket Author Info", style=discord.ButtonStyle.secondary, emoji="<:id_icons:1384041001114407013>", custom_id="advanced_ticket_author_info")
    async def author_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            
            creator_id = self.ticket_data.get('creator_id')
            
            if not creator_id and interaction.message.embeds:
                embed_content = interaction.message.embeds[0]
                if embed_content and embed_content.description:
                    match = re.search(r'```.*?\((\d+)\)```', embed_content.description)
                    if match:
                        creator_id = int(match.group(1))
            
            if not creator_id:
                await interaction.followup.send("<:icons_Wrong:1382701332955402341> **Creator ID not found in ticket data**", ephemeral=True)
                return
            
            user_info = await self.author_system.get_user_info(interaction.guild, creator_id)
            
            embed = self.author_system.create_user_info_embed(user_info)
            
            view = None
            if user_info['type'] in ['member', 'left_user']:
                view = UserAvatarView(user_info)
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in advanced author info: {e}")
            await interaction.followup.send(f"<:icons_Wrong:1382701332955402341> **System Error:** {str(e)}", ephemeral=True)
