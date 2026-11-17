param([switch]$IncludeMT5)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if ($IncludeMT5) {
    uv sync --frozen --extra dev --extra mt5
} else {
    uv sync --frozen --extra dev
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
