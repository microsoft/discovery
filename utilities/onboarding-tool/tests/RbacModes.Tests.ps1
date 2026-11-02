$modulePath = Join-Path $PSScriptRoot '..\scripts\lib\OnboardingCommon.psm1'
$stage2Path = Join-Path $PSScriptRoot '..\scripts\stage2-landing-zone\stage2_prepare.ps1'
$stage4Path = Join-Path $PSScriptRoot '..\scripts\stage4-deployment\stage4_deploy.ps1'
Import-Module $modulePath -Force

foreach ($functionSpec in @(
        @{ Path = $stage2Path; Name = 'Grant-OnboardingRole' },
        @{ Path = $stage4Path; Name = 'Get-ObjProp' },
        @{ Path = $stage4Path; Name = 'Grant-FoundryRolesOnManagedRg' }
    )) {
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        (Resolve-Path $functionSpec.Path),
        [ref]$tokens,
        [ref]$errors
    )
    if ($errors.Count) { throw ($errors.Message -join [Environment]::NewLine) }
    $functionAst = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionSpec.Name
        }, $true)
    if (-not $functionAst) { throw "Function $($functionSpec.Name) was not found in $($functionSpec.Path)." }
    Invoke-Expression $functionAst.Extent.Text
}

function New-TestConfig {
    param(
        [string]$Mode = 'permanent-role-assignments',
        [int]$DurationDays = -1
    )

    $config = [ordered]@{
        schemaVersion      = '1.0'
        subscriptionId     = '00000000-0000-0000-0000-000000000000'
        controlPlaneRegion = 'eastus'
        workloadRegion     = 'eastus'
        network            = @{}
        sizingTier         = 'Small'
        names              = @{ workspace = 'test-workspace' }
        deployingIdentity  = @{
            objectId = '11111111-1111-1111-1111-111111111111'
            type     = 'user'
        }
        rbac               = @{ humanAccessMode = $Mode }
    }
    if ($DurationDays -ge 0) {
        $config.rbac.jitEligibilityDurationDays = $DurationDays
    }
    return $config | ConvertTo-Json -Depth 10 | ConvertFrom-Json
}

Describe 'Get-OnboardingConfig human RBAC validation' {
    It 'accepts permanent-role-assignments without a JIT duration' {
        $path = Join-Path $TestDrive 'permanent-role-assignments.json'
        New-TestConfig | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $path

        (Get-OnboardingConfig -Path $path).rbac.humanAccessMode | Should Be 'permanent-role-assignments'
    }

    It 'accepts customer-jit-managed with an eligibility duration of at least seven days' {
        $path = Join-Path $TestDrive 'customer-jit.json'
        New-TestConfig -Mode 'customer-jit-managed' -DurationDays 7 | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $path

        (Get-OnboardingConfig -Path $path).rbac.jitEligibilityDurationDays | Should Be 7
    }

    It 'rejects customer-jit-managed without a duration' {
        $path = Join-Path $TestDrive 'missing-duration.json'
        New-TestConfig -Mode 'customer-jit-managed' | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $path

        $threw = $false
        try { Get-OnboardingConfig -Path $path | Out-Null }
        catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'rejects a JIT duration in permanent-role-assignments mode' {
        $path = Join-Path $TestDrive 'unexpected-duration.json'
        New-TestConfig -DurationDays 7 | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $path

        $threw = $false
        try { Get-OnboardingConfig -Path $path | Out-Null }
        catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'rejects an eligibility duration shorter than seven days' {
        $path = Join-Path $TestDrive 'short-duration.json'
        New-TestConfig -Mode 'customer-jit-managed' -DurationDays 6 | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $path

        $threw = $false
        try { Get-OnboardingConfig -Path $path | Out-Null }
        catch { $threw = $true }
        $threw | Should Be $true
    }

    It 'accepts the maximum eligibility duration' {
        $path = Join-Path $TestDrive 'maximum-duration.json'
        New-TestConfig -Mode 'customer-jit-managed' -DurationDays 3650 | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $path

        (Get-OnboardingConfig -Path $path).rbac.jitEligibilityDurationDays | Should Be 3650
    }

    It 'rejects an eligibility duration longer than 3650 days' {
        $path = Join-Path $TestDrive 'excessive-duration.json'
        New-TestConfig -Mode 'customer-jit-managed' -DurationDays 3651 | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $path

        $threw = $false
        try { Get-OnboardingConfig -Path $path | Out-Null }
        catch { $threw = $true }
        $threw | Should Be $true
    }
}

Describe 'Test-CustomerJitManagedUser' {
    $jitConfig = New-TestConfig -Mode 'customer-jit-managed' -DurationDays 7

    It 'matches only User principals in customer JIT mode' {
        (Test-CustomerJitManagedUser -Config $jitConfig -PrincipalType 'User') | Should Be $true
        (Test-CustomerJitManagedUser -Config $jitConfig -PrincipalType 'ServicePrincipal') | Should Be $false
        (Test-CustomerJitManagedUser -Config $jitConfig -PrincipalType 'Group') | Should Be $false
    }
}

Describe 'Set-PimRoleEligibility' {
    BeforeEach {
        Mock Get-AzJson -ModuleName OnboardingCommon -ParameterFilter { $Args -contains 'get' } {
            [pscustomobject]@{ value = @() }
        }
        Mock Get-AzJson -ModuleName OnboardingCommon -ParameterFilter { $Args -contains 'put' } {
            [pscustomobject]@{ properties = [pscustomobject]@{ status = 'Provisioned' } }
        }
    }

    It 'creates a time-bound AdminAssign eligibility request' {
        $result = Set-PimRoleEligibility -SubscriptionId 'sub-id' -PrincipalId 'user-id' `
            -RoleId 'reader-id' -Scope '/subscriptions/sub-id' -DurationDays 7

        $result.state | Should Be 'eligible-created'
        $result.requestStatus | Should Be 'Provisioned'
        $result.requiresActivation | Should Be $true
        Assert-MockCalled Get-AzJson -ModuleName OnboardingCommon -ParameterFilter { $Args -contains 'put' } -Times 1 -Scope It
        Assert-MockCalled Get-AzJson -ModuleName OnboardingCommon -ParameterFilter {
            $Args -contains 'put' -and
            ($Args -join ' ') -match '"requestType":"AdminAssign"' -and
            ($Args -join ' ') -match '"duration":"P7D"'
        } -Times 1 -Scope It
    }

    It 'reuses a current eligible assignment without creating another request' {
        Mock Get-AzJson -ModuleName OnboardingCommon -ParameterFilter { $Args -contains 'get' } {
            [pscustomobject]@{
                value = @([pscustomobject]@{
                        properties = [pscustomobject]@{ endDateTime = (Get-Date).ToUniversalTime().AddDays(3).ToString('o') }
                    })
            }
        }

        $result = Set-PimRoleEligibility -SubscriptionId 'sub-id' -PrincipalId 'user-id' `
            -RoleId 'reader-id' -Scope '/subscriptions/sub-id' -DurationDays 7

        $result.state | Should Be 'eligible-existing'
        $result.requiresActivation | Should Be $true
        Assert-MockCalled Get-AzJson -ModuleName OnboardingCommon -ParameterFilter { $Args -contains 'put' } -Times 0 -Scope It
    }

    It 'polls a pending request until eligibility is provisioned' {
        $global:PimRequestPoll = 0
        Mock Get-AzJson -ModuleName OnboardingCommon -ParameterFilter {
            $Args -contains 'get' -and ($Args -join ' ') -match 'roleEligibilityScheduleRequests'
        } {
            $global:PimRequestPoll++
            $status = if ($global:PimRequestPoll -eq 1) { 'PendingProvisioning' } else { 'Provisioned' }
            [pscustomobject]@{ properties = [pscustomobject]@{ status = $status } }
        }
        Mock Get-AzJson -ModuleName OnboardingCommon -ParameterFilter { $Args -contains 'put' } {
            [pscustomobject]@{ properties = [pscustomobject]@{ status = 'Accepted' } }
        }

        $result = Set-PimRoleEligibility -SubscriptionId 'sub-id' -PrincipalId 'user-id' `
            -RoleId 'reader-id' -Scope '/subscriptions/sub-id' -DurationDays 7 `
            -PollingIntervalSeconds 0 -MaxPollingAttempts 2

        $result.state | Should Be 'eligible-created'
        $result.requestStatus | Should Be 'Provisioned'
        $global:PimRequestPoll | Should Be 2
        Remove-Variable PimRequestPoll -Scope Global -ErrorAction SilentlyContinue
    }

    It 'rejects a missing request status' {
        Mock Get-AzJson -ModuleName OnboardingCommon -ParameterFilter { $Args -contains 'put' } {
            [pscustomobject]@{ properties = [pscustomobject]@{} }
        }

        $threw = $false
        try {
            Set-PimRoleEligibility -SubscriptionId 'sub-id' -PrincipalId 'user-id' `
                -RoleId 'reader-id' -Scope '/subscriptions/sub-id' -DurationDays 7 | Out-Null
        }
        catch {
            $threw = $true
            $_.Exception.Message | Should Match 'returned no status'
        }
        $threw | Should Be $true
    }

    It 'rejects an unrecognized request status' {
        Mock Get-AzJson -ModuleName OnboardingCommon -ParameterFilter { $Args -contains 'put' } {
            [pscustomobject]@{ properties = [pscustomobject]@{ status = 'FutureStatus' } }
        }

        $threw = $false
        try {
            Set-PimRoleEligibility -SubscriptionId 'sub-id' -PrincipalId 'user-id' `
                -RoleId 'reader-id' -Scope '/subscriptions/sub-id' -DurationDays 7 | Out-Null
        }
        catch {
            $threw = $true
            $_.Exception.Message | Should Match "unrecognized status 'FutureStatus'"
        }
        $threw | Should Be $true
    }

    It 'rejects a pending request that does not provision before the polling limit' {
        Mock Get-AzJson -ModuleName OnboardingCommon -ParameterFilter {
            $Args -contains 'get' -and ($Args -join ' ') -match 'roleEligibilityScheduleRequests'
        } {
            [pscustomobject]@{ properties = [pscustomobject]@{ status = 'PendingApproval' } }
        }
        Mock Get-AzJson -ModuleName OnboardingCommon -ParameterFilter { $Args -contains 'put' } {
            [pscustomobject]@{ properties = [pscustomobject]@{ status = 'PendingApproval' } }
        }

        $threw = $false
        try {
            Set-PimRoleEligibility -SubscriptionId 'sub-id' -PrincipalId 'user-id' `
                -RoleId 'reader-id' -Scope '/subscriptions/sub-id' -DurationDays 7 `
                -PollingIntervalSeconds 0 -MaxPollingAttempts 1 | Out-Null
        }
        catch {
            $threw = $true
            $_.Exception.Message | Should Match 'not provisioned after 1 polling attempts'
        }
        $threw | Should Be $true
    }
}

Describe 'Grant-OnboardingRole human JIT behavior' {
    BeforeEach {
        Mock Get-AzJson { @() }
        Mock Invoke-Az { [pscustomobject]@{} }
        Mock Set-PimRoleEligibility {
            [pscustomobject]@{
                state                      = 'eligible-created'
                roleDefinitionId           = 'reader-id'
                scope                      = '/subscriptions/sub-id'
                requestedEligibilityDurationDays = 7
                requiresActivation         = $true
            }
        }
    }

    It 'creates eligibility and passes when the User role is not activated yet' {
        $config = New-TestConfig -Mode 'customer-jit-managed' -DurationDays 7

        $result = Grant-OnboardingRole -PrincipalId 'user-id' -PrincipalType 'User' `
            -RoleName 'Reader' -RoleId 'reader-id' -Scope '/subscriptions/sub-id' `
            -ScopeLabel 'subscription' -Config $config

        $result.status | Should Be 'Pass'
        $result.data.state | Should Be 'eligible-created'
        $result.data.requiresActivation | Should Be $true
        (Test-AnyFailure -Results @($result)) | Should Be $false
        Assert-MockCalled Set-PimRoleEligibility -Times 1 -Scope It
        Assert-MockCalled Invoke-Az -Times 0 -Scope It
    }

    It 'still creates a workload identity assignment in customer JIT mode' {
        $config = New-TestConfig -Mode 'customer-jit-managed' -DurationDays 7

        $result = Grant-OnboardingRole -PrincipalId 'service-id' -PrincipalType 'ServicePrincipal' `
            -RoleName 'Reader' -RoleId 'reader-id' -Scope '/subscriptions/sub-id' `
            -ScopeLabel 'subscription' -Config $config

        $result.status | Should Be 'Pass'
        $result.data.state | Should Be 'created'
        Assert-MockCalled Set-PimRoleEligibility -ParameterFilter { $PrincipalId -eq 'service-id' } -Times 0 -Scope It
        Assert-MockCalled Invoke-Az -Times 1 -Scope It
    }

    It 'reports the actual expiry when reusing shorter existing eligibility' {
        Mock Set-PimRoleEligibility {
            [pscustomobject]@{
                state                              = 'eligible-existing'
                roleDefinitionId                   = 'reader-id'
                scope                              = '/subscriptions/sub-id'
                eligibilityEndDateTime             = '2026-10-18T00:00:00.0000000Z'
                requestedEligibilityDurationDays   = 7
                requiresActivation                 = $true
            }
        }
        $config = New-TestConfig -Mode 'customer-jit-managed' -DurationDays 7

        $result = Grant-OnboardingRole -PrincipalId 'user-id' -PrincipalType 'User' `
            -RoleName 'Reader' -RoleId 'reader-id' -Scope '/subscriptions/sub-id' `
            -ScopeLabel 'subscription' -Config $config

        $result.status | Should Be 'Pass'
        $result.detail | Should Match 'Reused existing PIM eligibility'
        $result.detail | Should Match '2026-10-18'
        $result.detail | Should Not Match 'for 7 days'
    }

    It 'fails explicitly when active assignments cannot be read in customer JIT mode' {
        Mock Get-AzJson { throw 'role assignment read denied' }
        $config = New-TestConfig -Mode 'customer-jit-managed' -DurationDays 7

        $result = Grant-OnboardingRole -PrincipalId 'user-id' -PrincipalType 'User' `
            -RoleName 'Reader' -RoleId 'reader-id' -Scope '/subscriptions/sub-id' `
            -ScopeLabel 'subscription' -Config $config

        $result.status | Should Be 'Fail'
        $result.detail | Should Match 'role assignment read denied'
        Assert-MockCalled Set-PimRoleEligibility -Times 0 -Scope It
    }
}

Describe 'Grant-FoundryRolesOnManagedRg human JIT behavior' {
    BeforeEach {
        $script:DiscoveryApiVersion = '2026-06-01'
        Mock Get-AzJson { @() }
        Mock Invoke-Az { 'managed-rg' }
        Mock Set-PimRoleEligibility {
            [pscustomobject]@{
                state                      = 'eligible-created'
                roleDefinitionId           = 'foundry-role-id'
                scope                      = '/subscriptions/sub/resourceGroups/managed-rg'
                requestedEligibilityDurationDays = 7
                requiresActivation         = $true
            }
        }
    }

    It 'creates Foundry eligibility without failing when the role is not active' {
        $config = New-TestConfig -Mode 'customer-jit-managed' -DurationDays 7

        $result = @(Grant-FoundryRolesOnManagedRg -Config $config -WorkspaceId '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/workspaces/ws')

        $roleResult = @($result | Where-Object { $_.id -like 'foundry-owner-mrg-*' })[0]
        $roleResult.status | Should Be 'Pass'
        $roleResult.data.state | Should Be 'eligible-created'
        @($result | Where-Object { $_.id -eq 'foundry-roles-pim-activation' })[0].status | Should Be 'Warn'
        Assert-MockCalled Set-PimRoleEligibility -Times 1 -Scope It
        Assert-MockCalled Invoke-Az -Times 1 -Scope It
    }
}
