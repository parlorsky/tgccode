#!/usr/bin/env python3
"""
Setup script to add the bot to Windows startup.
Run this once to make the bot start automatically when Windows boots.
"""

import os
import sys

def setup_autostart():
    if sys.platform != "win32":
        print("This script is for Windows only.")
        return False

    try:
        import winshell
        from win32com.client import Dispatch
    except ImportError:
        print("Installing required packages...")
        os.system("pip install pywin32 winshell")
        import winshell
        from win32com.client import Dispatch

    # Paths
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    vbs_path = os.path.join(bot_dir, "start_bot.vbs")
    startup_folder = winshell.startup()
    shortcut_path = os.path.join(startup_folder, "TelegramClaudeBot.lnk")

    # Create shortcut
    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(shortcut_path)
    shortcut.Targetpath = vbs_path
    shortcut.WorkingDirectory = bot_dir
    shortcut.Description = "Telegram Claude Code Bot"
    shortcut.save()

    print(f"Autostart configured!")
    print(f"Shortcut created at: {shortcut_path}")
    print(f"The bot will now start automatically when Windows boots.")
    return True


def remove_autostart():
    try:
        import winshell
    except ImportError:
        os.system("pip install winshell")
        import winshell

    startup_folder = winshell.startup()
    shortcut_path = os.path.join(startup_folder, "TelegramClaudeBot.lnk")

    if os.path.exists(shortcut_path):
        os.remove(shortcut_path)
        print(f"Autostart removed.")
    else:
        print("Autostart was not configured.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--remove":
        remove_autostart()
    else:
        setup_autostart()
