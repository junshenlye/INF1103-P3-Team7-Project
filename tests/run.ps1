#Requires -Version 5.1
param([ValidateSet("fast", "full", "integration", "deployment", "all", "workflow")][string]$Group = "full")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:STACKPLAN_PYTHON) { $env:STACKPLAN_PYTHON } elseif (Test-Path "$root\.venv\Scripts\python.exe") { "$root\.venv\Scripts\python.exe" } else { "python" }
if ($Group -eq "all") { $Group = "full" }
if ($Group -eq "workflow") { $Group = "integration" }
& $python "$PSScriptRoot\verify.py" $Group
exit $LASTEXITCODE
