BeforeAll {
    $repo = Split-Path $PSScriptRoot -Parent
    Import-Module "$repo/src/EntraAccessReview/EntraAccessReview.psd1" -Force
    $u1 = '00000000-0000-0000-0000-000000000001'
    $u2 = '00000000-0000-0000-0000-000000000002'
    $u3 = '00000000-0000-0000-0000-000000000003'
    $u4 = '00000000-0000-0000-0000-000000000004'
    $u5 = '00000000-0000-0000-0000-000000000005'
    $u6 = '00000000-0000-0000-0000-000000000006'
    $globalRole = '62e90394-69f5-4237-9190-012177145e10'
    $helpdeskRole = '729827e3-9c14-49f7-bb1b-9608f156bbb8'
    function Read-TestJson($Path) { Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable -DateKind String }
    function Save-TestJson($Path, $Value) { ConvertTo-Json -InputObject $Value -Depth 100 | Set-Content -LiteralPath $Path }
    function Run-Review {
        Invoke-EntraAccessReview -ExportPath "$case/graph" -PolicyPath "$case/policy.json" -ExceptionsPath "$case/exceptions.json" -OutputPath "$case/report" -AsOf '2026-11-05T00:00:00Z'
    }
    function Get-Findings { @(Import-Csv "$case/report/findings.csv") }
}

Describe 'Offline Entra access review' {
    BeforeEach {
        $case = Join-Path $TestDrive ([guid]::NewGuid().ToString())
        $null = New-Item -ItemType Directory -Path $case
        Copy-Item "$repo/samples/*" $case -Recurse
    }

    It 'reviews the complete fixture and writes all three reports' {
        $result = Run-Review
        $result.ReviewedUsers | Should -Be 5
        $result.Findings | Should -Be 10
        $result.Open | Should -Be 8
        $result.Excepted | Should -Be 2
        (Get-Findings).Count | Should -Be 10
        @(Import-Csv "$case/report/exceptions.csv").Count | Should -Be 4
        $report = Get-Content "$case/report/review.md" -Raw
        $report | Should -Match '5 enabled and reviewed, 1 disabled'
        $report | Should -Match (Get-FileHash "$case/graph/users.json").Hash
        $report | Should -Match 'Migration approval has expired'
    }

    It 'uses successful activity despite a recent attempt and includes the date and threshold' {
        $null = Run-Review
        $finding = Get-Findings | Where-Object { $_.UserId -eq $u1 -and $_.RuleId -eq 'StaleAccount' }
        $finding.Status | Should -Be 'Open'
        $finding.Evidence | Should -Match '2026-06-01'
        $finding.Evidence | Should -Match 'threshold=90'
    }

    It 'keeps the exact 90-day boundary active and excludes disabled accounts' {
        $null = Run-Review
        @(Get-Findings | Where-Object UserId -eq $u6).Count | Should -Be 0
        @(Get-Findings | Where-Object UserId -eq $u3).Count | Should -Be 0
    }

    It 'does not mistake email registration for MFA' {
        $null = Run-Review
        $finding = Get-Findings | Where-Object { $_.UserId -eq $u1 -and $_.RuleId -eq 'NoMfa' }
        $finding.Evidence | Should -Match 'isMfaRegistered=false; methodsRegistered=email'
        @(Get-Findings | Where-Object { $_.UserId -eq $u2 -and $_.RuleId -eq 'NoMfa' }).Count | Should -Be 0
    }

    It 'labels missing sign-in and registration evidence without inventing stale or no-MFA findings' {
        $null = Run-Review
        $rules = @(Get-Findings | Where-Object UserId -eq $u4 | Select-Object -ExpandProperty RuleId)
        $rules | Should -Contain 'MissingSignInEvidence'
        $rules | Should -Contain 'MissingMfaEvidence'
        $rules.Count | Should -Be 2
    }

    It 'resolves a group role and permits a documented support role' {
        $null = Run-Review
        $finding = Get-Findings | Where-Object { $_.UserId -eq $u2 -and $_.RoleDefinitionId -eq $globalRole }
        $finding.AssignmentId | Should -Be 'synthetic-assignment-3'
        $finding.Evidence | Should -Match 'Old admin group'
        @(Get-Findings | Where-Object RoleDefinitionId -eq $helpdeskRole).Count | Should -Be 0
    }

    It 'accepts a Graph null signInActivity object as missing evidence' {
        $data = Read-TestJson "$case/graph/users.json"
        $data.value[0].signInActivity = $null
        Save-TestJson "$case/graph/users.json" $data
        $null = Run-Review
        $rules = @(Get-Findings | Where-Object UserId -eq $u1 | Select-Object -ExpandProperty RuleId)
        $rules | Should -Contain 'MissingSignInEvidence'
        $rules | Should -Not -Contain 'StaleAccount'
    }

    It 'denies an unlisted role and counts distinct effective roles' {
        $null = Run-Review
        $findings = @(Get-Findings | Where-Object UserId -eq $u2)
        @($findings | Where-Object RuleId -eq 'UnapprovedRole').Count | Should -Be 2
        ($findings | Where-Object RuleId -eq 'TooManyRoles').Evidence | Should -Match 'distinct effective roles=3; limit=2'
    }

    It 'does not double-count the same role granted through two paths' {
        $data = Read-TestJson "$case/graph/role-assignments.json"
        $duplicate = $data.value[2].Clone()
        $duplicate.id = 'duplicate-path'
        $duplicate.principalId = $u2
        $data.value += $duplicate
        Save-TestJson "$case/graph/role-assignments.json" $data
        $null = Run-Review
        (Get-Findings | Where-Object { $_.UserId -eq $u2 -and $_.RuleId -eq 'TooManyRoles' }).Evidence | Should -Match 'roles=3;'
    }

    It 'requires both identity approval and scope approval' {
        $data = Read-TestJson "$case/graph/role-assignments.json"
        $data.value[1].directoryScopeId = '/administrativeUnits/demo-unit'
        Save-TestJson "$case/graph/role-assignments.json" $data
        $null = Run-Review
        $finding = Get-Findings | Where-Object RoleDefinitionId -eq $helpdeskRole
        $finding.RuleId | Should -Be 'UnapprovedRole'
        $finding.Evidence | Should -Match '/administrativeUnits/demo-unit'
    }

    It 'retains approved exceptions and exposes expired and unmatched entries' {
        $null = Run-Review
        @(Get-Findings | Where-Object { $_.UserId -eq $u5 -and $_.Status -eq 'Excepted' }).Count | Should -Be 2
        (Get-Findings | Where-Object { $_.UserId -eq $u1 -and $_.RuleId -eq 'UnapprovedRole' }).Status | Should -Be 'Open'
        $exceptions = @(Import-Csv "$case/report/exceptions.csv")
        @($exceptions | Where-Object Status -eq 'Applied').Count | Should -Be 2
        @($exceptions | Where-Object Status -eq 'Expired').Count | Should -Be 1
        @($exceptions | Where-Object Status -eq 'Unmatched').Count | Should -Be 1
    }

    It 'expires an exception exactly at the review time' {
        $data = Read-TestJson "$case/exceptions.json"
        $data.exceptions[0].expiresOn = '2026-11-05T00:00:00Z'
        Save-TestJson "$case/exceptions.json" $data
        (Run-Review).Excepted | Should -Be 1
    }

    It 'produces byte-identical reports for the same inputs and review time' {
        $null = Run-Review
        $before = @(Get-ChildItem "$case/report" | Get-FileHash | Select-Object -ExpandProperty Hash)
        $null = Run-Review
        @(Get-ChildItem "$case/report" | Get-FileHash | Select-Object -ExpandProperty Hash) -join ',' | Should -Be ($before -join ',')
    }

    It 'neutralizes spreadsheet formulas and escapes markdown table and HTML content' {
        $data = Read-TestJson "$case/graph/users.json"
        $data.value[0].displayName = '=HYPERLINK("https://example.invalid")'
        $data.value[0].userPrincipalName = "<script>alert(1)</script>|bad`nrow@example.invalid"
        Save-TestJson "$case/graph/users.json" $data
        $null = Run-Review
        (Get-Findings | Where-Object UserId -eq $u1 | Select-Object -First 1).DisplayName | Should -Be "'=HYPERLINK(`"https://example.invalid`")"
        $report = Get-Content "$case/report/review.md" -Raw
        $report | Should -Not -Match '<script>'
        $report | Should -Match '&lt;script&gt;'
        $report | Should -Match '&#124;bad row'
    }

    It 'writes usable header-only CSV files for an empty tenant' {
        Get-ChildItem "$case/graph/*.json" | ForEach-Object { Save-TestJson $_.FullName @{ value = @() } }
        $policy = Read-TestJson "$case/policy.json"
        $policy.roleRules = @()
        Save-TestJson "$case/policy.json" $policy
        Save-TestJson "$case/exceptions.json" @{ exceptions = @() }
        (Run-Review).Findings | Should -Be 0
        (Get-Content "$case/report/findings.csv") | Should -Match '"UserId","UserPrincipalName"'
        (Get-Content "$case/report/exceptions.csv") | Should -Match '"UserId","RuleId"'
        Get-Content "$case/report/review.md" -Raw | Should -Match 'No findings under this policy'
    }

    It 'rejects broken JSON before creating reports' {
        Copy-Item "$PSScriptRoot/fixtures/invalid-json.json" "$case/graph/users.json"
        { Run-Review } | Should -Throw '*Cannot read JSON*'
        Test-Path "$case/report" | Should -BeFalse
    }

    It 'rejects the malformed-record fixture before creating reports' {
        $data = Read-TestJson "$case/graph/users.json"
        $data.value += Read-TestJson "$PSScriptRoot/fixtures/malformed-user.json"
        Save-TestJson "$case/graph/users.json" $data
        { Run-Review } | Should -Throw '*Invalid accountEnabled*'
        Test-Path "$case/report" | Should -BeFalse
    }

    It 'rejects <Label>' -ForEach @(
        @{ Label = 'a duplicate user ID'; File = 'graph/users.json'; Change = { param($d) $d.value += $d.value[0] }; Message = '*Duplicate id*' }
        @{ Label = 'an unfinished Graph page'; File = 'graph/users.json'; Change = { param($d) $d['@odata.nextLink'] = 'https://graph.microsoft.com/next' }; Message = '*Incomplete export*' }
        @{ Label = 'a non-array collection'; File = 'graph/users.json'; Change = { param($d) $d.value = @{} }; Message = '*Expected array*' }
        @{ Label = 'a missing account ID'; File = 'graph/users.json'; Change = { param($d) $d.value[0].Remove('id') }; Message = '*invalid*id*' }
        @{ Label = 'an impossible calendar date'; File = 'graph/users.json'; Change = { param($d) $d.value[0].signInActivity.lastSuccessfulSignInDateTime = '2026-02-30T00:00:00Z' }; Message = '*Invalid timestamp*' }
        @{ Label = 'a timestamp without a timezone'; File = 'graph/users.json'; Change = { param($d) $d.value[0].signInActivity.lastSuccessfulSignInDateTime = '2026-05-01T00:00:00' }; Message = '*Invalid timestamp*' }
        @{ Label = 'a future sign-in date'; File = 'graph/users.json'; Change = { param($d) $d.value[0].signInActivity.lastSuccessfulSignInDateTime = '2027-01-01T00:00:00Z' }; Message = '*Out-of-range sign-in*' }
        @{ Label = 'an omitted sign-in field'; File = 'graph/users.json'; Change = { param($d) $d.value[0].Remove('signInActivity') }; Message = '*Missing lastSuccessful*' }
        @{ Label = 'a string MFA flag'; File = 'graph/authentication-registration.json'; Change = { param($d) $d.value[0].isMfaRegistered = 'false' }; Message = '*Invalid isMfaRegistered*' }
        @{ Label = 'a registration without method details'; File = 'graph/authentication-registration.json'; Change = { param($d) $d.value[0].Remove('methodsRegistered') }; Message = '*Expected array*' }
        @{ Label = 'an unresolved registration'; File = 'graph/authentication-registration.json'; Change = { param($d) $d.value[0].id = 'missing' }; Message = '*unknown user*' }
        @{ Label = 'an unresolved principal'; File = 'graph/role-assignments.json'; Change = { param($d) $d.value[0].principalId = 'missing' }; Message = '*Unresolved principal*' }
        @{ Label = 'an unresolved role'; File = 'graph/role-assignments.json'; Change = { param($d) $d.value[0].roleDefinitionId = 'missing' }; Message = '*Unresolved role*' }
        @{ Label = 'an app-scoped assignment'; File = 'graph/role-assignments.json'; Change = { param($d) $d.value[0].appScopeId = '/app/demo' }; Message = '*App-scoped*' }
        @{ Label = 'a non-role-assignable group'; File = 'graph/groups.json'; Change = { param($d) $d.value[0].isAssignableToRole = $false }; Message = '*not role-assignable*' }
        @{ Label = 'a truncated membership list'; File = 'graph/groups.json'; Change = { param($d) $d.value[0]['members@odata.nextLink'] = 'https://graph.microsoft.com/next' }; Message = '*Incomplete group membership*' }
        @{ Label = 'nested membership'; File = 'graph/groups.json'; Change = { param($d) $d.value[0].members[0]['@odata.type'] = '#microsoft.graph.group' }; Message = '*Unsupported or unresolved group member*' }
        @{ Label = 'an unresolved member'; File = 'graph/groups.json'; Change = { param($d) $d.value[0].members[0].id = 'missing' }; Message = '*Unsupported or unresolved group member*' }
        @{ Label = 'duplicate membership'; File = 'graph/groups.json'; Change = { param($d) $d.value[0].members += $d.value[0].members[0] }; Message = '*Duplicate group member*' }
        @{ Label = 'a zero-day policy'; File = 'policy.json'; Change = { param($d) $d.staleAfterDays = 0 }; Message = '*must be positive*' }
        @{ Label = 'a fractional role limit'; File = 'policy.json'; Change = { param($d) $d.maxRolesPerUser = 1.5 }; Message = '*must be an integer*' }
        @{ Label = 'a duplicate role rule'; File = 'policy.json'; Change = { param($d) $d.roleRules += $d.roleRules[0] }; Message = '*Duplicate policy role rule*' }
        @{ Label = 'an unresolved policy user'; File = 'policy.json'; Change = { param($d) $d.roleRules[0].allowedUserIds = @('missing') }; Message = '*Policy references unknown user*' }
        @{ Label = 'a duplicate exception'; File = 'exceptions.json'; Change = { param($d) $d.exceptions += $d.exceptions[0] }; Message = '*Duplicate exception*' }
        @{ Label = 'an exception without an owner'; File = 'exceptions.json'; Change = { param($d) $d.exceptions[0].owner = '' }; Message = '*invalid*owner*' }
        @{ Label = 'an unknown exception rule'; File = 'exceptions.json'; Change = { param($d) $d.exceptions[0].ruleId = 'MissingMfaEvidence' }; Message = '*Invalid exception ruleId*' }
        @{ Label = 'a role exception without a role ID'; File = 'exceptions.json'; Change = { param($d) $d.exceptions[3].Remove('roleDefinitionId') }; Message = '*invalid*roleDefinitionId*' }
    ) {
        $path = Join-Path $case $File
        $data = Read-TestJson $path
        $null = & $Change $data
        Save-TestJson $path $data
        { Run-Review } | Should -Throw $Message
        Test-Path "$case/report" | Should -BeFalse
    }
}
