#!/usr/bin/env python3
"""
Telegram bot that forwards messages to Claude Code CLI and returns responses.
Only responds to messages from the configured allowed user.
"""

import os
import sys
import subprocess
import tempfile
import asyncio
import json
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERNAME = os.getenv("ALLOWED_USERNAME")
TELEGRAM_MAX_LENGTH = 4096
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")  # For error notifications

# Directory for temporary images
TEMP_DIR = Path("temp_images")
TEMP_DIR.mkdir(exist_ok=True)

# Session storage file
SESSION_FILE = Path("session_data.json")

# Default working directory
DEFAULT_SCOPE = os.getcwd()

# Scope presets
SCOPE_PRESETS = {
    "desktop": os.path.expanduser("~/Desktop"),
    "documents": os.path.expanduser("~/Documents"),
    "downloads": os.path.expanduser("~/Downloads"),
    "home": os.path.expanduser("~"),
    "here": os.getcwd(),
    "root": "C:\\" if sys.platform == "win32" else "/",
}


def load_session_data() -> dict:
    """Load session data from file."""
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text(encoding='utf-8'))
        except:
            pass
    return {"session_id": None, "scope": DEFAULT_SCOPE}


def save_session_data(data: dict) -> None:
    """Save session data to file."""
    SESSION_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def is_allowed_user(update: Update) -> bool:
    """Check if the message is from the allowed user."""
    user = update.effective_user
    if user and user.username:
        return user.username.lower() == ALLOWED_USERNAME.lower()
    return False


async def call_claude(prompt: str, image_path: str = None) -> str:
    """
    Call Claude Code CLI with the given prompt and optional image.
    Uses persistent session with --continue flag.
    Returns the response from Claude.
    """
    session_data = load_session_data()
    scope = session_data.get("scope", DEFAULT_SCOPE)
    session_id = session_data.get("session_id")

    cmd = ["claude"]

    # Continue existing session or start new one
    if session_id:
        cmd.extend(["--continue", session_id])

    # Add image if provided
    if image_path:
        cmd.extend(["--image", image_path])

    # Add prompt
    cmd.extend(["-p", prompt])

    try:
        # Run claude CLI as subprocess in the scope directory
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=scope,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")
            # If session error, try without session
            if "session" in error_msg.lower() or "continue" in error_msg.lower():
                return await call_claude_new_session(prompt, image_path, scope)
            return f"Error calling Claude: {error_msg}"

        response = stdout.decode("utf-8", errors="replace")

        # Try to extract session ID from output if new session
        # Claude typically outputs session info that we can parse
        if not session_id:
            # Save a placeholder - claude will use last session automatically
            session_data["session_id"] = "last"
            save_session_data(session_data)

        return response

    except FileNotFoundError:
        return "Error: 'claude' command not found. Make sure Claude Code CLI is installed and in PATH."
    except Exception as e:
        return f"Error: {str(e)}"


async def call_claude_new_session(prompt: str, image_path: str, scope: str) -> str:
    """Start a fresh Claude session."""
    cmd = ["claude"]

    if image_path:
        cmd.extend(["--image", image_path])

    cmd.extend(["-p", prompt])

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=scope,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")
            return f"Error: {error_msg}"

        return stdout.decode("utf-8", errors="replace")
    except Exception as e:
        return f"Error: {str(e)}"


async def send_response(update: Update, response: str) -> None:
    """
    Send response to user. If response is too long, send as .txt file.
    """
    if not response.strip():
        response = "(empty response)"

    if len(response) <= TELEGRAM_MAX_LENGTH:
        await update.message.reply_text(response)
    else:
        # Create temporary file with response
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
            encoding="utf-8"
        ) as f:
            f.write(response)
            temp_path = f.name

        try:
            with open(temp_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename="response.txt",
                    caption=f"Response was too long ({len(response)} chars), sent as file."
                )
        finally:
            os.unlink(temp_path)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages."""
    if not is_allowed_user(update):
        return

    message_text = update.message.text
    print(f"Received message: {message_text[:100]}...")

    # Show typing indicator
    await update.message.chat.send_action("typing")

    response = await call_claude(message_text)
    await send_response(update, response)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo messages."""
    if not is_allowed_user(update):
        return

    # Get the largest photo
    photo = update.message.photo[-1]
    caption = update.message.caption or "What's in this image?"

    print(f"Received photo with caption: {caption[:100]}...")

    # Download photo
    file = await context.bot.get_file(photo.file_id)
    image_path = TEMP_DIR / f"{photo.file_id}.jpg"
    await file.download_to_drive(image_path)

    try:
        # Show typing indicator
        await update.message.chat.send_action("typing")

        response = await call_claude(caption, str(image_path))
        await send_response(update, response)
    finally:
        # Clean up image file
        if image_path.exists():
            image_path.unlink()


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document/file messages (for images sent as files)."""
    if not is_allowed_user(update):
        return

    document = update.message.document

    # Check if it's an image
    if document.mime_type and document.mime_type.startswith("image/"):
        caption = update.message.caption or "What's in this image?"

        print(f"Received image document")

        # Download document
        file = await context.bot.get_file(document.file_id)
        extension = document.file_name.split(".")[-1] if document.file_name else "jpg"
        image_path = TEMP_DIR / f"{document.file_id}.{extension}"
        await file.download_to_drive(image_path)

        try:
            await update.message.chat.send_action("typing")
            response = await call_claude(caption, str(image_path))
            await send_response(update, response)
        finally:
            if image_path.exists():
                image_path.unlink()
    else:
        # Non-image document - just use caption or filename as context
        caption = update.message.caption or f"Received file: {document.file_name}"
        await update.message.chat.send_action("typing")
        response = await call_claude(caption)
        await send_response(update, response)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not is_allowed_user(update):
        await update.message.reply_text("Sorry, you are not authorized to use this bot.")
        return

    session_data = load_session_data()
    await update.message.reply_text(
        f"Connected to Claude Code.\n\n"
        f"Current scope: {session_data.get('scope', DEFAULT_SCOPE)}\n\n"
        f"Commands:\n"
        f"/clear - start fresh session\n"
        f"/resume - continue last session\n"
        f"/scope <path> - set working directory\n"
        f"/send <file> - send file/photo to you\n"
        f"/status - show current settings\n"
        f"/myid - get your chat ID"
    )


async def clear_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear command - reset the session."""
    if not is_allowed_user(update):
        return

    session_data = load_session_data()
    session_data["session_id"] = None
    save_session_data(session_data)

    await update.message.reply_text("Session cleared. Next message will start a fresh conversation.")


async def set_scope(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /scope command - set working directory."""
    if not is_allowed_user(update):
        return

    if not context.args:
        session_data = load_session_data()
        presets_list = "\n".join([f"  {k} -> {v}" for k, v in SCOPE_PRESETS.items()])
        await update.message.reply_text(
            f"Current scope: {session_data.get('scope', DEFAULT_SCOPE)}\n\n"
            f"Usage: /scope <path or preset>\n\n"
            f"Presets:\n{presets_list}\n"
            f"  new -> create new empty folder on Desktop"
        )
        return

    arg = " ".join(context.args)

    # Check for "new" preset - create new folder
    if arg.lower() == "new":
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        new_folder = os.path.join(SCOPE_PRESETS["desktop"], f"claude_project_{timestamp}")
        os.makedirs(new_folder, exist_ok=True)
        new_scope = new_folder
    # Check if it's a preset
    elif arg.lower() in SCOPE_PRESETS:
        new_scope = SCOPE_PRESETS[arg.lower()]
    else:
        # Treat as path
        new_scope = os.path.expanduser(arg)

    if not os.path.isdir(new_scope):
        await update.message.reply_text(f"Error: '{new_scope}' is not a valid directory.")
        return

    session_data = load_session_data()
    session_data["scope"] = new_scope
    session_data["session_id"] = None  # Reset session when changing scope
    save_session_data(session_data)

    await update.message.reply_text(f"Scope set to: {new_scope}\nSession reset for new scope.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command - show current settings."""
    if not is_allowed_user(update):
        return

    session_data = load_session_data()
    has_session = session_data.get("session_id") is not None

    await update.message.reply_text(
        f"Status:\n"
        f"- Scope: {session_data.get('scope', DEFAULT_SCOPE)}\n"
        f"- Session: {'active' if has_session else 'none'}"
    )


async def resume_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resume command - continue last session or specific session."""
    if not is_allowed_user(update):
        return

    session_data = load_session_data()

    if context.args:
        # Resume specific session
        session_id = context.args[0]
        session_data["session_id"] = session_id
        save_session_data(session_data)
        await update.message.reply_text(f"Resuming session: {session_id}")
    else:
        # Resume last session
        session_data["session_id"] = "last"
        save_session_data(session_data)
        await update.message.reply_text("Resuming last session. Use /clear to start fresh.")


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /myid command - show user's chat ID."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username

    await update.message.reply_text(
        f"Your info:\n"
        f"- Chat ID: {chat_id}\n"
        f"- User ID: {user_id}\n"
        f"- Username: @{username}\n\n"
        f"Add this to .env for error notifications:\n"
        f"OWNER_CHAT_ID={chat_id}"
    )


async def send_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /send command - send a file to user."""
    if not is_allowed_user(update):
        return

    if not context.args:
        await update.message.reply_text("Usage: /send <file_path>\n\nExample: /send C:\\Users\\file.txt")
        return

    file_path = " ".join(context.args)
    session_data = load_session_data()
    scope = session_data.get("scope", DEFAULT_SCOPE)

    # If path is relative, make it relative to scope
    if not os.path.isabs(file_path):
        file_path = os.path.join(scope, file_path)

    if not os.path.exists(file_path):
        await update.message.reply_text(f"File not found: {file_path}")
        return

    if not os.path.isfile(file_path):
        await update.message.reply_text(f"Not a file: {file_path}")
        return

    try:
        file_size = os.path.getsize(file_path)
        # Telegram limit is 50MB for bots
        if file_size > 50 * 1024 * 1024:
            await update.message.reply_text(f"File too large ({file_size // (1024*1024)}MB). Telegram limit is 50MB.")
            return

        file_name = os.path.basename(file_path)
        mime_type = None

        # Detect if it's an image
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
        ext = os.path.splitext(file_name)[1].lower()

        with open(file_path, "rb") as f:
            if ext in image_extensions:
                await update.message.reply_photo(photo=f, caption=file_name)
            else:
                await update.message.reply_document(document=f, filename=file_name)

        await update.message.reply_text(f"Sent: {file_name}")

    except Exception as e:
        await update.message.reply_text(f"Error sending file: {str(e)}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send error notifications to owner via bot."""
    import traceback

    error_msg = f"Error: {context.error}\n\n"
    error_msg += "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))

    print(f"Error occurred: {context.error}")

    # Try to send error to owner
    if OWNER_CHAT_ID:
        try:
            # Truncate if too long
            if len(error_msg) > TELEGRAM_MAX_LENGTH:
                error_msg = error_msg[:TELEGRAM_MAX_LENGTH - 100] + "\n\n... (truncated)"
            await context.bot.send_message(chat_id=OWNER_CHAT_ID, text=f"Bot Error:\n{error_msg}")
        except Exception as e:
            print(f"Failed to send error notification: {e}")


def main():
    """Run the bot."""
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set in .env file")
        print("1. Get a token from @BotFather on Telegram")
        print("2. Create .env file with: TELEGRAM_BOT_TOKEN=your_token")
        return

    print(f"Starting bot... Only responding to @{ALLOWED_USERNAME}")
    print(f"Default scope: {DEFAULT_SCOPE}")
    print("Press Ctrl+C to stop")

    # Create application
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_session))
    app.add_handler(CommandHandler("resume", resume_session))
    app.add_handler(CommandHandler("scope", set_scope))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("send", send_file))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Add error handler
    app.add_error_handler(error_handler)

    # Run the bot (drop pending updates to avoid conflicts)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
