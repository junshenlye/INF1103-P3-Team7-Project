#Requires -Version 5.1

# Start PostgreSQL, the helper API and the frontend on Windows with Docker Desktop.
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "This launcher is for Windows. Use the Unix shell launcher on macOS or Linux."
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$previousLocation = Get-Location
$composeFiles = @(
    "--file", "compose.yaml",
    "--file", "compose.windows.yaml"
)
$startAttempted = $false

try {
    Set-Location $repositoryRoot

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker Desktop is required to start Stackplan."
    }

    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose 2.24 or newer is required to start Stackplan."
    }

    $dockerOperatingSystem = & docker info --format "{{.OSType}}" 2> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop is not running. Start it and try again."
    }
    if ($dockerOperatingSystem.Trim() -ne "linux") {
        throw "Docker Desktop must be switched to Linux containers to run Stackplan."
    }

    if (-not (Test-Path -LiteralPath ".env" -PathType Leaf)) {
        Copy-Item -LiteralPath ".env.example" -Destination ".env"
        Write-Warning "Created .env from .env.example. Add DASHSCOPE_API_KEY before using AI features."
    }

    if ([string]::IsNullOrWhiteSpace($env:FRONTEND_PORT)) {
        if ([string]::IsNullOrWhiteSpace($env:PORT)) {
            $env:FRONTEND_PORT = "5173"
        }
        else {
            $env:FRONTEND_PORT = $env:PORT
        }
    }

    & docker compose @composeFiles config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "The Docker Compose configuration is invalid. Ensure Docker Compose 2.24 or newer is installed."
    }

    Write-Host "Starting Stackplan at http://127.0.0.1:$($env:FRONTEND_PORT)"
    $startAttempted = $true
    & docker compose @composeFiles up --build --detach --wait frontend
    if ($LASTEXITCODE -ne 0) {
        throw "Stackplan failed to start."
    }
    Write-Host "Stackplan is ready. Press Ctrl+C to stop it."
    & docker compose @composeFiles logs --follow frontend api
    if ($LASTEXITCODE -ne 0) {
        throw "Stackplan log streaming stopped unexpectedly."
    }
}
finally {
    if ($startAttempted) {
        Write-Host "Stopping Stackplan frontend, API and database..."
        & docker compose @composeFiles stop frontend api database *> $null
    }
    Set-Location $previousLocation
}
