@echo off
rem winbootfix post-repair launcher: double-click it. Asks for administrator rights.
setlocal
set "HERE=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-ChildItem -LiteralPath '%HERE%' -Recurse | Unblock-File -ErrorAction SilentlyContinue; Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','\"%HERE%winbootfix-post.ps1\"'"
endlocal
