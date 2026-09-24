$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Get-Content .env | Where-Object { $_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$' } | ForEach-Object {
    $name = $Matches[1]; $value = $Matches[2].Trim('"', "'")
    if ($value) { Set-Item -Path "env:$name" -Value $value }
}
$env:FOOTAGE_ANALYZER_WORKDIR = "$PSScriptRoot\workspace\footage_analyzer"
$env:PYTHONUNBUFFERED = "1"
& .\.venv-fa\Scripts\python -m uvicorn footage_analyzer.server:app --host 127.0.0.1 --port 8010
