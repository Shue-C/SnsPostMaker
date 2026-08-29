@echo off
rem ---------------------------------------------------------------
rem  Stop any omikuji server (serve.ps1) left running in the background.
rem  Use this if the page keeps showing an old version after updating.
rem ---------------------------------------------------------------
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
