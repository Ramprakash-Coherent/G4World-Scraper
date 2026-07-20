#Requires -Version 5.1
<#
.SYNOPSIS
  Run countries in parallel; each country scrapes all catalogs (RM→FG→PK→MC) with resume.

.PARAMETER MaxParallel
  How many countries at once (default 2; recommend 2–3).

.PARAMETER Countries
  Comma-separated list, e.g. "Japan,Indonesia,Singapore"

.PARAMETER AllCountries
  Run all 12 target countries.

.PARAMETER ResetProgress
  Clear progress once per country at start (keeps companies.csv).

.EXAMPLE
  .\scripts\run_parallel_countries.ps1 -MaxParallel 2
  .\scripts\run_parallel_countries.ps1 -Countries "Japan,Indonesia" -MaxParallel 2
  .\scripts\run_parallel_countries.ps1 -AllCountries -MaxParallel 3
#>
param(
    [int]$MaxParallel = 2,
    [string]$Countries,
    [switch]$AllCountries,
    [switch]$ResetProgress
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$args = @(
    "run_parallel_countries.py",
    "--max-parallel", "$MaxParallel"
)
if ($AllCountries) {
    $args += "--all-countries"
}
elseif ($Countries) {
    $args += @("--countries", $Countries)
}
else {
    $args += "--interactive"
}
if ($ResetProgress) {
    $args += "--reset-progress"
}

Write-Host ("python " + ($args -join " "))
python @args
exit $LASTEXITCODE
