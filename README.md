# Telegram Claude Code Bot

A Telegram bot that acts as a bridge to [Claude Code CLI](https://claude.ai/claude-code), allowing you to interact with Claude directly from Telegram.

## Features

- **Persistent Sessions** - Conversations maintain context until you clear them
- **Image Support** - Send photos and Claude will analyze them
- **Scope Control** - Set working directory for Claude to operate in
- **Long Response Handling** - Responses exceeding Telegram's limit are sent as `.txt` files
- **User Whitelist** - Only responds to authorized users
- **Auto-start** - Can be configured to run on system startup

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Show bot info and current settings |
| `/clear` | Start fresh session |
| `/resume` | Continue last session |
| `/scope <path>` | Set working directory for Claude |
| `/send <file>` | Send a file or photo from scope to you |
| `/status` | Show current scope and session status |
| `/myid` | Get your Telegram chat ID (for error notifications) |

### Scope Presets

Use `/scope` with these presets:

- `desktop` - Desktop folder
- `documents` - Documents folder
- `downloads` - Downloads folder
- `home` - Home directory
- `here` - Bot's current directory
- `root` - Root drive (C:\ on Windows)
- `new` - Create new empty project folder on Desktop

Or specify a custom path: `/scope C:\Projects\MyApp`

## Installation

### Prerequisites

- Python 3.10+
- [Claude Code CLI](https://claude.ai/claude-code) installed and authenticated
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/tgccode.git
cd tgccode
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create `.env` file:
```bash
cp .env.example .env
```

4. Edit `.env` with your settings:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
ALLOWED_USERNAME=your_telegram_username
```

5. Run the bot:
```bash
python bot.py
```

## Auto-start on Windows

To run the bot automatically on system startup:

1. Press `Win + R`, type `shell:startup`, press Enter
2. Create a shortcut to `start_bot.vbs` in this folder
3. Or run: `python setup_autostart.py`

## Project Structure

```
tgccode/
├── bot.py              # Main bot code
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
├── .env                # Your config (not in git)
├── start_bot.vbs       # Windows startup script
├── session_data.json   # Session persistence (auto-created)
└── temp_images/        # Temporary image storage (auto-created)
```

## Security

- Bot only responds to the username specified in `ALLOWED_USERNAME`
- Never commit your `.env` file
- Bot token should be kept secret

## License

MIT
