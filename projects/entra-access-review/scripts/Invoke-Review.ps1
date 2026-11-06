#requires -Version 7.5
[CmdletBinding()]
param(
    [string]$ExportPath = "$PSScriptRoot/../samples/graph",
    [string]$PolicyPath = "$PSScriptRoot/../samples/policy.json",
    [string]$ExceptionsPath = "$PSScriptRoot/../samples/exceptions.json",
    [string]$OutputPath = "$PSScriptRoot/../output",
    [DateTimeOffset]$AsOf = [DateTimeOffset]::UtcNow
)
$ErrorActionPreference = 'Stop'
Import-Module "$PSScriptRoot/../src/EntraAccessReview/EntraAccessReview.psd1" -Force
try {
    Invoke-EntraAccessReview -ExportPath $ExportPath -PolicyPath $PolicyPath -ExceptionsPath $ExceptionsPath -OutputPath $OutputPath -AsOf $AsOf
} catch { Write-Error $_ -ErrorAction Continue; exit 1 }
