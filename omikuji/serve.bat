@echo off
rem ---------------------------------------------------------------
rem  Omikuji kiosk server (Windows / PowerShell only, no Python)
rem  Double-click this file. Answer "Yes" to the admin prompt.
rem  Then open the printed http://192.168.x.x:8080/ on the iPad.
rem ---------------------------------------------------------------
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0serve.ps1" %*
if errorlevel 1 pause
