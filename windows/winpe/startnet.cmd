@echo off
rem winbootfix WinPE start script
wpeinit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File X:\winbootfix\winpe-repair.ps1
echo.
echo winbootfix: type "winbootfix" to open the menu again, "exit" to restart.
doskey winbootfix=powershell.exe -NoProfile -ExecutionPolicy Bypass -File X:\winbootfix\winpe-repair.ps1
