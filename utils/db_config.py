import os
import aiosqlite
import asyncpg
from typing import Union, Optional
import logging

logger = logging.getLogger('discord')

class DatabaseConfig:
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL')
        self.is_production = bool(self.database_url and self.database_url.startswith('postgres'))

    async def get_connection(self):
        if self.is_production:
            # Parse the DATABASE_URL format: postgresql://user:password@host:port/database
            import re
            match = re.match(r'postgres(?:ql)?://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', self.database_url)
            if not match:
                raise ValueError("Invalid DATABASE_URL format")
                
            user, password, host, port, database = match.groups()
            
            return await asyncpg.create_pool(
                user=user,
                password=password,
                host=host,
                port=int(port),
                database=database,
                min_size=1,
                max_size=10
            )
        else:
            # SQLite for local development
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'bot.db')
            return await aiosqlite.connect(db_path)

    async def execute_query(self, query: str, *args, fetch: bool = False):
        if self.is_production:
            conn = await asyncpg.connect(self.database_url)
            try:
                if fetch:
                    result = await conn.fetch(query, *args)
                    return [dict(row) for row in result]
                else:
                    await conn.execute(query, *args)
            finally:
                await conn.close()
        else:
            conn = await self.get_connection()
            try:
                if fetch:
                    cursor = await conn.execute(query, args)
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
                else:
                    await conn.execute(query, args)
                    await conn.commit()
            finally:
                await conn.close()

db_config = DatabaseConfig()
