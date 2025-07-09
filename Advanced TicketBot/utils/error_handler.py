
import logging
import traceback
import discord
from discord.ext import commands
from datetime import datetime, timezone
import asyncio

logger = logging.getLogger('discord')

class GlobalErrorHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def create_error_embed(self, title: str, description: str, error_type: str = "general") -> discord.Embed:
        """Create a standardized error embed"""
        
        error_configs = {
            "permission": {
                "color": 0xFF6B6B,
                "emoji": "<:icons_locked:1382701901685985361>"
            },
            "bot_permission": {
                "color": 0xFF6B6B, 
                "emoji": "<:robot:1382702105722228824>"
            },
            "cooldown": {
                "color": 0xFF8C00,
                "emoji": "<:icons_clock:1382701751206936697>"
            },
            "not_found": {
                "color": 0xFF6B6B,
                "emoji": "<:icons_Wrong:1382701332955402341>"
            },
            "validation": {
                "color": 0xFF8C00,
                "emoji": "<:warning:1382701413284446228>"
            },
            "database": {
                "color": 0xFF0000,
                "emoji": "<:disk_icons:1384042698192715899>"
            },
            "network": {
                "color": 0xFF4444,
                "emoji": "<:icons_refresh:1382701477759549523>"
            },
            "general": {
                "color": 0xFF6B6B,
                "emoji": "<:icons_Wrong:1382701332955402341>"
            }
        }
        
        config = error_configs.get(error_type, error_configs["general"])
        
        embed = discord.Embed(
            title=f"{config['emoji']} {title}",
            description=description,
            color=config["color"],
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.set_footer(text=" Support System • Error Handler")
        return embed

    async def send_error_response(self, ctx, embed: discord.Embed):
        """Send error response handling both interactions and regular commands"""
        try:
            if isinstance(ctx, discord.Interaction):
                if ctx.response.is_done():
                    await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx.response.send_message(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)
        except Exception as e:
            simple_message = f"{embed.title}\n{embed.description}"
            try:
                if isinstance(ctx, discord.Interaction):
                    if ctx.response.is_done():
                        await ctx.followup.send(simple_message, ephemeral=True)
                    else:
                        await ctx.response.send_message(simple_message, ephemeral=True)
                else:
                    await ctx.send(simple_message)
            except:
                logger.error(f"Failed to send error message: {e}")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Handle all command errors globally"""
        
        ignored = (commands.CommandNotFound, commands.DisabledCommand)
        if isinstance(error, ignored):
            return

        logger.error(f"Command error in {ctx.command}: {error}")
        logger.error(traceback.format_exc())

        if isinstance(error, commands.MissingPermissions):
            embed = self.create_error_embed(
                "Missing Permissions",
                f"**You don't have the required permissions to use this command.**\n\n"
                f"**Required Permissions:**\n{', '.join(error.missing_permissions)}\n\n"
                f"<:lightbulb:1382701619753386035> Contact an administrator if you believe this is an error.",
                "permission"
            )
            
        elif isinstance(error, commands.BotMissingPermissions):
            embed = self.create_error_embed(
                "Bot Missing Permissions", 
                f"**I don't have the required permissions to execute this command.**\n\n"
                f"**Missing Permissions:**\n{', '.join(error.missing_permissions)}\n\n"
                f"<:icons_wrench:1382702984940617738> Please ask an administrator to grant me these permissions.",
                "bot_permission"
            )
            
        elif isinstance(error, commands.CommandOnCooldown):
            embed = self.create_error_embed(
                "Command Cooldown",
                f"**This command is on cooldown.**\n\n"
                f"<:icons_clock:1382701751206936697> **Try again in:** {error.retry_after:.1f} seconds\n\n"
                f"Cooldowns help prevent spam and ensure optimal performance.",
                "cooldown"
            )
            
        elif isinstance(error, commands.MissingRequiredArgument):
            embed = self.create_error_embed(
                "Missing Required Argument",
                f"**Missing required argument: `{error.param.name}`**\n\n"
                f"<:clipboard1:1383857546410070117> **Usage:** `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`\n\n"
                f"<:lightbulb:1382701619753386035> Use `{ctx.prefix}help {ctx.command.qualified_name}` for more information.",
                "validation"
            )
            
        elif isinstance(error, commands.BadArgument):
            embed = self.create_error_embed(
                "Invalid Argument",
                f"**Invalid argument provided.**\n\n"
                f"<:clipboard1:1383857546410070117> **Usage:** `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`\n\n"
                f"**Error Details:** {str(error)}\n\n"
                f"<:lightbulb:1382701619753386035> Use `{ctx.prefix}help {ctx.command.qualified_name}` for more information.",
                "validation"
            )
            
        elif isinstance(error, commands.NotOwner):
            embed = self.create_error_embed(
                "Owner Only Command",
                f"**This command is restricted to the bot owner only.**\n\n"
                f"<:shield:1382703287891136564> This is a developer command and cannot be used by regular users.",
                "permission"
            )
            
        elif isinstance(error, commands.NSFWChannelRequired):
            embed = self.create_error_embed(
                "NSFW Channel Required",
                f"**This command can only be used in NSFW channels.**\n\n"
                f"<:warning:1382701413284446228> Please use this command in an appropriate channel.",
                "validation"
            )
            
        elif isinstance(error, discord.Forbidden):
            embed = self.create_error_embed(
                "Permission Denied",
                f"**I don't have permission to perform this action.**\n\n"
                f"<:icons_wrench:1382702984940617738> Please check my permissions and try again.\n\n"
                f"**Action attempted:** {str(error)}",
                "bot_permission"
            )
            
        elif isinstance(error, discord.NotFound):
            embed = self.create_error_embed(
                "Resource Not Found",
                f"**The requested resource could not be found.**\n\n"
                f"<:Target:1382706193855942737> This might be a deleted channel, message, or user.\n\n"
                f"**Details:** {str(error)}",
                "not_found"
            )
            
        elif isinstance(error, discord.HTTPException):
            if "rate limit" in str(error).lower():
                embed = self.create_error_embed(
                    "Rate Limited",
                    f"**Discord is rate limiting the bot.**\n\n"
                    f"<:icons_clock:1382701751206936697> Please wait a moment and try again.\n\n"
                    f"This helps prevent spam and keeps Discord stable.",
                    "network"
                )
            else:
                embed = self.create_error_embed(
                    "Discord API Error",
                    f"**An error occurred while communicating with Discord.**\n\n"
                    f"<:icons_refresh:1382701477759549523> Please try again in a moment.\n\n"
                    f"**Error:** {str(error)[:200]}",
                    "network"
                )
                
        elif "database" in str(error).lower() or "sqlite" in str(error).lower():
            embed = self.create_error_embed(
                "Database Error",
                f"**A database error occurred.**\n\n"
                f"<:disk_icons:1384042698192715899> Our team has been notified and will fix this soon.\n\n"
                f"<:icons_refresh:1382701477759549523> Please try again in a few minutes.",
                "database"
            )
            
        else:
            embed = self.create_error_embed(
                "Unexpected Error",
                f"**An unexpected error occurred while executing this command.**\n\n"
                f"<:icons_refresh:1382701477759549523> Please try again. If the issue persists, contact support.\n\n"
                f"**Error:** {str(error)[:200]}{'...' if len(str(error)) > 200 else ''}",
                "general"
            )
            
            error_id = f"{hash(str(error)) % 10000:04d}"
            embed.add_field(
                name="<:clipboard1:1383857546410070117> Error ID",
                value=f"`{error_id}`",
                inline=False
            )
            
            logger.error(f"Error ID {error_id}: {str(error)}")

        await self.send_error_response(ctx, embed)

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        """Handle all application command errors globally"""
        
        logger.error(f"App command error: {error}")
        logger.error(traceback.format_exc())

        if isinstance(error, discord.app_commands.MissingPermissions):
            embed = self.create_error_embed(
                "Missing Permissions",
                f"**You don't have the required permissions to use this command.**\n\n"
                f"**Required Permissions:**\n{', '.join(error.missing_permissions)}\n\n"
                f"<:lightbulb:1382701619753386035> Contact an administrator if you believe this is an error.",
                "permission"
            )
            
        elif isinstance(error, discord.app_commands.BotMissingPermissions):
            embed = self.create_error_embed(
                "Bot Missing Permissions",
                f"**I don't have the required permissions to execute this command.**\n\n"
                f"**Missing Permissions:**\n{', '.join(error.missing_permissions)}\n\n"
                f"<:icons_wrench:1382702984940617738> Please ask an administrator to grant me these permissions.",
                "bot_permission"
            )
            
        elif isinstance(error, discord.app_commands.MissingRole):
            embed = self.create_error_embed(
                "Missing Role",
                f"**You need a specific role to use this command.**\n\n"
                f"**Required Role:** {error.missing_role}\n\n"
                f"<:icons_Person:1382703571056853082> Contact an administrator to get the required role.",
                "permission"
            )
            
        elif isinstance(error, discord.app_commands.CommandOnCooldown):
            embed = self.create_error_embed(
                "Command Cooldown",
                f"**This command is on cooldown.**\n\n"
                f"<:icons_clock:1382701751206936697> **Try again in:** {error.retry_after:.1f} seconds\n\n"
                f"Cooldowns help prevent spam and ensure optimal performance.",
                "cooldown"
            )
            
        elif isinstance(error, discord.app_commands.TransformerError):
            embed = self.create_error_embed(
                "Invalid Input",
                f"**Invalid input provided.**\n\n"
                f"<:warning:1382701413284446228> Please check your input and try again.\n\n"
                f"**Error:** {str(error)}",
                "validation"
            )
            
        else:
            embed = self.create_error_embed(
                "Command Error",
                f"**An error occurred while executing this command.**\n\n"
                f"<:icons_refresh:1382701477759549523> Please try again. If the issue persists, contact support.\n\n"
                f"**Error:** {str(error)[:200]}{'...' if len(str(error)) > 200 else ''}",
                "general"
            )
            
            embed.add_field(
                name="<:clipboard1:1383857546410070117> Error ID", 
                value=f"`{hash(str(error)) % 10000:04d}`",
                inline=False
            )

        await self.send_error_response(interaction, embed)

    @commands.Cog.listener()
    async def on_error(self, event, *args, **kwargs):
        """Handle all other bot errors"""
        logger.error(f"Bot error in event {event}")
        logger.error(traceback.format_exc())
        
        print(f"\033[91m[GLOBAL ERROR] Event: {event}\033[0m")
        print(f"\033[91m[GLOBAL ERROR] Args: {args}\033[0m")

    async def handle_view_error(self, interaction: discord.Interaction, error: Exception, error_type: str = "general"):
        """Handle errors from Discord UI views"""
        logger.error(f"View error: {error}")
        logger.error(traceback.format_exc())
        
        embed = self.create_error_embed(
            "Interface Error",
            f"**An error occurred with the user interface.**\n\n"
            f"<:icons_refresh:1382701477759549523> Please try again or refresh the interface.\n\n"
            f"**Error:** {str(error)[:200]}{'...' if len(str(error)) > 200 else ''}",
            error_type
        )
        
        await self.send_error_response(interaction, embed)

    async def handle_database_error(self, ctx, error: Exception):
        """Handle database-specific errors"""
        logger.error(f"Database error: {error}")
        logger.error(traceback.format_exc())
        
        embed = self.create_error_embed(
            "Database Connection Error",
            f"**Unable to connect to the database.**\n\n"
            f"<:disk_icons:1384042698192715899> This is usually temporary and resolves quickly.\n\n"
            f"<:icons_refresh:1382701477759549523> Please try again in a moment.",
            "database"
        )
        
        await self.send_error_response(ctx, embed)

async def setup(bot):
    await bot.add_cog(GlobalErrorHandler(bot))
