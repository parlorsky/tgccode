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
import datetime
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERNAME = os.getenv("ALLOWED_USERNAME")
TELEGRAM_MAX_LENGTH = 4096
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")

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
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text(encoding='utf-8'))
        except:
            pass
    return {"session_id": None, "scope": DEFAULT_SCOPE}


def save_session_data(data: dict) -> None:
    SESSION_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def is_allowed_user(update: Update) -> bool:
    user = update.effective_user
    if user and user.username:
        return user.username.lower() == ALLOWED_USERNAME.lower()
    return False


def get_main_keyboard():
    """Main menu keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("📁 Scope", callback_data="menu_scope"),
            InlineKeyboardButton("🔄 Session", callback_data="menu_session"),
        ],
        [
            InlineKeyboardButton("📊 Status", callback_data="action_status"),
            InlineKeyboardButton("🆔 My ID", callback_data="action_myid"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_scope_keyboard():
    """Scope presets keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("🖥 Desktop", callback_data="scope_desktop"),
            InlineKeyboardButton("📄 Documents", callback_data="scope_documents"),
        ],
        [
            InlineKeyboardButton("📥 Downloads", callback_data="scope_downloads"),
            InlineKeyboardButton("🏠 Home", callback_data="scope_home"),
        ],
        [
            InlineKeyboardButton("📍 Here", callback_data="scope_here"),
            InlineKeyboardButton("💽 Root", callback_data="scope_root"),
        ],
        [
            InlineKeyboardButton("🆕 New Project", callback_data="scope_new"),
        ],
        [
            InlineKeyboardButton("« Back", callback_data="menu_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_session_keyboard():
    """Session control keyboard."""
    keyboard = [
        [
            InlineKeyboardButton("🆕 New Session", callback_data="session_clear"),
            InlineKeyboardButton("▶️ Resume Last", callback_data="session_resume"),
        ],
        [
            InlineKeyboardButton("« Back", callback_data="menu_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def call_claude(prompt: str, image_path: str = None) -> str:
    session_data = load_session_data()
    scope = session_data.get("scope", DEFAULT_SCOPE)
    session_id = session_data.get("session_id")

    cmd = ["claude"]

    if session_id:
        cmd.extend(["--continue", session_id])

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
            if "session" in error_msg.lower() or "continue" in error_msg.lower():
                return await call_claude_new_session(prompt, image_path, scope)
            return f"Error calling Claude: {error_msg}"

        response = stdout.decode("utf-8", errors="replace")

        if not session_id:
            session_data["session_id"] = "last"
            save_session_data(session_data)

        return response

    except FileNotFoundError:
        return "Error: 'claude' command not found. Make sure Claude Code CLI is installed and in PATH."
    except Exception as e:
        return f"Error: {str(e)}"


async def call_claude_new_session(prompt: str, image_path: str, scope: str) -> str:
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
    if not response.strip():
        response = "(empty response)"

    if len(response) <= TELEGRAM_MAX_LENGTH:
        await update.message.reply_text(response)
    else:
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
    if not is_allowed_user(update):
        return

    message_text = update.message.text
    print(f"Received message: {message_text[:100]}...")

    await update.message.chat.send_action("typing")

    response = await call_claude(message_text)
    await send_response(update, response)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        return

    photo = update.message.photo[-1]
    caption = update.message.caption or "What's in this image?"

    print(f"Received photo with caption: {caption[:100]}...")

    file = await context.bot.get_file(photo.file_id)
    image_path = TEMP_DIR / f"{photo.file_id}.jpg"
    await file.download_to_drive(image_path)

    try:
        await update.message.chat.send_action("typing")
        response = await call_claude(caption, str(image_path))
        await send_response(update, response)
    finally:
        if image_path.exists():
            image_path.unlink()


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        return

    document = update.message.document

    if document.mime_type and document.mime_type.startswith("image/"):
        caption = update.message.caption or "What's in this image?"
        print(f"Received image document")

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
        caption = update.message.caption or f"Received file: {document.file_name}"
        await update.message.chat.send_action("typing")
        response = await call_claude(caption)
        await send_response(update, response)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_user(update):
        await update.message.reply_text("Sorry, you are not authorized to use this bot.")
        return

    session_data = load_session_data()
    scope = session_data.get('scope', DEFAULT_SCOPE)
    has_session = session_data.get("session_id") is not None

    await update.message.reply_text(
        f"🤖 *Claude Code Bot*\n\n"
        f"📁 Scope: `{scope}`\n"
        f"💬 Session: {'active' if has_session else 'none'}\n\n"
        f"Send any message to chat with Claude.\n"
        f"Use /send <file> to get files.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all button callbacks."""
    query = update.callback_query

    if not is_allowed_user(update):
        await query.answer("Not authorized")
        return

    await query.answer()
    data = query.data

    # Menu navigation
    if data == "menu_main":
        session_data = load_session_data()
        scope = session_data.get('scope', DEFAULT_SCOPE)
        has_session = session_data.get("session_id") is not None

        await query.edit_message_text(
            f"🤖 *Claude Code Bot*\n\n"
            f"📁 Scope: `{scope}`\n"
            f"💬 Session: {'active' if has_session else 'none'}\n\n"
            f"Send any message to chat with Claude.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

    elif data == "menu_scope":
        session_data = load_session_data()
        scope = session_data.get('scope', DEFAULT_SCOPE)

        await query.edit_message_text(
            f"📁 *Select Scope*\n\n"
            f"Current: `{scope}`\n\n"
            f"Choose a preset or use /scope <path>",
            parse_mode="Markdown",
            reply_markup=get_scope_keyboard()
        )

    elif data == "menu_session":
        session_data = load_session_data()
        has_session = session_data.get("session_id") is not None

        await query.edit_message_text(
            f"🔄 *Session Control*\n\n"
            f"Status: {'active' if has_session else 'none'}\n\n"
            f"• *New Session* - start fresh\n"
            f"• *Resume Last* - continue previous",
            parse_mode="Markdown",
            reply_markup=get_session_keyboard()
        )

    # Scope actions
    elif data.startswith("scope_"):
        preset = data.replace("scope_", "")
        session_data = load_session_data()

        if preset == "new":
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            new_scope = os.path.join(SCOPE_PRESETS["desktop"], f"claude_project_{timestamp}")
            os.makedirs(new_scope, exist_ok=True)
        else:
            new_scope = SCOPE_PRESETS.get(preset, DEFAULT_SCOPE)

        if os.path.isdir(new_scope):
            session_data["scope"] = new_scope
            session_data["session_id"] = None
            save_session_data(session_data)

            await query.edit_message_text(
                f"✅ *Scope Updated*\n\n"
                f"📁 `{new_scope}`\n\n"
                f"Session reset for new scope.",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
        else:
            await query.edit_message_text(
                f"❌ Directory not found: {new_scope}",
                reply_markup=get_scope_keyboard()
            )

    # Session actions
    elif data == "session_clear":
        session_data = load_session_data()
        session_data["session_id"] = None
        save_session_data(session_data)

        await query.edit_message_text(
            f"✅ *Session Cleared*\n\n"
            f"Next message will start a fresh conversation.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

    elif data == "session_resume":
        session_data = load_session_data()
        session_data["session_id"] = "last"
        save_session_data(session_data)

        await query.edit_message_text(
            f"✅ *Session Resumed*\n\n"
            f"Continuing last conversation.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

    # Actions
    elif data == "action_status":
        session_data = load_session_data()
        scope = session_data.get('scope', DEFAULT_SCOPE)
        has_session = session_data.get("session_id") is not None

        await query.edit_message_text(
            f"📊 *Status*\n\n"
            f"📁 Scope: `{scope}`\n"
            f"💬 Session: {'active' if has_session else 'none'}",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

    elif data == "action_myid":
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        username = update.effective_user.username

        await query.edit_message_text(
            f"🆔 *Your Info*\n\n"
            f"Chat ID: `{chat_id}`\n"
            f"User ID: `{user_id}`\n"
            f"Username: @{username}\n\n"
            f"Add to .env:\n"
            f"`OWNER_CHAT_ID={chat_id}`",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )


async def send_file_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /send command - send a file to user."""
    if not is_allowed_user(update):
        return

    if not context.args:
        await update.message.reply_text("Usage: /send <file_path>\n\nExample: /send file.txt")
        return

    file_path = " ".join(context.args)
    session_data = load_session_data()
    scope = session_data.get("scope", DEFAULT_SCOPE)

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
        if file_size > 50 * 1024 * 1024:
            await update.message.reply_text(f"File too large ({file_size // (1024*1024)}MB). Telegram limit is 50MB.")
            return

        file_name = os.path.basename(file_path)
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
        ext = os.path.splitext(file_name)[1].lower()

        with open(file_path, "rb") as f:
            if ext in image_extensions:
                await update.message.reply_photo(photo=f, caption=file_name)
            else:
                await update.message.reply_document(document=f, filename=file_name)

    except Exception as e:
        await update.message.reply_text(f"Error sending file: {str(e)}")


async def scope_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /scope command with path argument."""
    if not is_allowed_user(update):
        return

    if not context.args:
        session_data = load_session_data()
        await update.message.reply_text(
            f"📁 Current scope: {session_data.get('scope', DEFAULT_SCOPE)}\n\n"
            f"Use buttons or /scope <path>",
            reply_markup=get_scope_keyboard()
        )
        return

    new_scope = os.path.expanduser(" ".join(context.args))

    if not os.path.isdir(new_scope):
        await update.message.reply_text(f"Error: '{new_scope}' is not a valid directory.")
        return

    session_data = load_session_data()
    session_data["scope"] = new_scope
    session_data["session_id"] = None
    save_session_data(session_data)

    await update.message.reply_text(
        f"✅ Scope set to: {new_scope}\nSession reset.",
        reply_markup=get_main_keyboard()
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    import traceback

    error_msg = f"Error: {context.error}\n\n"
    error_msg += "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))

    print(f"Error occurred: {context.error}")

    if OWNER_CHAT_ID:
        try:
            if len(error_msg) > TELEGRAM_MAX_LENGTH:
                error_msg = error_msg[:TELEGRAM_MAX_LENGTH - 100] + "\n\n... (truncated)"
            await context.bot.send_message(chat_id=OWNER_CHAT_ID, text=f"🚨 Bot Error:\n{error_msg}")
        except Exception as e:
            print(f"Failed to send error notification: {e}")


def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set in .env file")
        return

    print(f"Starting bot... Only responding to @{ALLOWED_USERNAME}")
    print(f"Default scope: {DEFAULT_SCOPE}")
    print("Press Ctrl+C to stop")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("send", send_file_cmd))
    app.add_handler(CommandHandler("scope", scope_cmd))

    # Button handler
    app.add_handler(CallbackQueryHandler(button_handler))

    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    app.add_error_handler(error_handler)

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
