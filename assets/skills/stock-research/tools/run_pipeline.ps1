# stock-research run bootstrap (ASCII only: PS 5.1 safe)
# Usage: .\run_pipeline.ps1 -Code 600048
# Artifacts go to the CURRENT working directory (never inside the plugin dir).
param(
    [Parameter(Mandatory = $true)]
    [string]$Code
)
$ErrorActionPreference = 'Stop'
# Python: EQUITY_PY > DSH bundled runtime > PATH python
if ($env:EQUITY_PY) { $PY = $env:EQUITY_PY }
elseif ($env:DSH_HOME) {
  $cand = Join-Path $env:DSH_HOME 'dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
  if (Test-Path $cand) { $PY = $cand } else { $PY = (Get-Command python -ErrorAction SilentlyContinue).Source }
} else { $PY = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $PY) { Write-Host '[FAIL] python not found (set EQUITY_PY)'; exit 2 }
# Tools dir: EQUITY_TOOLS or alongside this script
if ($env:EQUITY_TOOLS) { $TOOLS = $env:EQUITY_TOOLS } else { $TOOLS = $PSScriptRoot }
$runid = $Code + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$RUN = Join-Path (Join-Path (Get-Location).Path 'equity-runs') $runid
New-Item -ItemType Directory -Path $RUN -Force | Out-Null
Write-Host ('runid : ' + $runid)
Write-Host ('run   : ' + $RUN)
Write-Host '[1/2] data agent: fetching ...'
& $PY (Join-Path $TOOLS 'fetch_data.py') --code $Code --history-days 1300 --out (Join-Path $RUN 'data.json')
if ($LASTEXITCODE -ne 0) { Write-Host '[FAIL] fetch failed - do NOT continue with empty data'; exit 1 }
Write-Host '[2/2] ready. Dispatch role agents per roles/*.md, then run the gate:'
Write-Host ('  & "' + $PY + '" "' + (Join-Path $TOOLS 'sanitize_check.py') + '" "' + $RUN + '" --json')
Write-Host ('exit 0 = write allowed; non-zero = rewrite, NEVER bypass.')
$runid
