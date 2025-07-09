import logging
import aiosqlite
from typing import Optional, List, Tuple
import discord

logger = logging.getLogger('discord')

async def check_database_connection(bot) -> bool:
    try:
        if not hasattr(bot, 'db') or bot.db is None:
            logger.error("Bot database object is None")
            return False

        async with bot.db.cursor() as cur:
            await cur.execute("SELECT 1")
            await cur.fetchone()
            return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False

async def ensure_database_connection(bot):
    """Ensure database connection is valid, attempt reconnection if needed"""
    if not await check_database_connection(bot):
        try:
            import aiosqlite
            if hasattr(bot, 'db') and bot.db:
                await bot.db.close()
            bot.db = await aiosqlite.connect('bot.db')
            logger.info("Database reconnected successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to reconnect to database: {e}")
            return False
    return True

async def get_ticket_channel(bot, guild_id: int) -> Optional[discord.TextChannel]:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT channel_id FROM tickets WHERE guild_id = ?", (guild_id,))
            result = await cur.fetchone()
            if result and result[0]:
                guild = bot.get_guild(guild_id)
                return guild.get_channel(result[0]) if guild else None
    except Exception as e:
        logger.error(f"Error getting ticket channel: {e}")
        return None

async def get_ticket_role(bot, guild_id: int) -> Optional[discord.Role]:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT role_id FROM tickets WHERE guild_id = ?", (guild_id,))
            result = await cur.fetchone()
            if result and result[0]:
                guild = bot.get_guild(guild_id)
                return guild.get_role(result[0]) if guild else None
    except Exception as e:
        logger.error(f"Error getting ticket role: {e}")
        return None

async def get_ticket_category(bot, guild_id: int) -> Optional[discord.CategoryChannel]:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT category_id FROM tickets WHERE guild_id = ?", (guild_id,))
            result = await cur.fetchone()
            if result and result[0]:
                guild = bot.get_guild(guild_id)
                return guild.get_channel(result[0]) if guild else None
    except Exception as e:
        logger.error(f"Error getting ticket category: {e}")
        return None

async def get_ticket_log_channel(bot, guild_id: int) -> Optional[discord.TextChannel]:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT log_channel_id FROM tickets WHERE guild_id = ?", (guild_id,))
            result = await cur.fetchone()
            if result and result[0]:
                guild = bot.get_guild(guild_id)
                return guild.get_channel(result[0]) if guild else None
    except Exception as e:
        logger.error(f"Error getting ticket log channel: {e}")
        return None

async def get_ping_role(bot, guild_id: int) -> Optional[discord.Role]:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT ping_role_id FROM tickets WHERE guild_id = ?", (guild_id,))
            result = await cur.fetchone()
            if result and result[0]:
                guild = bot.get_guild(guild_id)
                return guild.get_role(result[0]) if guild else None
    except Exception as e:
        logger.error(f"Error getting ping role: {e}")
        return None

async def get_ticket_categories(bot, guild_id: int) -> List[Tuple[str, str]]:
    try:
        if not bot.db:
            return []
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT category_name, emoji FROM ticket_categories WHERE guild_id = ? ORDER BY category_name", (guild_id,))
            results = await cur.fetchall()
            return [(row[0], row[1]) for row in results]
    except Exception as e:
        logger.error(f"Error getting ticket categories: {e}")
        return []

async def get_ticket_categories_with_emojis(bot, guild_id: int) -> List[Tuple[str, str]]:
    try:
        if not bot.db:
            return []
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT category_name, emoji FROM ticket_categories WHERE guild_id = ? ORDER BY category_name", (guild_id,))
            results = await cur.fetchall()
            return [(row[0], row[1]) for row in results]
    except Exception as e:
        logger.error(f"Error getting ticket categories with emojis: {e}")
        return []

async def add_ticket_category(bot, guild_id: int, category_name: str, emoji: str = None) -> Tuple[bool, str]:
    try:
        async with bot.db.cursor() as cur:
            try:
                await cur.execute("ALTER TABLE ticket_categories ADD COLUMN emoji TEXT")
                await bot.db.commit()
            except:
                pass  # Column already exists

            await cur.execute("SELECT 1 FROM ticket_categories WHERE guild_id = ? AND category_name = ?", (guild_id, category_name))
            if await cur.fetchone():
                return False, f"Category '{category_name}' already exists."

            await cur.execute("SELECT COUNT(*) FROM ticket_categories WHERE guild_id = ?", (guild_id,))
            count = (await cur.fetchone())[0]
            if count >= 25:
                return False, "Maximum of 25 categories allowed per server."

            await cur.execute(
                "INSERT INTO ticket_categories (guild_id, category_name, emoji) VALUES (?, ?, ?)",
                (guild_id, category_name, emoji)
            )
            await bot.db.commit()

            emoji_display = f" with emoji {emoji}" if emoji else ""
            return True, f"Category '{category_name}'{emoji_display} has been added successfully."
    except Exception as e:
        logger.error(f"Error adding ticket category: {e}")
        return False, f"Database error: {str(e)}"

async def remove_ticket_category(bot, guild_id: int, category_name: str) -> Tuple[bool, str]:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute(
                "DELETE FROM ticket_categories WHERE guild_id = ? AND category_name = ?",
                (guild_id, category_name)
            )
            if cur.rowcount == 0:
                return False, f"Category '{category_name}' not found."

            await bot.db.commit()
            return True, f"Category '{category_name}' has been removed successfully."
    except Exception as e:
        logger.error(f"Error removing ticket category: {e}")
        return False, f"Database error: {str(e)}"

async def reset_ticket_categories(bot, guild_id: int) -> Tuple[bool, str]:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("DELETE FROM ticket_categories WHERE guild_id = ?", (guild_id,))
            count = cur.rowcount
            await bot.db.commit()

            if count == 0:
                return False, "No categories found to reset."

            return True, f"All {count} categories have been reset successfully."
    except Exception as e:
        logger.error(f"Error resetting ticket categories: {e}")
        return False, f"Database error: {str(e)}"

async def user_has_support_role(bot, user: discord.Member) -> bool:
    try:
        if not user or not user.guild:
            return False

        if user.guild_permissions.administrator:
            return True

        async with bot.db.cursor() as cur:
            await cur.execute("SELECT role_id FROM tickets WHERE guild_id = ?", (user.guild.id,))
            result = await cur.fetchone()

            if result and result[0]:
                primary_support_role = user.guild.get_role(result[0])
                if primary_support_role and primary_support_role in user.roles:
                    return True

            await cur.execute("SELECT role_id FROM additional_support_roles WHERE guild_id = ?", (user.guild.id,))
            additional_roles = await cur.fetchall()

            for role_row in additional_roles:
                role_id = role_row[0]
                additional_role = user.guild.get_role(role_id)
                if additional_role and additional_role in user.roles:
                    return True

            return False
    except Exception as e:
        logger.error(f"Error checking support roles for user {user.id} in guild {user.guild.id}: {e}")
        return False

async def user_has_any_support_role(bot, user):
    """Check if user has any support role (primary or additional)"""
    try:
        if not user or not hasattr(user, 'guild'):
            return False

        async with bot.db.cursor() as cur:
            await cur.execute("SELECT role_id FROM tickets WHERE guild_id = ?", (user.guild.id,))
            result = await cur.fetchone()

            if result and result[0]:
                primary_support_role = user.guild.get_role(result[0])
                if primary_support_role and primary_support_role in user.roles:
                    return True

            await cur.execute("SELECT role_id FROM additional_support_roles WHERE guild_id = ?", (user.guild.id,))
            additional_roles = await cur.fetchall()

            for role_row in additional_roles:
                additional_role = user.guild.get_role(role_row[0])
                if additional_role and additional_role in user.roles:
                    return True

            return False
    except Exception as e:
        logger.error(f"Error checking support roles: {e}")
        return False

async def add_support_role(bot, guild_id: int, role_id: int):
    """Add an additional support role"""
    try:
        async with bot.db.cursor() as cur:
            await cur.execute(
                "INSERT OR IGNORE INTO additional_support_roles (guild_id, role_id) VALUES (?, ?)",
                (guild_id, role_id)
            )
            await bot.db.commit()
            return True, "Support role added successfully."
    except Exception as e:
        logger.error(f"Error adding support role: {e}")
        return False, f"Failed to add support role: {str(e)}"

async def remove_support_role(bot, guild_id: int, role_id: int):
    """Remove an additional support role"""
    try:
        async with bot.db.cursor() as cur:
            await cur.execute(
                "DELETE FROM additional_support_roles WHERE guild_id = ? AND role_id = ?",
                (guild_id, role_id)
            )

            if cur.rowcount == 0:
                return False, "Role was not found in additional support roles."

            await bot.db.commit()
            return True, "Support role removed successfully."
    except Exception as e:
        logger.error(f"Error removing support role: {e}")
        return False, f"Failed to remove support role: {str(e)}"

async def get_additional_support_roles(bot, guild_id: int):
    """Get all additional support roles for a guild"""
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT role_id FROM additional_support_roles WHERE guild_id = ?", (guild_id,))
            results = await cur.fetchall()
            return [row[0] for row in results]
    except Exception as e:
        logger.error(f"Error getting additional support roles: {e}")
        return []

async def get_user_open_tickets(bot, guild_id: int, user_id: int) -> int:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("""
                SELECT COUNT(*) FROM ticket_instances 
                WHERE guild_id = ? AND creator_id = ? AND status = 'open'
            """, (guild_id, user_id))
            result = await cur.fetchone()
            return result[0] if result else 0
    except Exception as e:
        logger.error(f"Error getting user open tickets: {e}")
        return 0

async def check_user_ticket_limit(bot, guild_id: int, user_id: int) -> Tuple[bool, int, int]:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT ticket_limit FROM tickets WHERE guild_id = ?", (guild_id,))
            result = await cur.fetchone()
            limit = result[0] if result else 3

            await cur.execute(
                "SELECT COUNT(*) FROM ticket_instances WHERE guild_id = ? AND creator_id = ? AND status = 'open'",
                (guild_id, user_id)
            )
            count = (await cur.fetchone())[0]

            can_create = count < limit
            return can_create, count, limit
    except Exception as e:
        logger.error(f"Error checking user ticket limit: {e}")
        return True, 0, 3

async def get_user_safe_mention(bot, user_id: int, guild_id: int = None) -> str:
    try:
        if guild_id:
            guild = bot.get_guild(guild_id)
            if guild:
                member = guild.get_member(user_id)
                if member:
                    return member.mention

        user = bot.get_user(user_id)
        if user:
            return user.mention

        return f"<@{user_id}>"
    except Exception as e:
        logger.error(f"Error getting user mention for {user_id}: {e}")
        return f"<@{user_id}>"

async def get_user_safe_display_name(bot, user_id: int, guild_id: int = None) -> str:
    try:
        if guild_id:
            guild = bot.get_guild(guild_id)
            if guild:
                member = guild.get_member(user_id)
                if member:
                    return member.display_name

        user = bot.get_user(user_id)
        if user:
            return user.display_name

        return "Unknown User"
    except Exception as e:
        logger.error(f"Error getting user display name for {user_id}: {e}")
        return "Unknown User"

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

async def add_or_update_ticket_config(bot, guild_id: int, **kwargs) -> bool:
    try:
        if 'embed_color' in kwargs:
            kwargs['embed_color'] = convert_color_to_int(kwargs['embed_color'])

        async with bot.db.cursor() as cur:
            await cur.execute("SELECT 1 FROM tickets WHERE guild_id = ?", (guild_id,))
            exists = await cur.fetchone() is not None

            if exists:
                set_clauses = []
                values = []
                for key, value in kwargs.items():
                    set_clauses.append(f"{key} = ?")
                    values.append(value)
                values.append(guild_id)

                query = f"UPDATE tickets SET {', '.join(set_clauses)} WHERE guild_id = ?"
                await cur.execute(query, values)
            else:
                keys = ['guild_id'] + list(kwargs.keys())
                placeholders = ', '.join(['?'] * len(keys))
                values = [guild_id] + list(kwargs.values())

                query = f"INSERT INTO tickets ({', '.join(keys)}) VALUES ({placeholders})"
                await cur.execute(query, values)

            await bot.db.commit()
            return True
    except Exception as e:
        logger.error(f"Error updating ticket config: {e}")
        return False

async def get_ticket_limit(bot, guild_id: int) -> int:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute("SELECT ticket_limit FROM tickets WHERE guild_id = ?", (guild_id,))
            result = await cur.fetchone()
            return result[0] if result and result[0] else 3
    except Exception as e:
        logger.error(f"Error getting ticket limit: {e}")
        return 3

async def update_ticket_priority(bot, channel_id: int, priority: str) -> bool:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute(
                "UPDATE ticket_instances SET priority = ? WHERE channel_id = ?",
                (priority, channel_id)
            )
            await bot.db.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating ticket priority: {e}")
        return False

async def is_user_blacklisted(bot, guild_id: int, user_id: int) -> bool:
    try:
        async with bot.db.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM ticket_blacklist WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)
            )
            return await cur.fetchone() is not None
    except Exception as e:
        logger.error(f"Error checking user blacklist status: {e}")
        return False

async def migrate_database(bot):
    try:
        async with bot.db.cursor() as cur:
            migrations = [
                "ALTER TABLE tickets ADD COLUMN embed_footer TEXT DEFAULT 'Powered by Harly Xploitz™'",
                "ALTER TABLE tickets ADD COLUMN embed_image_url TEXT",
                "ALTER TABLE tickets ADD COLUMN maintenance_mode BOOLEAN DEFAULT 0",
                "ALTER TABLE tickets ADD COLUMN panel_type TEXT DEFAULT 'dropdown'",
                "ALTER TABLE tickets ADD COLUMN ticket_limit INTEGER DEFAULT 3",
                "ALTER TABLE ticket_instances ADD COLUMN subject TEXT",
                "ALTER TABLE ticket_instances ADD COLUMN description TEXT",
                "ALTER TABLE ticket_instances ADD COLUMN claimed_by INTEGER"
            ]

            for migration in migrations:
                try:
                    await cur.execute(migration)
                except:
                    pass

            try:
                await cur.execute("ALTER TABLE ticket_categories ADD COLUMN emoji TEXT")
            except:
                pass

            try:
                await cur.execute("CREATE TABLE IF NOT EXISTS additional_support_roles (guild_id INTEGER, role_id INTEGER)")
            except:
                pass

            await bot.db.commit()
            logger.info("Database migration completed")
    except Exception as e:
        logger.error(f"Error during database migration: {e}")