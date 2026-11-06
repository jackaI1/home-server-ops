function Write-Audit($Action, $Target, $AuditPath) {
    @{time=(Get-Date).ToUniversalTime().ToString('o');action=$Action;target=$Target} | ConvertTo-Json -Compress | Add-Content -Path $AuditPath
}
function Get-HomeHealth {
    [CmdletBinding()] param([string]$ServiceName = 'EventLog')
    [pscustomobject]@{Service=Get-Service -Name $ServiceName; Disks=Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3'; Update=Get-Service -Name wuauserv; Errors=Get-WinEvent -FilterHashtable @{LogName='System';Level=2;StartTime=(Get-Date).AddDays(-1)} -ErrorAction SilentlyContinue | Select-Object -First 20 TimeCreated,Id,ProviderName,Message}
}
function Restart-HomeService {
    [CmdletBinding(SupportsShouldProcess)] param([Parameter(Mandatory)][string]$Name,[string]$AuditPath='homeops-audit.jsonl')
    if ($PSCmdlet.ShouldProcess($Name,'Restart service')) { Restart-Service -Name $Name -ErrorAction Stop; (Get-Service $Name).WaitForStatus('Running',[TimeSpan]::FromSeconds(30)); Write-Audit 'restart-service' $Name $AuditPath }
}
function Ensure-HomeFirewallRule {
    [CmdletBinding(SupportsShouldProcess)] param([Parameter(Mandatory)][string]$Name,[Parameter(Mandatory)][int]$Port,[string]$AuditPath='homeops-audit.jsonl')
    $existing=Get-NetFirewallRule -Name $Name -ErrorAction SilentlyContinue
    if (-not $existing -and $PSCmdlet.ShouldProcess($Name,'Create firewall rule')) { New-NetFirewallRule -Name $Name -DisplayName $Name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port | Out-Null; Write-Audit 'firewall-create' $Name $AuditPath }
}
function Ensure-HomeLocalUser {
    [CmdletBinding(SupportsShouldProcess)] param([Parameter(Mandatory)][string]$Name,[Parameter(Mandatory)][securestring]$Password,[string]$AuditPath='homeops-audit.jsonl')
    if (-not (Get-LocalUser -Name $Name -ErrorAction SilentlyContinue)) {
        if ($PSCmdlet.ShouldProcess($Name,'Create local user')) { New-LocalUser -Name $Name -Password $Password | Out-Null; Write-Audit 'user-create' $Name $AuditPath }
    }
}
function Ensure-HomeLocalGroup {
    [CmdletBinding(SupportsShouldProcess)] param([Parameter(Mandatory)][string]$Name,[string]$AuditPath='homeops-audit.jsonl')
    if (-not (Get-LocalGroup -Name $Name -ErrorAction SilentlyContinue)) {
        if ($PSCmdlet.ShouldProcess($Name,'Create local group')) { New-LocalGroup -Name $Name | Out-Null; Write-Audit 'group-create' $Name $AuditPath }
    }
}
function Ensure-HomeGroupMember {
    [CmdletBinding(SupportsShouldProcess)] param([Parameter(Mandatory)][string]$Group,[Parameter(Mandatory)][string]$User,[string]$AuditPath='homeops-audit.jsonl')
    if (-not (Get-LocalGroupMember -Group $Group | Where-Object { $_.Name -eq $User -or $_.Name -like "*\$User" })) { if ($PSCmdlet.ShouldProcess("$Group/$User",'Add group member')) { Add-LocalGroupMember -Group $Group -Member $User; Write-Audit 'group-add' "$Group/$User" $AuditPath } }
}
function Ensure-HomeLogRotationTask {
    [CmdletBinding(SupportsShouldProcess)] param([Parameter(Mandatory)][string]$Name,[Parameter(Mandatory)][string]$ScriptPath,[string]$AuditPath='homeops-audit.jsonl')
    if (-not (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue)) { if ($PSCmdlet.ShouldProcess($Name,'Register rotation task')) { $action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -File `"$ScriptPath`""; $trigger=New-ScheduledTaskTrigger -Daily -At '02:00'; Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger | Out-Null; Write-Audit 'task-create' $Name $AuditPath } }
}
Export-ModuleMember -Function Get-HomeHealth,Restart-HomeService,Ensure-HomeFirewallRule,Ensure-HomeLocalUser,Ensure-HomeLocalGroup,Ensure-HomeGroupMember,Ensure-HomeLogRotationTask
