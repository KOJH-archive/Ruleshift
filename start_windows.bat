@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE=python"
set "PYTHON_ARGS="
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 goto :no_python
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3.11"
)
if not exist ".venv\Scripts\python.exe" (
  echo [RuleShift] Creating virtual environment...
  %PYTHON_EXE% %PYTHON_ARGS% -m venv --without-pip .venv
  if errorlevel 1 goto :failed
  %PYTHON_EXE% %PYTHON_ARGS% -m pip --python .venv install -r requirements.txt
  if errorlevel 1 goto :failed
) else (
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
)
.venv\Scripts\python.exe -m streamlit run app.py
if errorlevel 1 goto :failed
exit /b 0
:no_python
echo [RuleShift] Python을 찾을 수 없습니다. Python 3.11 이상을 설치하고 PATH에 추가하세요.
goto :failed
:failed
echo.
echo [RuleShift] Error occurred. Please review the message above.
pause
exit /b 1
