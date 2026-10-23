# Start, or reuse, the prepared local application. No automatic package installs.
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\use-storage.ps1"
$python = 'E:\HumanitiAI\venvs\humaniti\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Application environment is missing. Follow the fresh-setup commands in README.md.'
}
$existing = $null
try { $existing = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 2 } catch { }
if ($existing -and $existing.status -eq 'ok' -and $existing.media_uploads -eq $false -and $existing.model -eq 'gemini-3.8-flash') {
    Write-Output 'Application is already running: http://127.0.0.1:8000'
    return
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$stdoutPath = "E:\HumanitiAI\tmp\humaniti-server-$stamp.stdout.log"
$stderrPath = "E:\HumanitiAI\tmp\humaniti-server-$stamp.stderr.log"
$serverProcess = Start-Process -FilePath $python -ArgumentList @('-u', (Join-Path $PSScriptRoot '..\server.py')) -WorkingDirectory (Split-Path $PSScriptRoot) -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 1
        if ($health.status -eq 'ok' -and $health.media_uploads -eq $false) {
            Write-Output ('Application running: http://127.0.0.1:8000 (detached process ' + $serverProcess.Id + ')')
            Write-Output 'Closing this terminal will not stop the detached server.'
            Write-Output ('Server errors, if any: ' + $stderrPath)
            return
        }
    } catch { }
    Start-Sleep -Milliseconds 150
}
throw ('Server did not become ready. Inspect ' + $stderrPath)
