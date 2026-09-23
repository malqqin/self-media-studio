param([switch]$Dev, [switch]$NoOpen)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$runtimePython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) {
    if (Test-Path -LiteralPath $runtimePython) { & $runtimePython -m venv .venv }
    else { python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment. Install Python 3.11+.' }
    & $pythonPath -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
}
& $pythonPath -c "import playwright" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $pythonPath -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Browser collection dependencies could not be installed.' }
}
$nodeRuntime = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin'
if (Test-Path -LiteralPath $nodeRuntime) { $env:PATH = "$nodeRuntime;$env:PATH" }
if ($Dev -or !(Test-Path -LiteralPath (Join-Path $projectRoot 'dist/index.html'))) {
    if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'node_modules'))) {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    }
    if (!$Dev) {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    }
}
$dataDirectory = Join-Path $projectRoot 'data'
New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
$healthy = $false
try { $health = Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 2; $healthy = ($health.ok -and $health.version -eq '0.1.0' -and $health.local_only) } catch {}
if (!$healthy) {
    $process = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8765','--workers','1') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataDirectory 'server.log') -RedirectStandardError (Join-Path $dataDirectory 'server-error.log')
    $process.Id | Set-Content -LiteralPath (Join-Path $dataDirectory 'server.pid')
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try { $health = Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 2; if ($health.ok) { $healthy=$true; break } } catch {}
        if ($process.HasExited) { break }
    }
    if (!$healthy) { throw 'Server did not start. Check data/server-error.log.' }
}
if ($Dev) {
    Write-Output 'API ready at http://127.0.0.1:8765. Starting frontend development server.'
    & npm.cmd run dev
} else {
    Write-Output 'Science Fieldnotes is running: http://127.0.0.1:8765'
    if (!$NoOpen) { Start-Process -FilePath 'http://127.0.0.1:8765' -WindowStyle Hidden }
}
