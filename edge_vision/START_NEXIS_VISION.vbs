Option Explicit
Dim sh, fso, base, ps1, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = fso.BuildPath(base, "START_NEXIS_VISION.ps1")
If Not fso.FileExists(ps1) Then
  MsgBox "START_NEXIS_VISION.ps1 was not found. Keep the complete edge_vision folder together.", 48, "NEXis Vision"
  WScript.Quit 2
End If
cmd = "powershell.exe -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Chr(34) & ps1 & Chr(34)
sh.Run cmd, 0, False
