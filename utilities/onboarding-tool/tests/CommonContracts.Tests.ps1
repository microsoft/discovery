$modulePath = Join-Path $PSScriptRoot '..\scripts\lib\OnboardingCommon.psm1'
Import-Module $modulePath -Force

function New-QuotaConfig {
    param([hashtable]$Overrides = @{})
    $config = [ordered]@{
        subscriptionId = '00000000-0000-0000-0000-000000000000'
        workloadRegion = 'eastus'
    }
    foreach ($key in $Overrides.Keys) { $config[$key] = $Overrides[$key] }
    [pscustomobject]$config
}

function New-VcpuUsage {
    param([string]$Name, [int]$Available)
    [pscustomobject]@{
        name         = [pscustomobject]@{ value = $Name }
        currentValue = 0
        limit        = $Available
    }
}

function New-VmSku {
    param([string]$Name, [string]$Family, [int]$Vcpus)
    [pscustomobject]@{
        name         = $Name
        family       = $Family
        restrictions = $null
        capabilities = @([pscustomobject]@{ name = 'vCPUs'; value = "$Vcpus" })
    }
}

Describe 'CIDR helpers' {
    It 'calculates the full IPv4 range for a slash zero network' {
        $info = Get-CidrInfo -Cidr '10.1.2.3/0'

        $info.Network | Should Be 0
        $info.Broadcast | Should Be 4294967295
        $info.Count | Should Be 4294967296
    }

    It 'calculates one address for a slash 32 network' {
        $info = Get-CidrInfo -Cidr '10.1.2.3/32'

        $info.Network | Should Be $info.Broadcast
        $info.Count | Should Be 1
    }

    It 'rejects malformed CIDR and invalid prefixes' {
        foreach ($cidr in @('10.0.0.0', '10.0.0.0/33', 'not-an-ip/24')) {
            $threw = $false
            try { Get-CidrInfo -Cidr $cidr | Out-Null }
            catch { $threw = $true }
            $threw | Should Be $true
        }
    }

    It 'recognizes containment including an exact boundary' {
        Test-CidrContains -Outer '10.0.0.0/24' -Inner '10.0.0.0/24' | Should Be $true
        Test-CidrContains -Outer '10.0.0.0/24' -Inner '10.0.1.0/24' | Should Be $false
    }

    It 'distinguishes overlap from adjacent networks' {
        Test-CidrOverlap -A '10.0.0.0/24' -B '10.0.0.128/25' | Should Be $true
        Test-CidrOverlap -A '10.0.0.0/25' -B '10.0.0.128/25' | Should Be $false
    }
}

Describe 'Get-VcpuQuotaResult' {
    BeforeEach {
        $global:OnboardingVcpuUsage = $null
        $global:OnboardingSkuCatalog = @(
            (New-VmSku -Name 'Standard_D4s_v6' -Family 'StandardDsv6Family' -Vcpus 4),
            (New-VmSku -Name 'Standard_D4ds_v6' -Family 'StandardDdsv6Family' -Vcpus 4)
        )
        Mock Get-AzJson -ModuleName OnboardingCommon { $global:OnboardingSkuCatalog } `
            -ParameterFilter { $Args -contains 'list-skus' }
        Mock Get-AzJson -ModuleName OnboardingCommon { $global:OnboardingVcpuUsage } `
            -ParameterFilter { $Args -contains 'list-usage' }
    }

    AfterEach {
        Remove-Variable OnboardingVcpuUsage -Scope Global -ErrorAction SilentlyContinue
        Remove-Variable OnboardingSkuCatalog -Scope Global -ErrorAction SilentlyContinue
    }

    It 'passes at the exact system and node-pool boundaries' {
        $global:OnboardingVcpuUsage = @(
            (New-VcpuUsage -Name 'cores' -Available 24),
            (New-VcpuUsage -Name 'StandardDsv6Family' -Available 12),
            (New-VcpuUsage -Name 'StandardDdsv6Family' -Available 12)
        )

        $result = Get-VcpuQuotaResult -Config (New-QuotaConfig) -Fr 'FR1.5' -SkuCatalog $global:OnboardingSkuCatalog

        $result.status | Should Be 'Pass'
        $result.detail | Should Match 'Total Regional vCPUs 24 available \(24 limit - 0 used; need 24\)'
        $result.detail | Should Match 'StandardDsv6Family.*12 available'
        $result.detail | Should Match 'StandardDdsv6Family.*12 available'
        $result.data.requirements.Count | Should Be 2
        $result.data.quotas.Count | Should Be 3
    }

    It 'fails when total regional quota cannot run the system pool' {
        $global:OnboardingVcpuUsage = @(
            (New-VcpuUsage -Name 'cores' -Available 11),
            (New-VcpuUsage -Name 'StandardDsv6Family' -Available 12),
            (New-VcpuUsage -Name 'StandardDdsv6Family' -Available 12)
        )

        $result = Get-VcpuQuotaResult -Config (New-QuotaConfig) -Fr 'FR1.5' -SkuCatalog $global:OnboardingSkuCatalog

        $result.status | Should Be 'Fail'
        @($result.data | Where-Object blocking).Count | Should Be 1
    }

    It 'fails when the system VM-family quota is missing' {
        $global:OnboardingVcpuUsage = @(
            (New-VcpuUsage -Name 'cores' -Available 24),
            (New-VcpuUsage -Name 'StandardDdsv6Family' -Available 12)
        )

        (Get-VcpuQuotaResult -Config (New-QuotaConfig) -Fr 'FR1.5' -SkuCatalog $global:OnboardingSkuCatalog).status | Should Be 'Fail'
    }

    It 'warns when deployment fits but node-pool autoscale does not' {
        $global:OnboardingVcpuUsage = @(
            (New-VcpuUsage -Name 'cores' -Available 12),
            (New-VcpuUsage -Name 'StandardDsv6Family' -Available 12),
            (New-VcpuUsage -Name 'StandardDdsv6Family' -Available 0)
        )

        (Get-VcpuQuotaResult -Config (New-QuotaConfig) -Fr 'FR1.5' -SkuCatalog $global:OnboardingSkuCatalog).status | Should Be 'Warn'
    }

    It 'warns when compute usage cannot be read' {
        $global:OnboardingVcpuUsage = $null

        (Get-VcpuQuotaResult -Config (New-QuotaConfig) -Fr 'FR1.5' -SkuCatalog $global:OnboardingSkuCatalog).status | Should Be 'Warn'
    }

    It 'calculates quota from effective SKU and node-count overrides' {
        $global:OnboardingSkuCatalog = @(
            (New-VmSku -Name 'Standard_E8s_v5' -Family 'StandardESv5Family' -Vcpus 8),
            (New-VmSku -Name 'Standard_F16s_v2' -Family 'StandardFSv2Family' -Vcpus 16)
        )
        $global:OnboardingVcpuUsage = @(
            (New-VcpuUsage -Name 'cores' -Available 56),
            (New-VcpuUsage -Name 'StandardESv5Family' -Available 24),
            (New-VcpuUsage -Name 'StandardFSv2Family' -Available 32)
        )
        $config = New-QuotaConfig -Overrides @{
            systemSku               = 'Standard_E8s_v5'
            nodePoolVmSize          = 'Standard_F16s_v2'
            nodePoolMaxNodeCount    = 2
        }

        $result = Get-VcpuQuotaResult -Config $config -Fr 'FR1.5' -SkuCatalog $global:OnboardingSkuCatalog

        $result.status | Should Be 'Pass'
        @($result.data.requirements | Where-Object sku -eq 'Standard_E8s_v5')[0].vcpus | Should Be 24
        @($result.data.requirements | Where-Object sku -eq 'Standard_F16s_v2')[0].vcpus | Should Be 32
    }

    It 'does not require node-pool SKU or quota when maximum nodes is zero' {
        $global:OnboardingSkuCatalog = @(
            (New-VmSku -Name 'Standard_D4s_v6' -Family 'StandardDsv6Family' -Vcpus 4)
        )
        $global:OnboardingVcpuUsage = @(
            (New-VcpuUsage -Name 'cores' -Available 12),
            (New-VcpuUsage -Name 'StandardDsv6Family' -Available 12)
        )

        $result = Get-VcpuQuotaResult -Config (New-QuotaConfig -Overrides @{ nodePoolMaxNodeCount = 0 }) -Fr 'FR1.5' -SkuCatalog $global:OnboardingSkuCatalog

        $result.status | Should Be 'Pass'
        $result.data.requirements.Count | Should Be 1
        $result.data.quotas.Count | Should Be 2
    }

    It 'combines system and node requirements when both SKUs use the same family' {
        $global:OnboardingSkuCatalog = @(
            (New-VmSku -Name 'Standard_D4s_v6' -Family 'StandardDsv6Family' -Vcpus 4),
            (New-VmSku -Name 'Standard_D8s_v6' -Family 'StandardDsv6Family' -Vcpus 8)
        )
        $global:OnboardingVcpuUsage = @(
            (New-VcpuUsage -Name 'cores' -Available 36),
            (New-VcpuUsage -Name 'StandardDsv6Family' -Available 36)
        )
        $config = New-QuotaConfig -Overrides @{ nodePoolVmSize = 'Standard_D8s_v6'; nodePoolMaxNodeCount = 3 }

        $result = Get-VcpuQuotaResult -Config $config -Fr 'FR1.5' -SkuCatalog $global:OnboardingSkuCatalog

        $result.status | Should Be 'Pass'
        $result.data.quotas.Count | Should Be 2
        @($result.data.quotas | Where-Object quota -eq 'StandardDsv6Family')[0].required | Should Be 36
    }

    It 'pins SKU and usage reads to the configured subscription' {
        $global:OnboardingVcpuUsage = @(
            (New-VcpuUsage -Name 'cores' -Available 24),
            (New-VcpuUsage -Name 'StandardDsv6Family' -Available 12),
            (New-VcpuUsage -Name 'StandardDdsv6Family' -Available 12)
        )

        (Get-VcpuQuotaResult -Config (New-QuotaConfig) -Fr 'FR1.5').status | Should Be 'Pass'

        Assert-MockCalled Get-AzJson -ModuleName OnboardingCommon -Scope It -Times 1 -Exactly `
            -ParameterFilter { $Args -contains 'list-skus' -and $Args -contains '--subscription' -and $Args -contains '00000000-0000-0000-0000-000000000000' }
        Assert-MockCalled Get-AzJson -ModuleName OnboardingCommon -Scope It -Times 1 -Exactly `
            -ParameterFilter { $Args -contains 'list-usage' -and $Args -contains '--subscription' -and $Args -contains '00000000-0000-0000-0000-000000000000' }
    }
}

Describe 'Onboarding report contract' {
    It 'writes matching JSON and Markdown with a NO-GO verdict' {
        $jsonPath = Join-Path $TestDrive 'nested\stage.json'
        $results = @(
            (New-CheckResult -Id 'pass' -Name 'pass check' -Status 'Pass' -Fr 'FRX'),
            (New-CheckResult -Id 'fail' -Name 'fail check' -Status 'Fail' -Fr 'FRX' -Detail "line one|line two" -Remediation 'fix it'),
            (New-CheckResult -Id 'warn' -Name 'warn check' -Status 'Warn' -Fr 'FRX'),
            (New-CheckResult -Id 'skip' -Name 'skip check' -Status 'Skip' -Fr 'FRX'),
            (New-CheckResult -Id 'waived' -Name 'waived check' -Status 'Waived' -Fr 'FRX')
        )

        $summary = Write-OnboardingReport -Results $results -Title 'Contract test' -JsonPath $jsonPath -Extra @{ run = 'unit' }
        $json = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json
        $markdown = Get-Content -LiteralPath ([IO.Path]::ChangeExtension($jsonPath, '.md')) -Raw

        $summary.verdict | Should Be 'NO-GO'
        $json.total | Should Be 5
        $json.pass | Should Be 1
        $json.fail | Should Be 1
        $json.warn | Should Be 1
        $json.skip | Should Be 1
        $json.waived | Should Be 1
        $json.extra.run | Should Be 'unit'
        $markdown | Should Match 'NO-GO'
        $markdown | Should Match 'line one\\|line two'
    }

    It 'reports GO when failures are absent' {
        $summary = Write-OnboardingReport -Results @(
            (New-CheckResult -Id 'pass' -Name 'pass' -Status 'Pass'),
            (New-CheckResult -Id 'warn' -Name 'warn' -Status 'Warn')
        ) -Title 'GO test'

        $summary.verdict | Should Be 'GO'
    }
}
