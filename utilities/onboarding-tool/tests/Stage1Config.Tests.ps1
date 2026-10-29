$stage1Path = Join-Path $PSScriptRoot '..\scripts\stage1-planning\stage1_plan.ps1'
$modulePath = Join-Path $PSScriptRoot '..\scripts\lib\OnboardingCommon.psm1'
Import-Module $modulePath -Force
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path $stage1Path),
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count) { throw ($errors.Message -join [Environment]::NewLine) }
foreach ($name in @('Read-XlsxSheet', 'Split-CellRef', 'ConvertFrom-ConfigSheet', 'ConvertTo-ConfigModel', 'Merge-ConfigDefaults', 'Get-RequiredVmSkuResult', 'Test-Field', 'Get-Stage1PropertyValue', 'Get-LivePolicyAssignments', 'Invoke-Stage1Checks')) {
    $functionAst = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
        }, $true)
    if (-not $functionAst) { throw "$name was not found in $stage1Path." }
    Invoke-Expression $functionAst.Extent.Text
}
foreach ($statement in $ast.EndBlock.Statements) {
    if ($statement -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $statement.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and
        $statement.Left.VariablePath.UserPath -like 'script:*') {
        Invoke-Expression $statement.Extent.Text
    }
}

Describe 'Stage 1 existing VNet region alignment' {
    BeforeEach {
        $configPath = Join-Path (Split-Path -Parent $stage1Path) '..\examples\sample-config.json'
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        $defaults = ConvertTo-ConfigModel -Parsed ([pscustomobject]@{ Scalars = @{}; Subnets = @(); Policies = @(); Waivers = @() }) |
            ConvertTo-Json -Depth 20 | ConvertFrom-Json
        $config = Merge-ConfigDefaults -Config $config -Defaults $defaults
        $config.network.model = 'byo-existing'
        $script:existingVnet = [pscustomobject]@{
            id           = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/vnet'
            location     = 'uksouth'
            addressSpace = [pscustomobject]@{ addressPrefixes = @($config.network.vnetCidr) }
            subnets      = @($config.network.subnets | ForEach-Object {
                    [pscustomobject]@{ name = "snet-$($_.role)"; addressPrefix = $_.cidr }
                })
        }
        Mock Get-AzJson { $null }
        Mock Get-AzJson { [pscustomobject]@{ id = 'sub' } } -ParameterFilter { $Args[0] -eq 'account' }
        Mock Get-AzJson { $script:existingVnet } -ParameterFilter { $Args[0] -eq 'network' }
        Mock Get-VcpuQuotaResult {}
        Mock Get-ModelQuotaResult {}
        Mock Get-LivePolicyAssignments { @() }
    }

    It 'checks the workload region independently of the control plane' -TestCases @(
        @{ Control = 'eastus'; Workload = 'uksouth'; Expected = 'Pass' },
        @{ Control = 'uksouth'; Workload = 'uksouth'; Expected = 'Pass' },
        @{ Control = 'uksouth'; Workload = 'eastus'; Expected = 'Fail' }
    ) {
        param($Control, $Workload, $Expected)
        $config.controlPlaneRegion = $Control
        $config.workloadRegion = $Workload

        $result = Invoke-Stage1Checks -Cfg $config | Where-Object id -eq 'byo-vnet'

        $result.status | Should Be $Expected
        if ($Expected -eq 'Fail') {
            $result.remediation | Should Match "Set workloadRegion to 'uksouth'"
            $result.remediation | Should Not Match 'Set controlPlaneRegion'
        }
    }
}

Describe 'Stage 1 required VM SKU availability' {
    It 'pins the live SKU catalog query to the configured subscription' {
        $source = Get-Content -LiteralPath $stage1Path -Raw

        $source | Should Match "list-skus'.*'--subscription', [`$]Cfg.subscriptionId"
    }

    It 'passes only when both required SKUs are available without restrictions' {
        $result = Get-RequiredVmSkuResult -Region 'uksouth' -Skus @(
            [pscustomobject]@{ name = 'Standard_D4s_v6'; restrictions = $null },
            [pscustomobject]@{ name = 'Standard_D4ds_v6'; restrictions = $null },
            [pscustomobject]@{ name = 'Standard_B2s'; restrictions = @() }
        )

        $result.status | Should Be 'Pass'
        $result.detail | Should Match 'Standard_D4s_v6'
        $result.detail | Should Match 'Standard_D4ds_v6'
        $result.data.Count | Should Be 2
    }

    It 'fails when a required SKU is missing despite other SKUs being offered' {
        $result = Get-RequiredVmSkuResult -Region 'uksouth' -Skus @(
            [pscustomobject]@{ name = 'Standard_D4s_v6'; restrictions = @() },
            [pscustomobject]@{ name = 'Standard_B2s'; restrictions = @() }
        )

        $result.status | Should Be 'Fail'
        $result.detail | Should Match 'Standard_D4ds_v6.*not offered'
    }

    It 'fails when a required SKU is restricted for the subscription' {
        $result = Get-RequiredVmSkuResult -Region 'uksouth' -Skus @(
            [pscustomobject]@{ name = 'Standard_D4s_v6'; restrictions = @([pscustomobject]@{ reasonCode = 'NotAvailableForSubscription' }) },
            [pscustomobject]@{ name = 'Standard_D4ds_v6'; restrictions = @() }
        )

        $result.status | Should Be 'Fail'
        $result.detail | Should Match 'Standard_D4s_v6.*restricted'
    }

    It 'uses the effective Stage 4 SKU overrides' {
        $config = [pscustomobject]@{
            systemSku            = 'Standard_E8s_v5'
            nodePoolVmSize       = 'Standard_F16s_v2'
            nodePoolMaxNodeCount = 2
        }
        $result = Get-RequiredVmSkuResult -Region 'uksouth' -Config $config -Skus @(
            [pscustomobject]@{ name = 'Standard_E8s_v5'; restrictions = @() },
            [pscustomobject]@{ name = 'Standard_F16s_v2'; restrictions = @() }
        )

        $result.status | Should Be 'Pass'
        $result.detail | Should Match 'Standard_E8s_v5'
        $result.detail | Should Match 'Standard_F16s_v2'
    }

    It 'does not require a node-pool SKU when maximum nodes is zero' {
        $config = [pscustomobject]@{ nodePoolMaxNodeCount = 0 }
        $result = Get-RequiredVmSkuResult -Region 'uksouth' -Config $config -Skus @(
            [pscustomobject]@{ name = 'Standard_D4s_v6'; restrictions = @() }
        )

        $result.status | Should Be 'Pass'
        $result.data.Count | Should Be 1
    }
}

Describe 'Stage 1 planning form conversion' {
    It 'parses scalar, subnet, policy, and waiver rows' {
        $parsed = ConvertFrom-ConfigSheet -Cells @{
            A1 = 'subscriptionId'; B1 = ' sub '
            A2 = 'SUBNET'; B2 = ' nodepool '; C2 = ' 10.0.0.0/26 '; D2 = ' /26 '; E2 = ''
            A3 = 'POLICY'; B3 = ' policy-a '
            A4 = 'WAIVER'; B4 = ' check-a '; C4 = ' approved exception '; D4 = ' owner@example.com '
            A5 = 'Heading only'; B5 = 'ignored'
        }

        $parsed.Scalars.subscriptionId | Should Be 'sub'
        $parsed.Subnets[0].role | Should Be 'nodepool'
        $parsed.Subnets[0].delegation | Should Be 'none'
        $parsed.Policies[0] | Should Be 'policy-a'
        $parsed.Waivers[0].check | Should Be 'check-a'
        $parsed.Scalars.ContainsKey('Heading only') | Should Be $false
    }

    It 'normalizes booleans, CSV lists, integers, defaults, and JIT duration' {
        $parsed = [pscustomobject]@{
            Scalars = @{
                'subscriptionId'                  = 'sub'
                'rbac.humanAccessMode'            = 'customer-jit-managed'
                'rbac.jitEligibilityDurationDays' = '30'
                'deployingIdentity.canRegisterProviders' = 'yes'
                'network.corpDns'                 = '10.0.0.4, 10.0.0.5'
                'network.dnsResourceGroup'        = 'central-dns-rg'
                'workspace.networkIsolation'      = 'false'
                'bookshelf.instances'             = '2'
                'projects'                        = '3'
            }
            Subnets = @([pscustomobject]@{ role = 'nodepool'; cidr = '10.0.0.0/26'; requiredPrefix = '/26'; delegation = 'none' })
            Policies = @('policy-a')
            Waivers = @()
        }

        $model = ConvertTo-ConfigModel -Parsed $parsed

        $model.deployingIdentity.canRegisterProviders | Should Be $true
        $model.network.corpDns.Count | Should Be 2
        $model.network.dnsResourceGroup | Should Be 'central-dns-rg'
        $model.workspace.networkIsolation | Should Be $false
        $model.rbac.jitEligibilityDurationDays | Should Be '30'
        $model.bookshelf.instances | Should Be 2
        $model.projects | Should Be 3
        $model.network.model | Should Be 'byo'
    }

    It 'fills missing nested defaults without replacing supplied values' {
        $config = [pscustomobject]@{
            network = [pscustomobject]@{ model = 'managed' }
        }
        $defaults = [pscustomobject]@{
            network = [pscustomobject]@{
                model        = 'byo'
                outboundType = 'UserDefinedRouting'
            }
            projects = 1
        }

        $merged = Merge-ConfigDefaults -Config $config -Defaults $defaults

        $merged.network.model | Should Be 'managed'
        $merged.network.outboundType | Should Be 'UserDefinedRouting'
        $merged.projects | Should Be 1
    }

    It 'reads both shipped planning workbooks without an Excel dependency' {
        foreach ($fileName in @(
                'discovery-resource-planning-form-byo-vnet.xlsx',
                'discovery-resource-planning-form-managed-vnet.xlsx'
            )) {
            $path = Join-Path (Split-Path -Parent $stage1Path) $fileName
            $cells = Read-XlsxSheet -Path $path -SheetName 'Config'

            ($cells.Count -gt 0) | Should Be $true
            $parsed = ConvertFrom-ConfigSheet -Cells $cells
            $parsed.Scalars.ContainsKey('subscriptionId') | Should Be $true
            $parsed.Scalars.ContainsKey('rbac.humanAccessMode') | Should Be $true
            $parsed.Scalars.ContainsKey('network.dnsResourceGroup') | Should Be $true
        }
    }
}
