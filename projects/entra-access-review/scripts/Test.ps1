#requires -Version 7.5
$ErrorActionPreference = 'Stop'
Import-Module Pester -RequiredVersion 5.7.1
$configuration = New-PesterConfiguration
$configuration.Run.Path = "$PSScriptRoot/../tests"
$configuration.Run.Exit = $true
$configuration.Output.Verbosity = 'Detailed'
$configuration.TestResult.Enabled = $true
$configuration.TestResult.OutputPath = "$PSScriptRoot/../TestResults.xml"
Invoke-Pester -Configuration $configuration
