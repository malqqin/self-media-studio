$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'data/server.pid'
if (!(Test-Path -LiteralPath $pidFile)) { Write-Output 'No recorded local server.'; exit }
$serverId = [int](Get-Content -LiteralPath $pidFile)
$running = Get-CimInstance Win32_Process -Filter "ProcessId = $serverId" -ErrorAction SilentlyContinue
$expectedPython = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '.venv/Scripts/python.exe'))
if ($running -and $running.CommandLine -match 'uvicorn\s+backend\.app:app' -and $running.ExecutablePath -eq $expectedPython) {
    Stop-Process -Id $serverId
    Write-Output 'Local server stopped. Saved jobs and files are preserved.'
} elseif ($running) {
    throw 'The recorded PID belongs to a different process. It was not stopped.'
} else {
    Write-Output 'The local server is already stopped.'
}
