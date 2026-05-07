param(
    [string]$ReleaseTag = "latest",
    [ValidateSet("auto", "cuda", "dml", "cpu")]
    [string]$Variant = "auto",
    [string]$Venv = ".venv",
    [switch]$SkipSync,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = (Get-Command python -ErrorAction Stop).Source

Push-Location $Root
try {
    $Arguments = @(
        "-m", "streamvox_agent_voice.bootstrap",
        "--release-tag", $ReleaseTag,
        "--variant", $Variant,
        "--venv", $Venv
    )

    if ($SkipSync) {
        $Arguments += "--skip-sync"
    }

    if ($DryRun) {
        $Arguments += "--dry-run"
    }

    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
