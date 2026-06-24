param(
    [switch]$ResetDb,
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
chcp 65001 | Out-Null

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList
    )
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath $($ArgumentList -join ' ') failed with exit code $LASTEXITCODE."
    }
}

function Test-ContainerExists {
    param([string]$Name)
    $containerId = docker ps -a --filter "name=^/$Name$" --format "{{.ID}}" 2>$null
    return -not [string]::IsNullOrWhiteSpace($containerId)
}

function Wait-Postgres {
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        $status = docker inspect -f "{{.State.Health.Status}}" aikeeper-db 2>$null
        if ($status -eq "healthy") {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "PostgreSQL container did not become healthy in time."
}

function Ensure-Postgres {
    if (Test-ContainerExists "aikeeper-db") {
        $image = docker inspect -f "{{.Config.Image}}" aikeeper-db
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect existing aikeeper-db container."
        }
        if ($image -notlike "pgvector/pgvector:*") {
            throw "Existing aikeeper-db container uses image '$image', expected pgvector/pgvector."
        }

        $running = docker inspect -f "{{.State.Running}}" aikeeper-db
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect existing aikeeper-db container state."
        }
        if ($running -ne "true") {
            Invoke-Native "docker" @("start", "aikeeper-db")
        }
    } else {
        Invoke-Native "docker" @("compose", "up", "-d", "postgres")
    }

    Wait-Postgres
}

if (-not $FrontendOnly) {
    if ($ResetDb) {
        Invoke-Native "docker" @("compose", "down", "-v")
        if (Test-ContainerExists "aikeeper-db") {
            Invoke-Native "docker" @("rm", "-f", "aikeeper-db")
        }
    }
    Ensure-Postgres
    $env:DATABASE_URL = "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper"
    Invoke-Native "python" @("-m", "pytest", "tests/server", "-q")
}

if (-not $BackendOnly) {
    Push-Location (Join-Path $repoRoot "src/client")
    try {
        Invoke-Native "node" @("./node_modules/typescript/bin/tsc", "--noEmit")
        Invoke-Native "node" @("./node_modules/vite/bin/vite.js", "build")
    } finally {
        Pop-Location
    }
}
