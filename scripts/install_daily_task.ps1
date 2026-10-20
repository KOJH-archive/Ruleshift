param([string]$TaskName = 'RuleShift-Daily', [string]$Time = '07:30')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (!(Test-Path $python)) { throw "Cannot find $python. Install virtualenv first." }
$parts = $Time -split ':'
if ($parts.Count -ne 2) { throw 'Time must be HH:mm' }
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$action = New-ScheduledTaskAction -Execute $python -Argument '-m ruleshift monitor --notify' -WorkingDirectory $root
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Description 'Check authorized law and financial regulation changes (RuleShift)' -Force
Write-Host "Registered $TaskName at $Time (local PC must be on)."
