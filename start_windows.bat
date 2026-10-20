@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv
  if errorlevel 1 goto :failed
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :failed
.venv\Scripts\python.exe -m streamlit run app.py
if errorlevel 1 goto :failed
exit /b 0
:failed
echo.
echo [RuleShift] Error occurred. Please review the message above.
pause
exit /b 1
