#Requires -Version 5.1
<#
.SYNOPSIS
  Prepare listings and run G4World catalog workers (RM / FG / PK / MC).

.PARAMETER Smoke
  Process only 1 listing per worker (Indonesia by default).

.PARAMETER Worker
  Run a single worker: RM, FG, PK, or MC.

.PARAMETER Country
  One country, e.g. Japan or Indonesia.

.PARAMETER AllCountries
  Explicitly run all 12 TARGET_COUNTRIES (long).

.PARAMETER Interactive
  Ensun-style numbered menus for worker + country (default when no country flags).

.EXAMPLE
  .\scripts\run_workers.ps1
  .\scripts\run_workers.ps1 -Interactive
  .\scripts\run_workers.ps1 -Worker RM -Country Japan
  .\scripts\run_workers.ps1 -Smoke
#>
param(
    [switch]$Smoke,
    [ValidateSet("RM", "FG", "PK", "MC")]
    [string]$Worker,
    [string]$Country,
    [switch]$AllCountries,
    [switch]$Interactive
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Default to interactive menus when no country/worker flags (like ensun)
if (-not $Smoke -and -not $Country -and -not $AllCountries -and -not $Worker) {
    $Interactive = $true
}
if ($Interactive -and -not $Smoke) {
    python run_interactive.py
    exit $LASTEXITCODE
}

if (-not $Smoke -and -not $Country -and -not $AllCountries) {
    Write-Error "Specify -Country Japan  OR  -AllCountries  OR  -Smoke  OR  -Interactive"
    exit 2
}
if ($Country -and $AllCountries) {
    Write-Error "Use either -Country or -AllCountries, not both."
    exit 2
}

$AllWorkers = @("RM", "FG", "PK", "MC")
$Selected = if ($Worker) { @($Worker) } else { $AllWorkers }

Write-Host "Preparing listings..."
python scripts/prepare_listings.py
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

foreach ($wid in $Selected) {
    $lower = $wid.ToLower()
    $listingsDir = "listings_$lower"
    $outputDir = "Go4World_$wid"
    $args = @(
        "main_go4world.py",
        "--listings-dir", $listingsDir,
        "--output-dir", $outputDir,
        "--single-csv",
        "--skip-empty-tabs"
    )
    if ($Smoke) {
        $args += @(
            "--max-listings", "1",
            "--country", $(if ($Country) { $Country } else { "Indonesia" }),
            "--reset-progress",
            "--fast"
        )
        $env:G4W_MAX_PAGES_PER_SEARCH = "1"
        $env:G4W_MAX_PROFILES_PER_LISTING = "3"
        $env:G4W_MAX_BUYLEADS_PER_PAGE = "2"
        $env:G4W_MIN_DELAY = "2.0"
        $env:G4W_MAX_DELAY = "4.0"
    }
    elseif ($AllCountries) {
        $args += @("--all-countries", "--fast")
    }
    else {
        $args += @("--country", $Country, "--fast")
    }

    Write-Host ""
    Write-Host "=== Worker $wid $(if ($Smoke) { '(smoke)' } else { '(full)' }) ==="
    Write-Host ("python " + ($args -join " "))
    python @args
    if ($Smoke) {
        Remove-Item Env:G4W_MAX_PAGES_PER_SEARCH -ErrorAction SilentlyContinue
        Remove-Item Env:G4W_MAX_PROFILES_PER_LISTING -ErrorAction SilentlyContinue
        Remove-Item Env:G4W_MAX_BUYLEADS_PER_PAGE -ErrorAction SilentlyContinue
        Remove-Item Env:G4W_MIN_DELAY -ErrorAction SilentlyContinue
        Remove-Item Env:G4W_MAX_DELAY -ErrorAction SilentlyContinue
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Worker $wid exited with code $LASTEXITCODE (continuing)"
    }
}

Write-Host ""
Write-Host "Done. Outputs under Go4World_RM / Go4World_FG / Go4World_PK / Go4World_MC"
