
# Discord Ticket Bot

A comprehensive Discord bot for managing support tickets with advanced features like categorization, rating system, and automated responses.

## Features

- 🎫 **Ticket Management** - Create, claim, transfer, and close tickets
- 📊 **Priority System** - Set ticket priorities (low/medium/high/critical)
- ⭐ **Rating System** - Users can rate their support experience
- 🏷️ **Categories** - Organize tickets by different support categories
- 🤖 **Auto Triggers** - Keyword-based automatic responses
- 📈 **Statistics** - Server and bot performance metrics
- 🎨 **Customizable Panels** - Dropdown or button-based ticket creation

## Setup Guide

### 1. Bot Creation & Permissions

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application and bot
3. Copy the bot token for the `.env` file
4. Invite the bot with these permissions:
   - `Administrator` (recommended) or:
   - `Manage Channels`
   - `Manage Messages` 
   - `Send Messages`
   - `View Channels`
   - `Read Message History`
   - `Add Reactions`
   - `Use Slash Commands`

### 2. Environment Configuration

Create a `.env` file in your project root with the following variables:

```env
# Required - Your Discord bot token
TOKEN=your_bot_token_here

# Optional - Bot configuration
PREFIX=!
BOT_STATUS=!help | /help 
BOT_STATUS_TYPE=STREAMING

# Optional - Support server link
SUPPORT_SERVER=https://discord.gg/GQfuF4Bx8r

```

### 3. Configuration Details

#### Required Variables

- **`TOKEN`** - Your Discord bot token from the Developer Portal

#### Optional Variables

- **`PREFIX`** - Command prefix for legacy commands (default: `!`)
- **`BOT_STATUS`** - Status message displayed by the bot (default: `!help | /help `)
- **`BOT_STATUS_TYPE`** - Type of status activity:
  - `STREAMING` - Shows as streaming (default)
  - `PLAYING` - Shows as playing a game
  - `WATCHING` - Shows as watching something
  - `LISTENING` - Shows as listening to something
  - `IDLE` - Shows bot as idle
  - `DND` - Shows bot as do not disturb
  - `INVISIBLE` - Shows bot as offline
- **`SUPPORT_SERVER`** - Your support server invite link (default: Harly Xploitz server)

### 4. Running the Bot

#### On Replit 

1. Fork this repl or create a new Python repl
2. Upload/paste all bot files
3. Add your environment variables in the Secrets tab:
   - Key: `TOKEN`, Value: `your_bot_token_here`
   - Add any other optional variables as needed
4. Click the "Run" button

#### Local Development

1. Install Python 3.11+
2. Install dependencies: `pip install -r requirements.txt`
3. Create your `.env` file with the configuration above
4. Run: `python main.py`

### 5. Initial Bot Setup

Once the bot is online in your Discord server:

1. Use `/setup-tickets` to configure the ticket system
2. Follow the setup wizard to:
   - Set support staff role
   - Configure ticket categories
   - Set up logging channels
   - Configure rate limiting
3. Use `/send-panel dropdown` or `/send-panel button` to deploy ticket creation panels

### 6. Available Commands

#### Admin Commands
- `/setup-tickets` - Complete system setup wizard
- `/add-category <name>` - Add new ticket category
- `/remove-category <name>` - Remove ticket category
- `/list-categories` - View all categories
- `/send-panel <type>` - Deploy ticket panels
- `/reset-categories` - Reset to default categories

#### Ticket Management
- `/close-ticket` - Close current ticket with transcript
- `/claim-ticket` - Claim ticket for support
- `/transfer-ticket @user` - Transfer ticket to another staff member
- `/priority <level>` - Set ticket priority

#### Trigger System
- `/add-trigger <keyword> <message>` - Create auto-response trigger
- `/remove-trigger <keyword>` - Remove trigger
- `/list-triggers` - View all triggers
- `/trigger-get <keyword>` - View trigger response

#### General Commands
- `/help` - Display help menu
- `/stats` - Server statistics
- `/ping` - Check bot latency
- `/botinfo` - Bot information
- `/faq` - Frequently asked questions

### 7. Database

The bot uses SQLite for data storage. The database file (`bot.db` by default) contains:
- Ticket configurations per server
- Active and closed tickets
- User ratings and feedback
- Trigger keywords and responses
- Rate limiting data

### 8. Support & Development

- **Support Server**: [Discord](https://discord.gg/E5fywzRPy3)
- **Developer**: [Harly](https://discord.com/users/927023306769588264)
- **Issues**: Create tickets in our support server for bug reports and feature requests
- **Documentation**: Full documentation available in our support server
- **Community**: Join our Discord for updates, tips, and community discussions

### 9. Deployment

#### Replit Deployment (Recommended)

1. Ensure your bot runs correctly in development
2. Add environment variables to Replit Secrets
3. Your bot will automatically stay online with Replit's hosting

#### Keep Alive

The bot includes automatic reconnection handling and will restart if it encounters errors. Monitor the console for any issues.

---


*Join our community for premium Discord solutions and expert support!*
