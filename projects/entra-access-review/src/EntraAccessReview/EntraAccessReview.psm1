Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Read-JsonObject([string]$Path) {
    try { $data = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable -Depth 100 -DateKind String }
    catch { throw "Cannot read JSON '$Path': $($_.Exception.Message)" }
    if ($data -isnot [System.Collections.IDictionary]) { throw "Expected a JSON object: $Path" }
    return $data
}

function Assert-Text($Record, [string[]]$Fields, [string]$Context) {
    if ($Record -isnot [System.Collections.IDictionary]) { throw "Invalid object at $Context" }
    foreach ($field in $Fields) {
        if ($Record[$field] -isnot [string] -or [string]::IsNullOrWhiteSpace($Record[$field])) {
            throw "Missing or invalid '$field' at $Context"
        }
    }
}

function Assert-Array($Record, [string]$Field, [string]$Context) {
    if ($Record[$Field] -isnot [array]) { throw "Expected array '$Field' at $Context" }
}

function Read-GraphCollection([string]$Path) {
    $data = Read-JsonObject $Path
    Assert-Array $data 'value' $Path
    if ($data['@odata.nextLink']) { throw "Incomplete export (unconsumed @odata.nextLink): $Path" }
    return ,$data['value']
}

function Get-RecordIndex([array]$Records, [string]$Context) {
    $index = @{}
    foreach ($record in $Records) {
        Assert-Text $record @('id') $Context
        if ($index.ContainsKey($record.id)) { throw "Duplicate id '$($record.id)' at $Context" }
        $index[$record.id] = $record
    }
    return $index
}

function ConvertTo-ReviewDate($Value, [string]$Context) {
    $parsed = [DateTimeOffset]::MinValue
    if ($Value -isnot [string] -or $Value -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$' -or
        -not [DateTimeOffset]::TryParse($Value, [cultureinfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$parsed)) {
        throw "Invalid timestamp at $Context; use ISO 8601 with a timezone"
    }
    return $parsed.ToUniversalTime()
}

function ConvertTo-SafeCell($Value) {
    $text = [string]$Value
    # Prevent spreadsheet formula evaluation, including leading control characters.
    if ($text -match '^[\s\p{C}]*[=+@-]' -or $text -match '^[\t\r\n]') { return "'$text" }
    return $text
}

function Write-ReviewCsv([array]$Rows, [string[]]$Columns, [string]$Path) {
    if ($Rows.Count -eq 0) {
        ($Columns | ForEach-Object { '"' + $_ + '"' }) -join ',' | Set-Content -LiteralPath $Path -Encoding utf8
        return
    }
    $Rows | ForEach-Object {
        $safe = [ordered]@{}
        foreach ($column in $Columns) { $safe[$column] = ConvertTo-SafeCell $_.$column }
        [pscustomobject]$safe
    } | Export-Csv -LiteralPath $Path -NoTypeInformation -Encoding utf8
}

function ConvertTo-MarkdownCell($Value) {
    return [System.Net.WebUtility]::HtmlEncode([string]$Value).Replace('|', '&#124;').Replace("`r", ' ').Replace("`n", ' ')
}

function Invoke-EntraAccessReview {
    <#
    .SYNOPSIS
    Reviews complete offline Microsoft Graph exports against a local policy.
    .DESCRIPTION
    Validates all inputs before writing reports. No network calls or directory changes.
    Active exceptions remain visible alongside actionable findings.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ExportPath,
        [Parameter(Mandatory)][string]$PolicyPath,
        [Parameter(Mandatory)][string]$ExceptionsPath,
        [Parameter(Mandatory)][string]$OutputPath,
        [Parameter(Mandatory)][DateTimeOffset]$AsOf
    )
    $AsOf = $AsOf.ToUniversalTime()
    $users = Get-RecordIndex (Read-GraphCollection (Join-Path $ExportPath 'users.json')) 'users'
    $groups = Get-RecordIndex (Read-GraphCollection (Join-Path $ExportPath 'groups.json')) 'groups'
    $roles = Get-RecordIndex (Read-GraphCollection (Join-Path $ExportPath 'role-definitions.json')) 'role definitions'
    $assignments = Get-RecordIndex (Read-GraphCollection (Join-Path $ExportPath 'role-assignments.json')) 'role assignments'
    $registrations = Get-RecordIndex (Read-GraphCollection (Join-Path $ExportPath 'authentication-registration.json')) 'authentication registration'
    $policy = Read-JsonObject $PolicyPath
    Assert-Text $policy @('name') 'policy'
    foreach ($field in @('staleAfterDays', 'maxRolesPerUser')) {
        if ($policy[$field] -isnot [long] -and $policy[$field] -isnot [int]) { throw "Policy $field must be an integer" }
        if ($policy[$field] -lt 1) { throw "Policy $field must be positive" }
    }
    Assert-Array $policy 'roleRules' 'policy'
    $roleRules = @{}
    foreach ($rule in $policy.roleRules) {
        Assert-Text $rule @('roleDefinitionId') 'policy role rule'
        if (-not $roles.ContainsKey($rule.roleDefinitionId)) { throw "Policy references unknown role $($rule.roleDefinitionId)" }
        if ($roleRules.ContainsKey($rule.roleDefinitionId)) { throw 'Duplicate policy role rule' }
        foreach ($field in @('allowedUserIds', 'allowedGroupIds', 'allowedDirectoryScopes')) {
            Assert-Array $rule $field 'policy role rule'
            foreach ($value in $rule[$field]) {
                if ($value -isnot [string] -or [string]::IsNullOrWhiteSpace($value)) { throw "Invalid policy $field entry" }
            }
        }
        foreach ($id in $rule.allowedUserIds) { if (-not $users.ContainsKey($id)) { throw "Policy references unknown user $id" } }
        foreach ($id in $rule.allowedGroupIds) { if (-not $groups.ContainsKey($id)) { throw "Policy references unknown group $id" } }
        $roleRules[$rule.roleDefinitionId] = $rule
    }
    $lastSuccess = @{}
    foreach ($user in $users.Values) {
        Assert-Text $user @('userPrincipalName', 'displayName', 'createdDateTime') "user $($user.id)"
        if ($user['accountEnabled'] -isnot [bool]) { throw "Invalid accountEnabled for user $($user.id)" }
        $created = ConvertTo-ReviewDate $user.createdDateTime "user $($user.id) createdDateTime"
        if ($created -gt $AsOf) { throw "Future creation date for user $($user.id)" }
        $activity = $user['signInActivity']
        $lastSuccess[$user.id] = $null
        if ($user.Contains('signInActivity') -and $null -eq $activity) { continue }
        if ($activity -isnot [System.Collections.IDictionary] -or -not $activity.Contains('lastSuccessfulSignInDateTime')) {
            throw "Missing lastSuccessfulSignInDateTime for user $($user.id); export the field explicitly"
        }
        if ($null -ne $activity.lastSuccessfulSignInDateTime) {
            $date = ConvertTo-ReviewDate $activity.lastSuccessfulSignInDateTime "user $($user.id) last successful sign-in"
            if ($date -gt $AsOf -or $date -lt $created) { throw "Out-of-range sign-in date for user $($user.id)" }
            $lastSuccess[$user.id] = $date
        }
    }
    foreach ($registration in $registrations.Values) {
        if (-not $users.ContainsKey($registration.id)) { throw "Registration references unknown user $($registration.id)" }
        if ($registration['isMfaRegistered'] -isnot [bool]) { throw "Invalid isMfaRegistered for $($registration.id)" }
        Assert-Array $registration 'methodsRegistered' "registration $($registration.id)"
        foreach ($method in $registration.methodsRegistered) {
            if ($method -isnot [string] -or [string]::IsNullOrWhiteSpace($method)) { throw 'Invalid methodsRegistered entry' }
        }
    }
    foreach ($role in $roles.Values) { Assert-Text $role @('displayName') "role $($role.id)" }
    $groupsByUser = @{}
    foreach ($group in $groups.Values) {
        Assert-Text $group @('displayName') "group $($group.id)"
        if ($group['isAssignableToRole'] -isnot [bool]) { throw "Missing isAssignableToRole for group $($group.id)" }
        Assert-Array $group 'members' "group $($group.id)"
        if ($group['members@odata.nextLink']) { throw "Incomplete group membership for $($group.id)" }
        $seenMembers = @{}
        foreach ($member in $group.members) {
            Assert-Text $member @('id', '@odata.type') "group member $($group.id)"
            if ($member['@odata.type'] -ne '#microsoft.graph.user' -or -not $users.ContainsKey($member.id)) {
                throw "Unsupported or unresolved group member $($member.id); export direct users only"
            }
            if ($seenMembers.ContainsKey($member.id)) { throw "Duplicate group member $($member.id)" }
            $seenMembers[$member.id] = $true
            if (-not $groupsByUser.ContainsKey($member.id)) { $groupsByUser[$member.id] = [System.Collections.Generic.List[object]]::new() }
            $groupsByUser[$member.id].Add($group)
        }
    }
    $assignmentsByUser = @{}
    foreach ($assignment in $assignments.Values) {
        Assert-Text $assignment @('principalId', 'roleDefinitionId', 'directoryScopeId') "assignment $($assignment.id)"
        if ($assignment['appScopeId']) { throw "App-scoped assignment $($assignment.id) is unsupported" }
        if (-not $roles.ContainsKey($assignment.roleDefinitionId)) { throw "Unresolved role on assignment $($assignment.id)" }
        if (-not $users.ContainsKey($assignment.principalId) -and -not $groups.ContainsKey($assignment.principalId)) {
            throw "Unresolved principal on assignment $($assignment.id); service principals are outside this review"
        }
        if ($groups.ContainsKey($assignment.principalId) -and -not $groups[$assignment.principalId].isAssignableToRole) {
            throw "Assigned group $($assignment.principalId) is not role-assignable"
        }
        $recipients = @($assignment.principalId)
        if ($groups.ContainsKey($assignment.principalId)) { $recipients = @($groups[$assignment.principalId].members | ForEach-Object { $_.id }) }
        foreach ($id in $recipients) {
            if (-not $assignmentsByUser.ContainsKey($id)) { $assignmentsByUser[$id] = [System.Collections.Generic.List[object]]::new() }
            $assignmentsByUser[$id].Add($assignment)
        }
    }

    $exceptionsDocument = Read-JsonObject $ExceptionsPath
    Assert-Array $exceptionsDocument 'exceptions' 'exceptions'
    $exceptions = @{}
    $exceptionRows = [System.Collections.Generic.List[object]]::new()
    foreach ($exception in $exceptionsDocument.exceptions) {
        Assert-Text $exception @('userId', 'ruleId', 'reason', 'owner', 'expiresOn') 'exception'
        if (-not $users.ContainsKey($exception.userId)) { throw "Exception references unknown user $($exception.userId)" }
        if ($exception.ruleId -notin @('StaleAccount', 'NoMfa', 'UnapprovedRole', 'TooManyRoles')) { throw 'Invalid exception ruleId' }
        $roleId = ''
        if ($exception.ruleId -eq 'UnapprovedRole') {
            Assert-Text $exception @('roleDefinitionId') 'role exception'
            $roleId = $exception.roleDefinitionId
            if (-not $roles.ContainsKey($roleId)) { throw 'Exception references unknown role' }
        } elseif ($exception['roleDefinitionId']) { throw 'Only UnapprovedRole exceptions may specify a roleDefinitionId' }
        $expiry = ConvertTo-ReviewDate $exception.expiresOn 'exception expiresOn'
        $key = "$($exception.userId)|$($exception.ruleId)|$roleId"
        if ($exceptions.ContainsKey($key)) { throw "Duplicate exception $key" }
        $row = [pscustomobject][ordered]@{
            UserId = $exception.userId; RuleId = $exception.ruleId; RoleDefinitionId = $roleId
            Owner = $exception.owner; Reason = $exception.reason; ExpiresOn = $expiry.ToString('o')
            Status = $(if ($expiry -le $AsOf) { 'Expired' } else { 'Unmatched' })
        }
        $exceptions[$key] = $row
        $exceptionRows.Add($row)
    }

    $findings = [System.Collections.Generic.List[object]]::new()
    # The closure keeps exception handling identical for all rules.
    $addFinding = {
        param($User, $RuleId, $Severity, $RoleId, $AssignmentId, $Evidence, $Recommendation)
        $key = "$($User.id)|$RuleId|$RoleId"
        $exception = $exceptions[$key]
        $status = 'Open'
        if ($null -ne $exception -and $exception.Status -ne 'Expired') { $status = 'Excepted'; $exception.Status = 'Applied' }
        $findings.Add([pscustomobject][ordered]@{
            UserId = $User.id; UserPrincipalName = $User.userPrincipalName; DisplayName = $User.displayName
            RuleId = $RuleId; Severity = $Severity; Status = $status; RoleDefinitionId = $RoleId
            AssignmentId = $AssignmentId; Evidence = $Evidence; Recommendation = $Recommendation
            ExceptionOwner = $(if ($exception) { $exception.Owner } else { '' })
            ExceptionReason = $(if ($exception) { $exception.Reason } else { '' })
            ExceptionExpiresOn = $(if ($exception) { $exception.ExpiresOn } else { '' })
        })
    }
    $enabled = @($users.Values | Where-Object { $_.accountEnabled } | Sort-Object id)
    foreach ($user in $enabled) {
        $last = $lastSuccess[$user.id]
        if ($null -eq $last) {
            & $addFinding $user 'MissingSignInEvidence' 'Review' '' '' 'users.json: signInActivity.lastSuccessfulSignInDateTime=null; this does not prove the account never signed in.' 'Check sign-in coverage before deciding whether to disable this account.'
        } elseif ($last -lt $AsOf.AddDays(-$policy.staleAfterDays)) {
            & $addFinding $user 'StaleAccount' 'Medium' '' '' "users.json: lastSuccessfulSignInDateTime=$($last.ToString('o')); inactivity=$([math]::Floor(($AsOf - $last).TotalDays)) days; threshold=$($policy.staleAfterDays) days (strictly older)." 'Confirm the account is still needed; disable it through the normal approval process if unused.'
        }
        if (-not $registrations.ContainsKey($user.id)) {
            & $addFinding $user 'MissingMfaEvidence' 'Review' '' '' 'authentication-registration.json: no registration record for this user.' 'Export the registration record; do not assume missing data means no MFA.'
        } elseif (-not $registrations[$user.id].isMfaRegistered) {
            & $addFinding $user 'NoMfa' 'High' '' '' "authentication-registration.json: isMfaRegistered=false; methodsRegistered=$($registrations[$user.id].methodsRegistered -join ',')." 'Register a strong second sign-in method and check the sign-in enforcement policy.'
        }
        $userGroups = @()
        $effectiveAssignments = @()
        if ($groupsByUser.ContainsKey($user.id)) { $userGroups = @($groupsByUser[$user.id] | Sort-Object id) }
        if ($assignmentsByUser.ContainsKey($user.id)) { $effectiveAssignments = @($assignmentsByUser[$user.id] | Sort-Object id) }
        foreach ($assignment in $effectiveAssignments) {
            $roleId = $assignment.roleDefinitionId
            $rule = $roleRules[$roleId]
            $approved = $false
            if ($null -ne $rule) {
                $approvedIdentity = $user.id -in $rule.allowedUserIds -or @($userGroups | Where-Object { $_.id -in $rule.allowedGroupIds }).Count -gt 0
                $approved = $approvedIdentity -and $assignment.directoryScopeId -in $rule.allowedDirectoryScopes
            }
            if (-not $approved) {
                $path = 'direct user assignment'
                if ($groups.ContainsKey($assignment.principalId)) { $path = "group=$($assignment.principalId) ($($groups[$assignment.principalId].displayName)) -> user=$($user.id)" }
                & $addFinding $user 'UnapprovedRole' 'High' $roleId $assignment.id "role-assignments.json: assignment=$($assignment.id); role=$roleId ($($roles[$roleId].displayName)); scope=$($assignment.directoryScopeId); path=$path; no matching identity-and-scope approval in policy." 'Confirm the role and scope are needed; remove excess access or record a time-limited exception.'
            }
        }
        $distinctRoles = @($effectiveAssignments | ForEach-Object { $_.roleDefinitionId } | Sort-Object -Unique)
        if ($distinctRoles.Count -gt $policy.maxRolesPerUser) {
            $assignmentIds = @($effectiveAssignments | ForEach-Object { $_.id })
            & $addFinding $user 'TooManyRoles' 'High' '' '' "role-assignments.json: distinct effective roles=$($distinctRoles.Count); limit=$($policy.maxRolesPerUser); roleDefinitionIds=$($distinctRoles -join ','); assignmentIds=$($assignmentIds -join ',')." 'Review the combined responsibilities and reduce standing privileges.'
        }
    }

    $sorted = @($findings | Sort-Object UserId, RuleId, RoleDefinitionId, AssignmentId)
    $openCount = @($sorted | Where-Object Status -eq 'Open').Count
    $exceptedCount = @($sorted | Where-Object Status -eq 'Excepted').Count
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add('# Access review')
    $lines.Add('')
    $lines.Add("Policy: $(ConvertTo-MarkdownCell $policy.name). Review time (UTC): $($AsOf.ToString('o')).")
    $lines.Add("Accounts: $($users.Count) exported, $($enabled.Count) enabled and reviewed, $($users.Count - $enabled.Count) disabled and excluded. Findings: $($sorted.Count) total, $openCount open, $exceptedCount excepted.")
    $lines.Add('Missing evidence is a review finding. This report does not certify compliance or change directory access. MFA registration does not prove MFA is enforced.')
    $lines.Add('')
    $lines.Add('## Input fingerprints (SHA-256)')
    $lines.Add('')
    foreach ($name in @('users.json', 'groups.json', 'role-definitions.json', 'role-assignments.json', 'authentication-registration.json')) {
        $hash = (Get-FileHash -LiteralPath (Join-Path $ExportPath $name) -Algorithm SHA256).Hash
        $lines.Add("- ${name}: $hash")
    }
    $lines.Add("- Policy: $((Get-FileHash -LiteralPath $PolicyPath -Algorithm SHA256).Hash)")
    $lines.Add("- Exceptions: $((Get-FileHash -LiteralPath $ExceptionsPath -Algorithm SHA256).Hash)")
    $lines.Add('')
    $lines.Add('## Findings')
    $lines.Add('')
    $lines.Add('| Account (ID) | Rule | Severity | Status | Evidence | Next step | Exception |')
    $lines.Add('| --- | --- | --- | --- | --- | --- | --- |')
    foreach ($finding in $sorted) {
        $exceptionText = ''
        if ($finding.ExceptionOwner) { $exceptionText = "owner=$($finding.ExceptionOwner); reason=$($finding.ExceptionReason); expires=$($finding.ExceptionExpiresOn)" }
        $cells = @("$($finding.UserPrincipalName) ($($finding.UserId))", $finding.RuleId, $finding.Severity, $finding.Status, $finding.Evidence, $finding.Recommendation, $exceptionText)
        $lines.Add('| ' + (($cells | ForEach-Object { ConvertTo-MarkdownCell $_ }) -join ' | ') + ' |')
    }
    if ($sorted.Count -eq 0) { $lines.Add('No findings under this policy and the supplied export. This is not proof that every account is safe.') }
    $lines.Add('')
    $lines.Add('## Exception register')
    $lines.Add('')
    $lines.Add('| User ID | Rule | Role ID | Status | Owner | Reason | Expires (UTC) |')
    $lines.Add('| --- | --- | --- | --- | --- | --- | --- |')
    foreach ($exception in ($exceptionRows | Sort-Object UserId, RuleId, RoleDefinitionId)) {
        $cells = @($exception.UserId, $exception.RuleId, $exception.RoleDefinitionId, $exception.Status, $exception.Owner, $exception.Reason, $exception.ExpiresOn)
        $lines.Add('| ' + (($cells | ForEach-Object { ConvertTo-MarkdownCell $_ }) -join ' | ') + ' |')
    }
    if ($exceptionRows.Count -eq 0) { $lines.Add('No exceptions supplied.') }
    # Validation and evaluation finish before any output files are created.
    $null = New-Item -ItemType Directory -Path $OutputPath -Force
    $findingColumns = @('UserId', 'UserPrincipalName', 'DisplayName', 'RuleId', 'Severity', 'Status', 'RoleDefinitionId', 'AssignmentId', 'Evidence', 'Recommendation', 'ExceptionOwner', 'ExceptionReason', 'ExceptionExpiresOn')
    Write-ReviewCsv $sorted $findingColumns (Join-Path $OutputPath 'findings.csv')
    Write-ReviewCsv @($exceptionRows | Sort-Object UserId, RuleId, RoleDefinitionId) @('UserId', 'RuleId', 'RoleDefinitionId', 'Owner', 'Reason', 'ExpiresOn', 'Status') (Join-Path $OutputPath 'exceptions.csv')
    $lines | Set-Content -LiteralPath (Join-Path $OutputPath 'review.md') -Encoding utf8
    [pscustomobject]@{ ReviewedUsers = $enabled.Count; Findings = $sorted.Count; Open = $openCount; Excepted = $exceptedCount; OutputPath = $OutputPath }
}

Export-ModuleMember -Function Invoke-EntraAccessReview
