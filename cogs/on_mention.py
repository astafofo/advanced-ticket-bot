
import discord
from discord.ext import commands
import logging
from utils.config import Config

logger = logging.getLogger('discord')

class OnMention(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        
        # Only respond to direct mentions, not when replying to bot's messages
        if (self.bot.user.mentioned_in(message) and 
            not message.mention_everyone and 
            not (message.reference and message.reference.resolved and 
                 message.reference.resolved.author == self.bot.user)):
            try:
                embed = discord.Embed(
                    title="<:UA_Rocket_icons:1382701592851124254> Hey there! Thanks for mentioning me!",
                    description=f"<:welcome:1382706419765350480> **Welcome to the {self.bot.user.name} Support System!**\n\n<:icons_heart:1382705238619984005> I'm here to help you create and manage support tickets efficiently.\n\n<:j_icons_Correct:1382701297987485706> **Quick Start:**\n• Use `{self.config.PREFIX}help` for command list\n• Use `/help` for slash commands\n• Set up with `{self.config.PREFIX}setup-tickets`\n\n<:people_icons:1384040549937451068> Need assistance? Join our support server below!",
                    color=0x000000
                )
                
                support_guild = self.bot.get_guild(1381702592095809576)
                thumbnail_url = support_guild.icon.url if support_guild and support_guild.icon else self.bot.user.display_avatar.url
                embed.set_thumbnail(url=thumbnail_url)
                
                embed.add_field(
                    name="<:Ticket_icons:1382703084815257610> **Quick Commands**",
                    value=f"`{self.config.PREFIX}setup-tickets` - Complete setup wizard\n`{self.config.PREFIX}add-category` - Add support category\n`{self.config.PREFIX}send-panel` - Deploy ticket panel",
                    inline=True
                )
                
                embed.add_field(
                    name="<:stats_1:1382703019334045830> **Useful Links**",
                    value=f"<:Icons_link:1382706535766954035> **[Support Server]({self.config.SUPPORT_SERVER})**\n<:icons_wrench:1382702984940617738> **[Setup Guide](https://discord.gg/GQfuF4Bx8r)**",
                    inline=True
                )
                
                embed.set_footer(
                    text=f"Powered by Harly Xploitz™ • Prefix: {self.config.PREFIX}",
                    icon_url=self.bot.user.display_avatar.url
                )
                
                await message.reply(embed=embed, mention_author=False)
                
                logger.info(f"Sent mention response to {message.author} in {message.guild.name if message.guild else 'DM'}")
                
            except Exception as e:
                logger.error(f"Error sending mention response: {e}")

async def setup(bot):
    await bot.add_cog(OnMention(bot))
