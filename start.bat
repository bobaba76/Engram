@echo off
setlocal
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe scripts\run_index.py
) else (
  python scripts\run_index.py
)
endlocal
