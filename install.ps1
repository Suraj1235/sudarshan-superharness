param(
    [Parameter(Mandatory = $true)]
    [string]$AgentRoot,
    [switch]$NonInteractive,
    [switch]$Repair,
    [switch]$WithSearXNG,
    [switch]$SkipSearXNG,
    [switch]$DryRun
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue
}

if (-not $pythonCmd) {
    Write-Error "Python is required to run install.py"
    exit 1
}

$args = @(
    (Join-Path $scriptDir "install.py"),
    "--agent-root", $AgentRoot
)

if ($NonInteractive) { $args += "--noninteractive" }
if ($Repair) { $args += "--repair" }
if ($WithSearXNG) { $args += "--with-searxng" }
if ($SkipSearXNG) { $args += "--skip-searxng" }
if ($DryRun) { $args += "--dry-run" }

& $pythonCmd.Source @args
exit $LASTEXITCODE
