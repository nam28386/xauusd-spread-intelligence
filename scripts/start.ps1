param(
    [ValidateSet('mock','mt5')][string]$Mode = 'mock',
    [string]$SourcesFile = '',
    [switch]$ConfirmLiveReadonly,
    [ValidateRange(1,28800)][int]$Duration = 120,
    [ValidateRange(1,65535)][int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if ($Mode -eq 'mt5') {
    if (-not $ConfirmLiveReadonly -or -not $SourcesFile) {
        throw 'MT5 requires -SourcesFile and -ConfirmLiveReadonly.'
    }
    uv run --frozen --no-sync python -m xbsis live-serve --mode mt5 --port $Port --duration $Duration --sources-file $SourcesFile --confirm-live-readonly
} else {
    if ($SourcesFile -or $ConfirmLiveReadonly) { throw 'Mock mode does not accept live settings.' }
    uv run --frozen --no-sync python -m xbsis live-serve --mode mock --port $Port --duration $Duration
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
