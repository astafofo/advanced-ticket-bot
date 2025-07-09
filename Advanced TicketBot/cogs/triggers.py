import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
import logging

logger = logging.getLogger('discord')

class TriggerSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.triggers_db = None
        self.bot.loop.create_task(self.setup_triggers_database())

    async def setup_triggers_database(self):
        """Setup the triggers database"""
        try:
            if not self.triggers_db:
                self.triggers_db = await aiosqlite.connect('triggers.db')

            async with self.triggers_db.cursor() as cur:
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS triggers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER NOT NULL,
                        keyword TEXT NOT NULL,
                        message TEXT NOT NULL,
                        created_by INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(guild_id, keyword)
                    )
                """)
                await self.triggers_db.commit()
                logger.info("Triggers database setup completed")

        except Exception as e:
            logger.error(f"Error setting up triggers database: {e}")

    async def cog_load(self):
        """Initialize the triggers database when cog loads"""
        await self.setup_triggers_database()

    @commands.hybrid_command(name="add-trigger", description="Add a keyword trigger with an automatic response.")
    @app_commands.describe(
        keyword="The keyword that will trigger the response",
        message="The message to send when the keyword is detected"
    )
    @commands.has_permissions(administrator=True)
    async def add_trigger(self, ctx: commands.Context, keyword: str, *, message: str):
        """Add a new trigger keyword and response"""
        try:
            is_interaction = isinstance(ctx, discord.Interaction)

            if is_interaction and not ctx.response.is_done():
                await ctx.response.defer(ephemeral=True)

            if not self.triggers_db:
                await self.setup_triggers_database()

            if not self.triggers_db:
                error_msg = "<:icons_Wrong:1382701332955402341> | Database connection failed. Please try again later."
                if is_interaction:
                    await ctx.followup.send(error_msg, ephemeral=True)
                else:
                    await ctx.send(error_msg)
                return

            if len(keyword) > 50:
                error_msg = "<:icons_Wrong:1382701332955402341> | Keyword cannot exceed 50 characters."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(error_msg, ephemeral=True)
                else:
                    await ctx.send(error_msg)
                return

            if len(message) > 2000:
                error_msg = "<:icons_Wrong:1382701332955402341> | Response message cannot exceed 2000 characters."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(error_msg, ephemeral=True)
                else:
                    await ctx.send(error_msg)
                return

            keyword = keyword.lower().strip()
            invoker = ctx.author if isinstance(ctx, commands.Context) else ctx.user

            async with self.triggers_db.cursor() as cur:
                try:
                    await cur.execute(
                        "INSERT INTO triggers (guild_id, keyword, message, created_by) VALUES (?, ?, ?, ?)",
                        (ctx.guild.id, keyword, message, invoker.id)
                    )
                    await self.triggers_db.commit()

                    embed = discord.Embed(
                        title="<:j_icons_Correct:1382701297987485706> Trigger Added Successfully",
                        description=f"**Keyword:** `{keyword}`\n**Response:** {message[:100]}{'...' if len(message) > 100 else ''}",
                        color=0x00D4FF
                    )
                    embed.set_footer(text="Trigger System • Auto-Response")

                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(embed=embed, ephemeral=True)
                    else:
                        await ctx.send(embed=embed)

                except aiosqlite.IntegrityError:
                    error_msg = f"<:icons_Wrong:1382701332955402341> | A trigger for keyword `{keyword}` already exists in this server."
                    if isinstance(ctx, discord.Interaction):
                        await ctx.followup.send(error_msg, ephemeral=True)
                    else:
                        await ctx.send(error_msg)

        except Exception as e:
            logger.error(f"Error adding trigger: {e}")
            raise

    @commands.hybrid_command(name="remove-trigger", description="Remove a keyword trigger.")
    @app_commands.describe(keyword="The keyword trigger to remove")
    @commands.has_permissions(administrator=True)
    async def remove_trigger(self, ctx: commands.Context, keyword: str):
        """Remove a trigger keyword"""
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if not self.triggers_db:
                await self.setup_triggers_database()

            keyword = keyword.lower().strip()

            async with self.triggers_db.cursor() as cur:
                await cur.execute(
                    "DELETE FROM triggers WHERE guild_id = ? AND keyword = ?",
                    (ctx.guild.id, keyword)
                )

                if cur.rowcount > 0:
                    await self.triggers_db.commit()
                    success_msg = f"<:j_icons_Correct:1382701297987485706> | Trigger for keyword `{keyword}` has been removed."
                else:
                    success_msg = f"<:icons_Wrong:1382701332955402341> | No trigger found for keyword `{keyword}`."

                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(success_msg, ephemeral=True)
                else:
                    await ctx.send(success_msg)

        except Exception as e:
            logger.error(f"Error removing trigger: {e}")
            raise

    @commands.hybrid_command(name="trigger-get", description="Get details of a specific trigger.")
    @app_commands.describe(keyword="The keyword trigger to get details for")
    async def trigger_get(self, ctx: commands.Context, keyword: str):
        """Get details of a specific trigger"""
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if not self.triggers_db:
                await self.setup_triggers_database()

            keyword = keyword.lower().strip()

            async with self.triggers_db.cursor() as cur:
                await cur.execute(
                    "SELECT keyword, message, created_by FROM triggers WHERE guild_id = ? AND keyword = ?",
                    (ctx.guild.id, keyword)
                )
                trigger = await cur.fetchone()

            if not trigger:
                error_msg = f"No trigger found for keyword `{keyword}`."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(error_msg, ephemeral=True)
                else:
                    await ctx.send(error_msg)
                return

            keyword, message, created_by = trigger

            try:
                creator = await self.bot.fetch_user(created_by)
                creator_name = f"{creator.display_name} ({creator.id})"
            except:
                creator_name = f"Unknown User ({created_by})"

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(message, ephemeral=True)
            else:
                await ctx.send(message)

        except Exception as e:
            logger.error(f"Error getting trigger details: {e}")
            raise

    @commands.hybrid_command(name="list-triggers", description="List all active triggers in this server.")
    @commands.has_permissions(administrator=True)
    async def list_triggers(self, ctx: commands.Context):
        """List all triggers for the current guild"""
        try:
            if isinstance(ctx, discord.Interaction):
                await ctx.response.defer(ephemeral=True)

            if not self.triggers_db:
                await self.setup_triggers_database()

            async with self.triggers_db.cursor() as cur:
                await cur.execute(
                    "SELECT keyword, message FROM triggers WHERE guild_id = ? ORDER BY keyword",
                    (ctx.guild.id,)
                )
                triggers = await cur.fetchall()

            if not triggers:
                no_triggers_msg = "<:clipboard1:1383857546410070117> | No triggers configured for this server."
                if isinstance(ctx, discord.Interaction):
                    await ctx.followup.send(no_triggers_msg, ephemeral=True)
                else:
                    await ctx.send(no_triggers_msg)
                return

            embed = discord.Embed(
                title="<:clipboard1:1383857546410070117> Active Triggers",
                description=f"**{len(triggers)} trigger(s) configured for this server**",
                color=0x00D4FF
            )

            trigger_list = []
            for i, (keyword, message) in enumerate(triggers[:10], 1):  # Limit to 10 triggers
                preview = message[:50] + "..." if len(message) > 50 else message
                trigger_list.append(f"**{i}.** `{keyword}` → {preview}")

            embed.add_field(
                name="<:Target:1382706193855942737> Keyword Triggers",
                value="\n".join(trigger_list),
                inline=False
            )

            if len(triggers) > 10:
                embed.add_field(
                    name="<:stats_1:1382703019334045830> Additional Info",
                    value=f"... and {len(triggers) - 10} more triggers",
                    inline=False
                )

            embed.set_footer(text="Trigger System • Auto-Response Management")

            if isinstance(ctx, discord.Interaction):
                await ctx.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error listing triggers: {e}")
            raise

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for trigger keywords in messages"""
        try:
            if message.author.bot or not message.guild:
                return

            if not self.triggers_db:
                await self.setup_triggers_database()

            content = message.content.lower().strip()

            async with self.triggers_db.cursor() as cur:
                await cur.execute(
                    "SELECT keyword, message FROM triggers WHERE guild_id = ?",
                    (message.guild.id,)
                )
                triggers = await cur.fetchall()

            for keyword, response in triggers:
                if keyword in content:
                    await message.channel.send(response)
                    break  # Only respond to the first matching trigger

        except Exception as e:
            logger.error(f"Error processing trigger in message: {e}")

    async def cog_unload(self):
        """Clean up when cog is unloaded"""
        if self.triggers_db:
            await self.triggers_db.close()

async def setup(bot):
    await bot.add_cog(TriggerSystem(bot))