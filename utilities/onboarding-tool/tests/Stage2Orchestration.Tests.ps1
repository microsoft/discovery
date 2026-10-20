$modulePath = Join-Path $PSScriptRoot '..\scripts\lib\OnboardingCommon.psm1'
$stage2Path = Join-Path $PSScriptRoot '..\scripts\stage2-landing-zone\stage2_prepare.ps1'
Import-Module $modulePath -Force

$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path $stage2Path),
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count) { throw ($errors.Message -join [Environment]::NewLine) }
foreach ($name in @('Get-Stage2TargetResourceGroups', 'Get-Stage2PrivateDnsZones', 'New-Stage2NetworkParamFile', 'Invoke-Stage2Pipeline')) {
    $functionAst = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
        }, $true)
    if (-not $functionAst) { throw "$name was not found in $stage2Path." }
    Invoke-Expression $functionAst.Extent.Text
}

function Invoke-TestStage2Pass {
    param($Config, $ConfigPath, [switch]$PassThru, $JsonPath)
    $script:Stage2PassCalls++
    New-CheckResult -Id 'pass' -Name 'passing step' -Status 'Pass'
}

function Invoke-TestStage2Fail {
    param($Config, $ConfigPath, [switch]$PassThru, $JsonPath)
    $script:Stage2FailCalls++
    New-CheckResult -Id 'fail' -Name 'failing step' -Status 'Fail' -Detail 'expected failure' -Remediation 'fix expected failure'
}

function Invoke-TestStage2Throw {
    param($Config, $ConfigPath, [switch]$PassThru, $JsonPath)
    $script:Stage2ThrowCalls++
    throw 'unexpected step exception'
}

Describe 'Stage 2 fail-fast pipeline' {
    BeforeEach {
        $script:Stage2PassCalls = 0
        $script:Stage2FailCalls = 0
        $script:Stage2ThrowCalls = 0
    }

    It 'runs all steps when every step passes' {
        $results = [System.Collections.Generic.List[object]]::new()
        $steps = @(
            [pscustomobject]@{ ScriptName = 'first.ps1'; FunctionName = 'Invoke-TestStage2Pass' },
            [pscustomobject]@{ ScriptName = 'second.ps1'; FunctionName = 'Invoke-TestStage2Pass' }
        )

        $output = @(Invoke-Stage2Pipeline -Config @{} -ConfigPath 'config.json' -Results $results -Steps $steps)

        $script:Stage2PassCalls | Should Be 2
        @($output | Where-Object status -eq 'Fail').Count | Should Be 0
    }

    It 'stops immediately after the first returned failure' {
        $results = [System.Collections.Generic.List[object]]::new()
        $steps = @(
            [pscustomobject]@{ ScriptName = 'failing.ps1'; FunctionName = 'Invoke-TestStage2Fail' },
            [pscustomobject]@{ ScriptName = 'must-not-run.ps1'; FunctionName = 'Invoke-TestStage2Pass' }
        )

        $output = @(Invoke-Stage2Pipeline -Config @{} -ConfigPath 'config.json' -Results $results -Steps $steps)

        $script:Stage2FailCalls | Should Be 1
        $script:Stage2PassCalls | Should Be 0
        @($output | Where-Object { $_.id -eq 'stage2-stop-failing.ps1' }).Count | Should Be 1
    }

    It 'turns an exception into a failure and stops later steps' {
        $results = [System.Collections.Generic.List[object]]::new()
        $steps = @(
            [pscustomobject]@{ ScriptName = 'throwing.ps1'; FunctionName = 'Invoke-TestStage2Throw' },
            [pscustomobject]@{ ScriptName = 'must-not-run.ps1'; FunctionName = 'Invoke-TestStage2Pass' }
        )

        $output = @(Invoke-Stage2Pipeline -Config @{} -ConfigPath 'config.json' -Results $results -Steps $steps)

        $script:Stage2ThrowCalls | Should Be 1
        $script:Stage2PassCalls | Should Be 0
        @($output | Where-Object { $_.id -eq 'stage2-exception-throwing.ps1' })[0].detail | Should Match 'unexpected step exception'
    }

    It 'does not start any step when a prior login failure is already present' {
        $results = [System.Collections.Generic.List[object]]::new()
        $results.Add((New-CheckResult -Id 'login' -Name 'login' -Status 'Fail'))
        $steps = @([pscustomobject]@{ ScriptName = 'must-not-run.ps1'; FunctionName = 'Invoke-TestStage2Pass' })

        $null = Invoke-Stage2Pipeline -Config @{} -ConfigPath 'config.json' -Results $results -Steps $steps

        $script:Stage2PassCalls | Should Be 0
        $results.Count | Should Be 1
    }
}

Describe 'Stage 2 centralized DNS configuration' {
    It 'includes a distinct DNS resource group in the RBAC target set' {
        $config = [pscustomobject]@{
            resourceGroup = 'platform-rg'
            network       = [pscustomobject]@{
                networkResourceGroup = 'network-rg'
                dnsResourceGroup     = 'dns-rg'
            }
            storage       = [pscustomobject]@{
                accountId = '/subscriptions/sub/resourceGroups/storage-rg/providers/Microsoft.Storage/storageAccounts/data'
            }
        }

        $groups = @(Get-Stage2TargetResourceGroups -Config $config)

        $groups.Count | Should Be 4
        ($groups -contains 'dns-rg') | Should Be $true
    }

    It 'disables Bicep DNS creation when the DNS and VNet resource groups differ' {
        $config = [pscustomobject]@{
            network = [pscustomobject]@{
                networkResourceGroup = 'network-rg'
                dnsResourceGroup     = 'dns-rg'
                vnetCidr             = '10.0.0.0/23'
                outboundType         = 'LoadBalancer'
                subnets              = @()
            }
        }
        $path = New-Stage2NetworkParamFile -Config $config -VnetName 'vnet' -Location 'eastus'
        try {
            $parameters = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json

            $parameters.parameters.createPrivateDns.value | Should Be $false
            @($parameters.parameters.privateDnsZones.value).Count | Should BeGreaterThan 1
        }
        finally {
            Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        }
    }

    It 'keeps Bicep DNS creation enabled when DNS shares the VNet resource group' {
        $config = [pscustomobject]@{
            network = [pscustomobject]@{
                networkResourceGroup = 'network-rg'
                vnetCidr             = '10.0.0.0/23'
                outboundType         = 'LoadBalancer'
                subnets              = @()
            }
        }
        $path = New-Stage2NetworkParamFile -Config $config -VnetName 'vnet' -Location 'eastus'
        try {
            $parameters = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json

            $parameters.parameters.createPrivateDns.value | Should Be $true
        }
        finally {
            Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        }
    }
}
