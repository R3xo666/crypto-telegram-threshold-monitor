' Silent Windows background runner for Crypto Monitor Daemon
' Double-clicking this script will launch the daemon invisibly in the background.

Set WshShell = CreateObject("WScript.Shell")

' Build absolute path to main.py and venv pythonw.exe
strCurDir = WshShell.CurrentDirectory
strCmd = """" & strCurDir & "\venv\Scripts\pythonw.exe"" """ & strCurDir & "\main.py"" --config """ & strCurDir & "\config\targets.json"""

' 0 = Hide window, False = Do not wait for return
WshShell.Run strCmd, 0, False
