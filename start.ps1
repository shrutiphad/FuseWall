$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$fusewallPython = if (Test-Path -LiteralPath '.venv\Scripts\python.exe') { '.venv\Scripts\python.exe' } else { 'python' }
& $fusewallPython -c 'import fastapi,uvicorn,httpx'
if ($LASTEXITCODE -ne 0) { throw 'Dependencies are missing. Follow README.md setup instructions.' }
Write-Host 'Open http://127.0.0.1:8765 after startup.'
Write-Host 'In another terminal, run: python -m fusewall token'
& $fusewallPython -m fusewall serve
exit $LASTEXITCODE
