import os
from dotenv import load_dotenv
import logging

load_dotenv()

class Config:

    TOKEN = os.getenv('TOKEN')
    PREFIX = os.getenv('PREFIX', '!')
    BOT_STATUS = os.getenv('BOT_STATUS', '!help | /help | Harly Xploitz')
    BOT_STATUS_TYPE = os.getenv('BOT_STATUS_TYPE', 'STREAMING').upper()

    DATABASE_PATH = os.getenv('DATABASE_PATH', 'bot.db')

    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

    SUPPORT_SERVER = os.getenv('SUPPORT_SERVER', 'https://discord.gg/GQfuF4Bx8r')

    DEV_MODE = os.getenv('DEV_MODE', 'False').lower() == 'true'

    @classmethod
    def setup_logging(cls):
        logging.basicConfig(
            level=getattr(logging, cls.LOG_LEVEL),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('bot.log'),
                logging.StreamHandler()
            ]
        )

config = Config()