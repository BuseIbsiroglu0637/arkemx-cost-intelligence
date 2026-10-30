@echo off
cd /d "%~dp0"
python scripts\run_pilot.py
if errorlevel 1 pause
