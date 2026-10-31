$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

foreach ($tool in @('uv', 'node', 'npm.cmd')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Required tool '$tool' was not found. Install uv (https://docs.astral.sh/uv/getting-started/installation/) and Node.js 20+, then reopen your terminal."
    }
}

$api = $null
$web = $null
try {
    Push-Location "$PSScriptRoot/backend"
    try {
        & uv sync --quiet
        if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
    } finally { Pop-Location }

    if (-not (Test-Path "$PSScriptRoot/frontend/node_modules")) {
        Push-Location "$PSScriptRoot/frontend"
        try {
            & npm.cmd ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        } finally { Pop-Location }
    }

    $api = Start-Process -FilePath (Get-Command uv).Source -ArgumentList @('run', 'uvicorn', 'app.main:app', '--port', '8000') -WorkingDirectory "$PSScriptRoot/backend" -NoNewWindow -PassThru
    $web = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d', '/c', 'npm.cmd run dev -- --port 5173 --strictPort') -WorkingDirectory "$PSScriptRoot/frontend" -NoNewWindow -PassThru
    Write-Host 'PawPath: http://localhost:5173 / API: http://localhost:8000/docs'
    Write-Host 'Press Ctrl+C to stop both servers.'
    while (-not $api.HasExited -and -not $web.HasExited) {
        Start-Sleep -Milliseconds 500
    }
    throw 'A server stopped. Check the error output above.'
} finally {
    foreach ($server in @($api, $web)) {
        if ($null -ne $server -and -not $server.HasExited) {
            & taskkill.exe /PID $server.Id /T /F 2>$null | Out-Null
        }
    }
}
