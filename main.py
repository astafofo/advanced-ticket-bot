import discord
from discord.ext import commands
import asyncio
import logging
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from utils.config import config
from utils.db_config import db_config

load_dotenv()

logging.getLogger('discord').setLevel(logging.CRITICAL)
logging.getLogger('discord.gateway').setLevel(logging.CRITICAL)
logging.getLogger('discord.client').setLevel(logging.CRITICAL)
logging.getLogger('discord.http').setLevel(logging.CRITICAL)

logger = logging.getLogger('discord')

def print_bot_ready(bot_name):
    ascii_art = """
 ▄████▄   ▒█████  ▓█████▄ ▓█████ ▒██   ██▒
▒██▀ ▀█  ▒██▒  ██▒▒██▀ ██▌▓█   ▀ ▒▒ █ █ ▒░
▒▓█    ▄ ▒██░  ██▒░██   █▌▒███   ░░  █   ░
▒▓▓▄ ▄██▒▒██   ██░░▓█▄   ▌▒▓█  ▄  ░ █ █ ▒ 
▒ ▓███▀ ░░ ████▓▒░░▒████▓ ░▒████▒▒██▒ ▒██▒
░ ░▒ ▒  ░░ ▒░▒░▒░  ▒▒▓  ▒ ░░ ▒░ ░▒▒ ░ ░▓ ░
  ░  ▒     ░ ▒ ▒░  ░ ▒  ▒  ░ ░  ░░░   ░▒ ░
░        ░ ░ ░ ▒   ░ ░  ░    ░    ░    ░  
░ ░          ░ ░     ░       ░  ░ ░    ░  
░                  ░                     
"""
    print(ascii_art)
    print(f"\033[92mLogin successful logged in as {bot_name}\033[0m")

def print_error(message):
    print(f"\033[91m[ERROR] {message}\033[0m")

def print_loading(message):
    colors = ["\033[91m", "\033[93m", "\033[92m", "\033[96m", "\033[94m", "\033[95m"]
    color = colors[hash(message) % len(colors)]
    print(f"{color}◆ {message}...\033[0m")

def print_success(message):
    colors = ["\033[92m", "\033[96m", "\033[94m", "\033[95m"]
    color = colors[hash(message) % len(colors)]
    print(f"{color}✓ {message}\033[0m")

def print_rainbow_separator():
    rainbow = "\033[91m▆\033[93m▆\033[92m▆\033[96m▆\033[94m▆\033[95m▆\033[0m"
    print(f"  {rainbow * 12}")

def print_system_ready():
    print_rainbow_separator()
    print("\033[92m  System Operational\033[0m")
    print("\033[95m Developed By Harly Xploitz\033[0m")
    print_rainbow_separator()

class TicketBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True

        super().__init__(
            command_prefix=config.PREFIX,
            intents=intents,
            help_command=None,
            heartbeat_timeout=60.0,
            chunk_guilds_at_startup=False
        )

        self.db = None
        self.triggers_db = None
        self.active_setups = {}
        self.start_time = datetime.now()

    async def setup_database(self):
        try:
            print_loading("Initializing database")
            self.db = await aiosqlite.connect('bot.db')
            self.db.row_factory = aiosqlite.Row
            
            # Enable foreign key support for SQLite
            await self.db.execute("PRAGMA foreign_keys = ON")
            
            # Create tables
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    role_id INTEGER,
                    category_id INTEGER,
                    log_channel_id INTEGER,
                    ping_role_id INTEGER,
                    ticket_limit INTEGER DEFAULT 3,
                    panel_type TEXT DEFAULT 'dropdown',
                    embed_color INTEGER DEFAULT 53247,
                    embed_title TEXT DEFAULT 'Support Ticket System',
                    embed_description TEXT DEFAULT 'Click the button below to create a support ticket.'
                )
            """)
            
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS rate_limits (
                    user_id INTEGER PRIMARY KEY,
                    last_ticket_time REAL
                )
            """)
            
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS ticket_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    category_name TEXT,
                    UNIQUE(guild_id, category_name),
                    FOREIGN KEY (guild_id) REFERENCES tickets(guild_id) ON DELETE CASCADE
                )
            """)
            
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS ticket_instances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    channel_id INTEGER UNIQUE,
                    creator_id INTEGER,
                    category TEXT,
                    subject TEXT,
                    description TEXT,
                    priority TEXT DEFAULT 'Medium',
                    status TEXT DEFAULT 'open',
                    claimed_by INTEGER,
                    ticket_number INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP,
                    FOREIGN KEY (guild_id) REFERENCES tickets(guild_id) ON DELETE CASCADE
                )
            """)
            
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS ticket_ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    ticket_number INTEGER,
                    user_id INTEGER,
                    rating INTEGER,
                    feedback TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await self.db.commit()
            print_success("Database initialized successfully")
            
        except Exception as e:
            print_error(f"Failed to initialize database: {e}")
            await self.close()
            sys.exit(1)

    async def setup_hook(self):
        try:
            await self.setup_database()

            print_loading("Loading modules")
            extensions = ['cogs.tickets', 'cogs.help', 'cogs.triggers', 'cogs.on_mention', 'utils.error_handler']

            for extension in extensions:
                try:
                    await self.load_extension(extension)
                    print_success(f"✓ {extension} loaded")
                except Exception as e:
                    print_error(f"✗ Failed to load {extension}: {e}")
                    raise

            hybrid_commands = [cmd for cmd in self.commands if hasattr(cmd, 'app_command')]
            print_success(f"Modules loaded - {len(hybrid_commands)} hybrid commands registered")

        except Exception as e:
            print_error(f"Setup failed: {e}")
            raise


    async def on_ready(self):
        try:
            print_loading("Initializing persistent views")
            from views.panel_views import TicketPanelView
            from views.ticket_views import TicketControlView
            from utils.author_info import UserAvatarView
            from utils.rating_system import RatingView

            self.add_view(TicketControlView(self, {}))
            print_success("Views registered")

            print_loading("Syncing guild configurations")
            for guild in self.guilds:
                try:
                    from utils.database import get_ticket_categories
                    categories = await get_ticket_categories(self, guild.id)
                    if categories:
                        try:
                            if len(categories) > 0:  # Only create view if categories exist
                                panel_view = TicketPanelView(self, categories, guild.id)
                                if panel_view.children and all(hasattr(item, 'custom_id') and item.custom_id for item in panel_view.children):
                                    self.add_view(panel_view)
                        except Exception as view_error:
                            logger.warning(f"Skipping panel view for guild {guild.id}: {view_error}")

                    async with self.db.cursor() as cur:
                        await cur.execute("""
                            SELECT DISTINCT t.ticket_number, t.creator_id, t.guild_id 
                            FROM ticket_instances t
                            LEFT JOIN ticket_ratings r ON t.guild_id = r.guild_id 
                                AND t.ticket_number = r.ticket_number 
                                AND t.creator_id = r.user_id
                            WHERE t.guild_id = ? AND t.status = 'closed' AND r.rating IS NULL
                        """, (guild.id,))
                        unrated_tickets = await cur.fetchall()

                        for ticket_number, creator_id, guild_id in unrated_tickets:
                            try:
                                rating_view = RatingView(self, ticket_number, creator_id, "Support Staff", guild_id)
                                rating_view._timeout = None
                                rating_view.timeout = None
                                self.add_view(rating_view)
                                logger.info(f"Registered persistent rating view for unrated ticket #{ticket_number:04d}")
                            except Exception as rating_error:
                                logger.warning(f"Skipping rating view for ticket {ticket_number}: {rating_error}")

                except Exception as e:
                    logger.warning(f"Guild {guild.id} sync failed: {e}")
            print_success("Guild configurations synced")

            print_loading("Synchronizing slash commands")
            try:
                synced = await asyncio.wait_for(self.tree.sync(), timeout=30.0)
                print_success(f"Commands synchronized ({len(synced)} commands)")

                for cmd in synced:
                    logger.info(f"Synced command: /{cmd.name}")

            except asyncio.TimeoutError:
                print_error("Command sync timed out - bot will continue running")
            except discord.HTTPException as e:
                if "429" in str(e):
                    print_error("Rate limited during command sync - commands will sync later")
                else:
                    print_error(f"Command sync failed: {e}")
            except Exception as e:
                print_error(f"Command sync failed: {e}")

            try:
                status_type = config.BOT_STATUS_TYPE

                if status_type == 'STREAMING':
                    activity = discord.Streaming(
                        name=config.BOT_STATUS,
                        url="https://discord.gg/GQfuF4Bx8r"
                    )
                    status = discord.Status.online
                elif status_type == 'PLAYING':
                    activity = discord.Game(name=config.BOT_STATUS)
                    status = discord.Status.online
                elif status_type == 'WATCHING':
                    activity = discord.Activity(type=discord.ActivityType.watching, name=config.BOT_STATUS)
                    status = discord.Status.online
                elif status_type == 'LISTENING':
                    activity = discord.Activity(type=discord.ActivityType.listening, name=config.BOT_STATUS)
                    status = discord.Status.online
                else:
                    activity = discord.Streaming(
                        name=config.BOT_STATUS,
                        url="https://discord.gg/GQfuF4Bx8r"
                    )
                    status = discord.Status.online

                if config.BOT_STATUS_TYPE == 'IDLE':
                    status = discord.Status.idle
                elif config.BOT_STATUS_TYPE == 'DND':
                    status = discord.Status.dnd
                elif config.BOT_STATUS_TYPE == 'INVISIBLE':
                    status = discord.Status.invisible

                await self.change_presence(activity=activity, status=status)
                print_success(f"Bot status set: {config.BOT_STATUS} ({status_type})")
            except Exception as status_error:
                print_error(f"Failed to set bot status: {status_error}")

            print_bot_ready(self.user.name)
            print_system_ready()

        except Exception as e:
            print_error(f"Startup error: {e}")
            if hasattr(self, 'user') and self.user:
                print_bot_ready(self.user.name)

    async def close(self):
        print_loading("Shutting down bot")

        if hasattr(self, 'db') and self.db:
            try:
                await self.db.close()
                print_success("Main database connection closed")
            except Exception as e:
                print_error(f"Error closing main database: {e}")

        if hasattr(self, 'triggers_db') and self.triggers_db:
            try:
                await self.triggers_db.close()
                print_success("Triggers database connection closed")
            except Exception as e:
                print_error(f"Error closing triggers database: {e}")

        try:
            await super().close()
            print_success("Bot shutdown complete")
        except Exception as e:
            print_error(f"Error during bot shutdown: {e}")

bot = TicketBot()

async def shutdown_handler():
    """Handle graceful shutdown"""
    print_loading("Shutdown signal received")
    await bot.close()

if __name__ == "__main__":
    config.setup_logging()
    if not config.TOKEN:
        logger.error("No TOKEN found in environment variables")
        exit(1)

    print("Bot logging in...")

    try:
        asyncio.run(bot.start(config.TOKEN))
    except discord.LoginFailure:
        print_error("Invalid bot token. Please check your TOKEN in the .env file.")
    except KeyboardInterrupt:
        print_loading("Shutdown initiated by user")
        asyncio.run(shutdown_handler())
    except Exception as e:
        print_error(f"Bot failed to start: {e}")
    finally:
        print_success("Bot process ended")
