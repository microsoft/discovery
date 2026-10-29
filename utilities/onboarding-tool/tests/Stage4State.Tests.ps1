$modulePath = Join-Path $PSScriptRoot '..\scripts\lib\OnboardingCommon.psm1'
$stage4Path = Join-Path $PSScriptRoot '..\scripts\stage4-deployment\stage4_deploy.ps1'
Import-Module $modulePath -Force

$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path $stage4Path),
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count) { throw ($errors.Message -join [Environment]::NewLine) }
foreach ($name in @(
        'Get-WorkspacePublicNetworkAccess',
        'Get-WorkspaceNetworkIsolation',
        'Get-ObjProp',
        'Get-ConfigName',
        'Get-Stage4VNetName',
        'Get-SubnetIdByRole',
        'Get-VNetRegionFromSubnetId',
        'Get-Stage4NetworkRegionFailures',
        'Get-ManagedIdentityId',
        'Get-StorageAccountId',
        'New-Stage4BicepParamFile',
        'Resolve-DiscoveryError',
        'Get-DiscoveryArmState',
        'Get-FoundryAccountState',
        'Test-DiscoveryTrueState'
    )) {
    $functionAst = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
        }, $true)
    if (-not $functionAst) { throw "$name was not found in $stage4Path." }
    Invoke-Expression $functionAst.Extent.Text
}

Describe 'Stage 4 workload and VNet region alignment' {
    BeforeEach {
        $configPath = Join-Path (Split-Path -Parent $stage4Path) '..\examples\sample-config.json'
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        $config.controlPlaneRegion = 'eastus'
        $config.workloadRegion = 'uksouth'
        Mock Get-VNetRegionFromSubnetId { 'uksouth' }
    }

    It 'allows separate control-plane and workload regions' {
        @(Get-Stage4NetworkRegionFailures -Config $config -ResourceGroup $config.resourceGroup).Count | Should Be 0
    }

    It 'preserves same-region deployments' {
        $config.controlPlaneRegion = 'uksouth'

        @(Get-Stage4NetworkRegionFailures -Config $config -ResourceGroup $config.resourceGroup).Count | Should Be 0
    }

    It 'rejects a subnet in the control-plane region instead of the workload region' -TestCases @(
        @{ Role = 'managedcluster' },
        @{ Role = 'nodepool' },
        @{ Role = 'agent-containerapp' },
        @{ Role = 'workspace-containerapp' },
        @{ Role = 'search-containerapp' },
        @{ Role = 'private-endpoints' },
        @{ Role = 'spare' }
    ) {
        param($Role)
        $script:mismatchedRole = $Role
        Mock Get-VNetRegionFromSubnetId { 'eastus' } -ParameterFilter { $SubnetId -like "*/snet-$script:mismatchedRole" }

        $failures = @(Get-Stage4NetworkRegionFailures -Config $config -ResourceGroup $config.resourceGroup)

        $failures.Count | Should Be 1
        $failures[0].status | Should Be 'Fail'
        $failures[0].data.role | Should Be $Role
        $failures[0].data.expected | Should Be 'uksouth'
        $failures[0].data.actual | Should Be 'eastus'
        $failures[0].remediation | Should Match 'controlPlaneRegion can differ'
    }

    It 'fails explicitly when the VNet region cannot be read' {
        Mock Get-VNetRegionFromSubnetId { '' }

        $failures = @(Get-Stage4NetworkRegionFailures -Config $config -ResourceGroup $config.resourceGroup)

        ($failures.Count -gt 0) | Should Be $true
        $failures[0].detail | Should Match 'Could not resolve VNet region'
    }

    It 'does not validate the unused management subnet with LoadBalancer egress' {
        $config.network.outboundType = 'LoadBalancer'
        Mock Get-VNetRegionFromSubnetId { 'eastus' } -ParameterFilter { $SubnetId -like '*/snet-spare' }

        @(Get-Stage4NetworkRegionFailures -Config $config -ResourceGroup $config.resourceGroup).Count | Should Be 0
    }

    It 'keeps the control-plane location and MRG workload region separate in Bicep parameters' {
        $path = New-Stage4BicepParamFile -Config $config -ResourceGroup $config.resourceGroup -Location $config.controlPlaneRegion
        try {
            $parameters = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json

            $parameters.parameters.location.value | Should Be 'eastus'
            $parameters.parameters.workloadRegion.value | Should Be 'uksouth'
        }
        finally {
            Remove-Item -LiteralPath $path -Force
        }
    }
}

Describe 'Stage 4 workspace configuration defaults' {
    It 'uses secure network-isolation and explicit public-access defaults' {
        $config = [pscustomobject]@{}

        Get-WorkspaceNetworkIsolation -Config $config | Should Be $true
        Get-WorkspacePublicNetworkAccess -Config $config | Should Be 'Enabled'
    }

    It 'honors configured workspace networking values' {
        $config = [pscustomobject]@{
            workspace = [pscustomobject]@{
                networkIsolation   = $false
                publicNetworkAccess = 'Disabled'
            }
        }

        Get-WorkspaceNetworkIsolation -Config $config | Should Be $false
        Get-WorkspacePublicNetworkAccess -Config $config | Should Be 'Disabled'
    }

    It 'rejects unsupported public-access values by returning the documented default' {
        $config = [pscustomobject]@{
            workspace = [pscustomobject]@{ publicNetworkAccess = 'Invalid' }
        }

        Get-WorkspacePublicNetworkAccess -Config $config | Should Be 'Enabled'
    }
}

Describe 'Test-DiscoveryTrueState' {
    BeforeEach {
        Mock Start-Sleep {}
        Mock Get-DiscoveryArmState { 'Succeeded' }
        Mock Get-FoundryAccountState { 'Succeeded' }
    }

    It 'passes when ARM succeeds and no Foundry account check is requested' {
        $result = Test-DiscoveryTrueState -ResourceId '/resource/id' -TimeoutMinutes 0 -PollSeconds 0

        $result.verdict | Should Be 'Pass'
        $result.trueState | Should Be 'Succeeded'
        $result.source | Should Be 'arm'
    }

    It 'does not let a succeeded Foundry account override failed ARM state' {
        Mock Get-DiscoveryArmState { 'Failed' }

        $result = Test-DiscoveryTrueState -ResourceId '/resource/id' -AccountName 'foundry' -ResourceGroup 'managed-rg' -TimeoutMinutes 0 -PollSeconds 0

        $result.verdict | Should Be 'Fail'
        $result.trueState | Should Be 'Failed'
    }

    It 'times out when ARM succeeds but Foundry remains creating' {
        Mock Get-FoundryAccountState { 'Creating' }

        $result = Test-DiscoveryTrueState -ResourceId '/resource/id' -AccountName 'foundry' -ResourceGroup 'managed-rg' -TimeoutMinutes 0 -PollSeconds 0

        $result.verdict | Should Be 'Fail'
        $result.trueState | Should Be 'TimedOut:Creating'
        $result.timedOut | Should Be $true
    }

    It 'polls a transient ARM state until it succeeds' {
        $global:Stage4ArmStateCall = 0
        Mock Get-DiscoveryArmState {
            $global:Stage4ArmStateCall++
            if ($global:Stage4ArmStateCall -eq 1) { 'Creating' } else { 'Succeeded' }
        }

        $result = Test-DiscoveryTrueState -ResourceId '/resource/id' -TimeoutMinutes 1 -PollSeconds 0

        $result.verdict | Should Be 'Pass'
        $result.trueState | Should Be 'Succeeded'
        Assert-MockCalled Start-Sleep -Times 1 -Scope It
        Remove-Variable Stage4ArmStateCall -Scope Global -ErrorAction SilentlyContinue
    }

    It 'fails when the ARM resource is not found' {
        Mock Get-DiscoveryArmState { 'NotFound' }

        $result = Test-DiscoveryTrueState -ResourceId '/resource/id' -TimeoutMinutes 0 -PollSeconds 0

        $result.verdict | Should Be 'Fail'
        $result.trueState | Should Be 'NotFound'
    }
}

Describe 'Resolve-DiscoveryError' {
    It 'maps model quota errors' {
        (Resolve-DiscoveryError -ErrorText 'InsufficientQuota: Tokens Per Minute').errorSignature |
            Should Match 'Insufficient model TPM quota'
    }

    It 'maps VM-family quota errors' {
        (Resolve-DiscoveryError -ErrorText 'VmSkuQuota exceeded').errorSignature |
            Should Match 'Insufficient VM quota'
    }

    It 'maps regional creation and subnet-region failures separately' {
        (Resolve-DiscoveryError -ErrorText 'Creation of new Supercomputer resources is not supported in region').errorSignature |
            Should Be 'Creation not supported in region'
        (Resolve-DiscoveryError -ErrorText 'RegionMismatch for dependent resource SubnetId').errorSignature |
            Should Match 'RegionMismatch'
    }

    It 'does not require changing the control-plane region to resolve a subnet-region mismatch' {
        $result = Resolve-DiscoveryError -ErrorText 'RegionMismatch for dependent resource SubnetId'

        $result.remediation | Should Match 'set workloadRegion'
        $result.remediation | Should Not Match 'set controlPlaneRegion'
    }

    It 'maps policy failures by affected resource type' {
        (Resolve-DiscoveryError -ErrorText 'RequestDisallowedByPolicy Microsoft.CognitiveServices/accounts publicNetworkAccess').errorSignature |
            Should Match 'Foundry'
        (Resolve-DiscoveryError -ErrorText 'RequestDisallowedByPolicy Microsoft.OperationalInsights workspaces').errorSignature |
            Should Match 'Log Analytics'
        (Resolve-DiscoveryError -ErrorText 'RequestDisallowedByPolicy Microsoft.Storage storage account publicNetworkAccess').errorSignature |
            Should Match 'Storage'
    }

    It 'returns an explicit unmatched result for unknown failures' {
        $result = Resolve-DiscoveryError -ErrorText 'an entirely new failure'

        $result.matched | Should Be $false
        $result.errorSignature | Should Be 'unrecognized signature'
        $result.remediation | Should Match 'add a new'
    }
}
