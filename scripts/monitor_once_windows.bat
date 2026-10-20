@echo off
cd /d "%~dp0\.."
.venv\Scripts\python.exe -m ruleshift monitor --notify
if errorlevel 1 echo [RuleShift] Monitoring ended with errors. Check Dashboard error log.
