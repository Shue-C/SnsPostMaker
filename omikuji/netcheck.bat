@echo off
rem ---------------------------------------------------------------
rem  Printer connection diagnostics (Windows, no Python needed)
rem  Usage: netcheck.bat -Printer 192.168.10.100
rem ---------------------------------------------------------------
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0netcheck.ps1" %*
