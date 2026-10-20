@echo off
setlocal
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 goto :no_python

if not exist ".venv\Scripts\python.exe" goto :create_venv
.venv\Scripts\python.exe -c "import streamlit, requests, defusedxml, docx, bs4, dateutil, dotenv" >nul 2>&1
if not errorlevel 1 goto :run_app
echo [RuleShift] Repairing incomplete virtual environment...
rmdir /s /q ".venv"
if exist ".venv" goto :failed

:create_venv
echo [RuleShift] Creating virtual environment...
python -m venv --without-pip .venv
if errorlevel 1 goto :failed

:install_requirements
python -m pip --python .venv install -r requirements.txt
if errorlevel 1 goto :failed

:run_app
.venv\Scripts\python.exe -m streamlit run app.py
if errorlevel 1 goto :failed
exit /b 0

:no_python
echo [RuleShift] Python을 찾을 수 없습니다. Python 3.11 이상을 설치하고 PATH에 추가하세요.

:failed
echo.
echo [RuleShift] Error occurred. Please review the message above.
pause
exit /b 1
