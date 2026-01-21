Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\olegus\Desktop\tgccode"
WshShell.Run "pythonw bot.py", 0, False
