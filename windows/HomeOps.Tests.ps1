BeforeAll { Import-Module "$PSScriptRoot/HomeOps.psm1" -Force }
Describe 'HomeOps safety' {
    It 'does not restart a service with WhatIf' {
        Mock Restart-Service {} -ModuleName HomeOps
        Restart-HomeService -Name EventLog -WhatIf
        Should -Invoke Restart-Service -ModuleName HomeOps -Times 0
    }
    It 'does not create a firewall rule with WhatIf' {
        Mock Get-NetFirewallRule { $null } -ModuleName HomeOps
        Mock New-NetFirewallRule {} -ModuleName HomeOps
        Ensure-HomeFirewallRule -Name 'test' -Port 1234 -WhatIf
        Should -Invoke New-NetFirewallRule -ModuleName HomeOps -Times 0
    }
}
