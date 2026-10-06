Option Explicit
Dim shell, command
Set shell = CreateObject("WScript.Shell")
command = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command ""Get-CimInstance Win32_Process -Filter 'Name=''python.exe'' OR Name=''pythonw.exe''' -ErrorAction SilentlyContinue ^| Where-Object { $_.CommandLine -and $_.CommandLine.Contains('vision_edge_agent.py') } ^| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"""
shell.Run command, 0, False
