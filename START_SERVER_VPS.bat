@echo off
cd /d "%~dp0"
if exist C:\Python311\python.exe (
  C:\Python311\python.exe server.py
) else (
  python server.py
)
pause
