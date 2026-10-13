#Requires -Version 5.1

# Teacher-facing Stackplan test runner for Windows PowerShell.
[CmdletBinding()]
param(
    [ValidateSet("all", "function", "frontend", "workflow", "deployment", "live")]
    [string]$Group = "all"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$previousLocation = Get-Location
$logDirectory = Join-Path $repositoryRoot "test-results"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logDirectory "stackplan-tests-$timestamp.log"
$transcriptStarted = $false
$exitCode = 0
$functionTestsPassed = $false
$frontendTestsPassed = $false
$workflowTestsPassed = $false
$deploymentTestsPassed = $false
$liveTestPassed = $false

function Write-Heading {
    param([string]$Title)
    Write-Host ""
    Write-Host "============================================================"
    Write-Host $Title
    Write-Host "============================================================"
}

function Write-Description {
    param([string]$Text, [string]$Command)
    Write-Host $Text
    Write-Host "Command: $Command"
    Write-Host ""
}

function Invoke-Native {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Assert-Command {
    param([string]$Name, [string]$Message)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw $Message
    }
}

function Assert-Docker {
    Assert-Command "docker" "Docker Desktop is required. Install and start it before running the tests."
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose 2.24 or newer is required."
    }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop is installed but is not running."
    }
}

function Invoke-FunctionTests {
    Write-Heading "TEST GROUP 1 - Manager and business-rule tests"
    Write-Description `
        "Checks image intake, AI response parsing, schedule construction, Week 7 recess rules, assessment weights, recommendations, and data-manager behaviour. AI calls are mocked, so this group does not use API credits." `
        "$script:pythonCommand -m pytest tests/function"
    $env:PYTHONPATH = "."
    Invoke-Native $script:pythonCommand @("-m", "pytest", "-v", "-p", "no:cacheprovider", "tests/function")
    $script:functionTestsPassed = $true
    Write-Host "PASS - Manager and business-rule tests completed."
}

function Invoke-FrontendTests {
    Write-Heading "TEST GROUP 2 - Frontend contract and browser-logic tests"
    Write-Description `
        "Checks upload forwarding, partial-error display, safe HTML rendering, assessment weight labels, unknown dates, schedule capacity, and study-plan selection." `
        "$script:pythonCommand -m pytest tests/frontend/test_frontend.py; npm run check --prefix frontend"
    $env:PYTHONPATH = "."
    Invoke-Native $script:pythonCommand @("-m", "pytest", "-v", "-p", "no:cacheprovider", "tests/frontend/test_frontend.py")
    Invoke-Native "npm" @("run", "check", "--prefix", "frontend")
    $script:frontendTestsPassed = $true
    Write-Host "PASS - Frontend contract and browser-logic tests completed."
}

function Invoke-WorkflowTests {
    Write-Heading "TEST GROUP 3 - Docker workflow and PostgreSQL tests"
    Write-Description `
        "Builds the test container and checks the API workflow, complete manager pipeline, Docker file staging, and real PostgreSQL persistence in an isolated disposable database." `
        "docker compose --profile test run tests"
    $project = "stackplan-workflow-tests"
    try {
        Invoke-Native "docker" @(
            "compose", "--project-name", $project, "--profile", "test",
            "run", "--build", "--rm", "--no-TTY", "tests",
            "-v", "-p", "no:cacheprovider",
            "tests/workflow", "tests/function/test_data_manager.py"
        )
    }
    finally {
        & docker compose --project-name $project --profile test down --volumes *> $null
    }
    $script:workflowTestsPassed = $true
    Write-Host "PASS - Docker workflow and PostgreSQL tests completed."
}

function Invoke-DeploymentTests {
    Write-Heading "TEST GROUP 4 - Full deployment smoke test"
    Write-Description `
        "Builds and starts the real database, API, and frontend. It checks both health endpoints, loads the homepage, and verifies a project can be written through the frontend proxy and read back from PostgreSQL." `
        "docker compose up database api frontend; python tests/deployment/smoke.py"
    $project = "stackplan-deployment-check"
    $apiPort = if ($env:STACKPLAN_DEPLOYMENT_API_PORT) { $env:STACKPLAN_DEPLOYMENT_API_PORT } else { "18000" }
    $frontendPort = if ($env:STACKPLAN_DEPLOYMENT_FRONTEND_PORT) { $env:STACKPLAN_DEPLOYMENT_FRONTEND_PORT } else { "15173" }
    $env:API_HOST_PORT = $apiPort
    $env:FRONTEND_PORT = $frontendPort
    $composeArguments = @(
        "compose", "--project-name", $project,
        "--file", "compose.yaml", "--file", "tests/deployment/compose.yaml"
    )
    try {
        Invoke-Native "docker" ($composeArguments + @("config", "--quiet"))
        Invoke-Native "docker" ($composeArguments + @("up", "--build", "--detach", "--wait", "database", "api", "frontend"))
        $env:STACKPLAN_DEPLOYMENT_API_URL = "http://127.0.0.1:$apiPort"
        $env:STACKPLAN_DEPLOYMENT_FRONTEND_URL = "http://127.0.0.1:$frontendPort"
        Invoke-Native $script:pythonCommand @("tests/deployment/smoke.py")
    }
    catch {
        & docker @composeArguments logs --no-color database api frontend
        throw
    }
    finally {
        & docker @composeArguments down --volumes *> $null
    }
    $script:deploymentTestsPassed = $true
    Write-Host "PASS - Full deployment smoke test completed."
}

function Invoke-LiveTest {
    Write-Heading "OPTIONAL LIVE AI TEST - One real module image"
    Write-Description `
        "Processes the HSC1010 fixture through the real Qwen service. This requires DASHSCOPE_API_KEY in .env, consumes API credits, and is intentionally excluded from the automated all mode." `
        "docker compose run --rm stackplan-cli /input/grader-test-case/one-module.json"
    Invoke-Native "docker" @(
        "compose", "run", "--rm", "stackplan-cli",
        "/input/grader-test-case/one-module.json"
    )
    $script:liveTestPassed = $true
    Write-Host "PASS - Optional live AI CLI test completed."
}

function Show-VerificationSummary {
    Write-Heading "FINAL VERIFICATION SUMMARY"

    if ($script:functionTestsPassed) {
        Write-Host "✅ Image intake, validation, and multi-image module handling"
        Write-Host "✅ AI response parsing, relevance checks, and failure handling"
        Write-Host "✅ Assessment normalization, weights, ranking, and module ownership"
        Write-Host "✅ Week 1-14 scheduling, unknown dates, and Week 7 recess rules"
        Write-Host "✅ Study-plan recommendations and workload limits"
    }

    if ($script:frontendTestsPassed) {
        Write-Host "✅ Frontend upload forwarding and multipart file handling"
        Write-Host "✅ Partial errors, unknown dates, weights, and plan display"
        Write-Host "✅ Safe rendering of untrusted source text"
    }

    if ($script:workflowTestsPassed) {
        Write-Host "✅ Complete API and manager workflow in Docker"
        Write-Host "✅ PostgreSQL save, reload, and latest-result persistence"
        Write-Host "✅ Isolated test database cleanup"
    }

    if ($script:deploymentTestsPassed) {
        Write-Host "✅ Production database, API, and frontend containers started healthy"
        Write-Host "✅ Frontend homepage and proxy were reachable"
        Write-Host "✅ Project write/read round trip through PostgreSQL"
    }

    if ($script:liveTestPassed) {
        Write-Host "✅ Live HSC1010 image processed through the configured Qwen service"
    }

    Write-Host "⬜ Manual UI run still required - follow the steps below"
}

function Show-UiInstructions {
    Write-Heading "REQUIRED MANUAL CHECK - Run Stackplan through the actual UI"
    Write-Host "Automated tests cannot replace a real user run. Add DASHSCOPE_API_KEY to .env, then start the application:"
    Write-Host ""
    Write-Host "  Windows:     powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_local_windows.ps1"
    Write-Host "  macOS/Linux: ./scripts/run_local_unix.sh"
    Write-Host ""
    Write-Host "Open http://127.0.0.1:5173 and create a trimester."
    Write-Host "Add HSC1007, HSC1009, HSC1010, and OTY1103 as four modules."
    Write-Host "Upload the matching JPEG files from grader-test-case\images\."
    Write-Host "Confirm that the Week 1-14 schedule, assessment details, and study plan appear, and that the saved trimester can be reopened."
    Write-Host ""
    Write-Host "Do not submit an API key in the project ZIP."
}

try {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    Set-Location $repositoryRoot
    Start-Transcript -Path $logFile -Force | Out-Null
    $transcriptStarted = $true

    $venvPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $script:pythonCommand = $venvPython
    }
    else {
        Assert-Command "python" "Python 3.12 is required. Install it and run: python -m pip install -r requirements-dev.txt"
        $script:pythonCommand = "python"
    }

    Write-Heading "STACKPLAN TEACHER TEST SCRIPT"
    Write-Host "Selected test group: $Group"
    Write-Host "Repository: $repositoryRoot"
    Write-Host "Full log: $logFile"

    switch ($Group) {
        "function" { Invoke-FunctionTests }
        "frontend" {
            Assert-Command "npm" "Node.js and npm are required for the frontend tests."
            Invoke-FrontendTests
        }
        "workflow" {
            Assert-Docker
            Invoke-WorkflowTests
        }
        "deployment" {
            Assert-Docker
            Invoke-DeploymentTests
        }
        "live" {
            Assert-Docker
            Invoke-LiveTest
        }
        "all" {
            Assert-Command "npm" "Node.js and npm are required for the frontend tests."
            Assert-Docker
            Invoke-FunctionTests
            Invoke-FrontendTests
            Invoke-WorkflowTests
            Invoke-DeploymentTests
        }
    }

    Write-Heading "AUTOMATED TEST RESULT - PASS"
    Write-Host "The selected Stackplan test group completed successfully."
    Show-VerificationSummary
    Show-UiInstructions
}
catch {
    $exitCode = 1
    Write-Heading "AUTOMATED TEST RESULT - FAIL"
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Review the full log: $logFile"
}
finally {
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
    }
    Set-Location $previousLocation
}

Write-Host "Test log saved to: $logFile"
exit $exitCode
