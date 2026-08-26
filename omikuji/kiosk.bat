@echo off
rem ---------------------------------------------------------------
rem  Omikuji kiosk launcher (Windows only, no iPad, no Python)
rem  Serves this folder on localhost and opens Edge in kiosk mode.
rem  Double-click this file. No administrator rights required.
rem ---------------------------------------------------------------
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0kiosk.ps1" %*
if errorlevel 1 pause
