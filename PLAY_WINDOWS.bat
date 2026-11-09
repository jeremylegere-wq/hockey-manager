@echo off
cd /d "%~dp0"
if not exist saves mkdir saves
python -m hs.app --saves saves --template auto --env auto %*
if errorlevel 1 pause
