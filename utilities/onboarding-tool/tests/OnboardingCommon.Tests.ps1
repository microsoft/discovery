$modulePath = Join-Path $PSScriptRoot '..\scripts\lib\OnboardingCommon.psm1'
Import-Module $modulePath -Force

Describe 'Get-ModelQuotaResult' {
    $config = [pscustomobject]@{
        subscriptionId = '00000000-0000-0000-0000-000000000000'
        workloadRegion = 'uksouth'
    }

    function Set-QuotaMocks {
        param(
            [object[]]$Usage,
            [object[]]$Models,
            [string]$UsageError = '',
            [string]$ModelsError = ''
        )
        $global:OnboardingTestUsage = $Usage
        $global:OnboardingTestModels = $Models
        $global:OnboardingTestUsageError = $UsageError
        $global:OnboardingTestModelsError = $ModelsError
        Mock Get-AzJsonResult -ModuleName OnboardingCommon -ParameterFilter { $Args -contains 'usage' } {
            [pscustomobject]@{
                succeeded = [string]::IsNullOrWhiteSpace($global:OnboardingTestUsageError)
                data      = $global:OnboardingTestUsage
                error     = $global:OnboardingTestUsageError
            }
        }
        Mock Get-AzJsonResult -ModuleName OnboardingCommon -ParameterFilter { $Args -contains 'model' } {
            [pscustomobject]@{
                succeeded = [string]::IsNullOrWhiteSpace($global:OnboardingTestModelsError)
                data      = $global:OnboardingTestModels
                error     = $global:OnboardingTestModelsError
            }
        }
    }

    AfterEach {
        Remove-Variable OnboardingTestUsage, OnboardingTestModels, OnboardingTestUsageError, OnboardingTestModelsError -Scope Global -ErrorAction SilentlyContinue
    }

    function New-QuotaUsage {
        param(
            [object]$Current = 0,
            [object]$Limit = 1000,
            [AllowEmptyString()][string]$Status = ''
        )
        [pscustomobject]@{
            name         = [pscustomobject]@{ value = 'OpenAI.GlobalStandard.gpt-5.4' }
            currentValue = $Current
            limit        = $Limit
            status       = $Status
        }
    }

    function New-ModelRecord {
        param(
            [string]$Version = '2026-03-05',
            [string]$Kind = 'OpenAI',
            [bool]$Default = $true,
            [string]$Sku = 'GlobalStandard',
            [object]$TokenRate = 1000,
            [object]$RenewalPeriod = 60,
            [AllowEmptyString()][string]$Lifecycle = 'GenerallyAvailable'
        )
        [pscustomobject]@{
            kind  = $Kind
            model = [pscustomobject]@{
                name             = 'gpt-5.4'
                version          = $Version
                isDefaultVersion = $Default
                lifecycleStatus  = $Lifecycle
                skus             = @([pscustomobject]@{
                        name       = $Sku
                        usageName  = if ($Sku -eq 'GlobalStandard') { 'OpenAI.GlobalStandard.gpt-5.4' } else { "OpenAI.$Sku" }
                        rateLimits = @([pscustomobject]@{
                                key           = 'token'
                                renewalPeriod = $RenewalPeriod
                                count         = $TokenRate
                                rules         = $null
                            })
                    })
            }
        }
    }

    It 'passes at exactly 450K free' {
        Set-QuotaMocks -Usage @(New-QuotaUsage -Current 550 -Limit 1000) -Models @(New-ModelRecord)

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        $result.status | Should Be 'Pass'
        $result.data.available | Should Be 450
        $result.detail | Should Match 'Catalog and quota prerequisites satisfied at check time'
    }

    It 'accepts the flattened token key returned by Azure CLI' {
        Set-QuotaMocks -Usage @(New-QuotaUsage) -Models @(New-ModelRecord)

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        $result.status | Should Be 'Pass'
    }

    It 'also accepts the nested token rule from the documented SDK shape' {
        $model = New-ModelRecord
        $model.model.skus[0].rateLimits[0].key = $null
        $model.model.skus[0].rateLimits[0].rules = @([pscustomobject]@{ key = 'token' })
        Set-QuotaMocks -Usage @(New-QuotaUsage) -Models @($model)

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        $result.status | Should Be 'Pass'
    }

    It 'accepts the unlabeled rate-limit shape returned by Azure CLI' {
        $model = New-ModelRecord
        $model.model.skus[0].rateLimits = @(
            [pscustomobject]@{ count = 10.0; renewalPeriod = 60.0; rules = $null },
            [pscustomobject]@{ count = 1000.0; renewalPeriod = 60.0; rules = $null }
        )
        Set-QuotaMocks -Usage @(New-QuotaUsage -Current 3100 -Limit 4000) -Models @($model)

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR3.6e'

        $result.status | Should Be 'Pass'
        $result.data.available | Should Be 900
        $result.data.quotaUnit | Should Be '1K TPM'
    }

    It 'does not treat an unrelated unlabeled one-minute rate limit as the quota conversion' {
        $model = New-ModelRecord
        $model.model.skus[0].rateLimits = @(
            [pscustomobject]@{ count = 10.0; renewalPeriod = 60.0; rules = $null }
        )
        Set-QuotaMocks -Usage @(New-QuotaUsage) -Models @($model)

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR3.6e'

        $result.status | Should Be 'Fail'
        $result.detail | Should Match 'one capacity unit to 1,000 tokens per minute'
    }

    It 'prefers explicit token metadata over an unlabeled fallback' {
        $model = New-ModelRecord -TokenRate 2000
        $model.model.skus[0].rateLimits += [pscustomobject]@{
            count = 1000.0
            renewalPeriod = 60.0
            rules = $null
        }
        Set-QuotaMocks -Usage @(New-QuotaUsage) -Models @($model)

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR3.6e'

        $result.status | Should Be 'Fail'
        $result.detail | Should Match 'one capacity unit to 1,000 tokens per minute'
    }

    It 'fails at 449K free' {
        Set-QuotaMocks -Usage @(New-QuotaUsage -Current 551 -Limit 1000) -Models @(New-ModelRecord)

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        $result.status | Should Be 'Fail'
        $result.data.available | Should Be 449
    }

    It 'pins usage and model calls to the configured subscription' {
        Set-QuotaMocks -Usage @(New-QuotaUsage) -Models @(New-ModelRecord)

        $null = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        Assert-MockCalled Get-AzJsonResult -ModuleName OnboardingCommon -Times 2 -ParameterFilter {
            $Args -contains '--subscription' -and $Args -contains $config.subscriptionId
        }
    }

    It 'selects the default OpenAI version independent of response order' {
        $models = @(
            (New-ModelRecord -Version '2026-01-01' -Default $false),
            (New-ModelRecord -Version '2026-03-05' -Default $true),
            (New-ModelRecord -Version '2026-03-05' -Kind 'AIServices' -Default $true)
        )
        Set-QuotaMocks -Usage @(New-QuotaUsage) -Models $models

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        $result.status | Should Be 'Pass'
        $result.data.modelVersion | Should Be '2026-03-05'
    }

    It 'filters by SKU before preferring a default version' {
        $models = @(
            (New-ModelRecord -Version '2026-04-01' -Default $true -Sku 'ProvisionedManaged'),
            (New-ModelRecord -Version '2026-03-05' -Default $false -Sku 'GlobalStandard')
        )
        Set-QuotaMocks -Usage @(New-QuotaUsage) -Models $models

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        $result.status | Should Be 'Pass'
        $result.data.modelVersion | Should Be '2026-03-05'
    }

    It 'falls back to the latest compatible version when no compatible default exists' {
        $models = @(
            (New-ModelRecord -Version '2026-01-01' -Default $false),
            (New-ModelRecord -Version '2026-05-01' -Default $false),
            (New-ModelRecord -Version '2026-03-05' -Default $false)
        )
        Set-QuotaMocks -Usage @(New-QuotaUsage) -Models $models

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        $result.status | Should Be 'Pass'
        $result.data.modelVersion | Should Be '2026-05-01'
    }

    It 'distinguishes a missing quota entry from an unreadable usage call' {
        Set-QuotaMocks -Usage @([pscustomobject]@{ name = [pscustomobject]@{ value = 'another-quota' } }) -Models @(New-ModelRecord)
        (Get-ModelQuotaResult -Config $config -Fr 'FR1.5').status | Should Be 'Fail'

        Set-QuotaMocks -Usage @() -Models @(New-ModelRecord) -UsageError 'AuthorizationFailed'
        $unreadable = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'
        $unreadable.status | Should Be 'Warn'
        $unreadable.detail | Should Match 'AuthorizationFailed'
    }

    It 'makes an unreadable Stage 3 check blocking' {
        Set-QuotaMocks -Usage @() -Models @(New-ModelRecord) -UsageError 'Network timeout'

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR3.6e'

        $result.status | Should Be 'Fail'
        $result.detail | Should Match 'Network timeout'
    }

    It 'distinguishes blocked and unknown quota statuses' {
        Set-QuotaMocks -Usage @(New-QuotaUsage -Status 'Blocked') -Models @(New-ModelRecord)
        (Get-ModelQuotaResult -Config $config -Fr 'FR1.5').status | Should Be 'Fail'

        Set-QuotaMocks -Usage @(New-QuotaUsage -Status 'FutureStatus') -Models @(New-ModelRecord)
        (Get-ModelQuotaResult -Config $config -Fr 'FR1.5').status | Should Be 'Warn'
    }

    It 'returns unverified for malformed or nonnumeric quota values' {
        Set-QuotaMocks -Usage @(New-QuotaUsage -Current 'not-a-number') -Models @(New-ModelRecord)

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        $result.status | Should Be 'Warn'
        $result.detail | Should Match 'invalid usage values'
    }

    It 'returns unverified instead of crashing when quota fields are missing' {
        $usage = [pscustomobject]@{
            name  = [pscustomobject]@{ value = 'OpenAI.GlobalStandard.gpt-5.4' }
            limit = 1000
        }
        Set-QuotaMocks -Usage @($usage) -Models @(New-ModelRecord)

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        $result.status | Should Be 'Warn'
        $result.detail | Should Match "currentValue=''"
    }

    It 'handles incomplete catalog records without strict-mode errors' {
        $models = @(
            [pscustomobject]@{ kind = 'OpenAI'; model = [pscustomobject]@{ name = 'gpt-5.4' } },
            (New-ModelRecord)
        )
        Set-QuotaMocks -Usage @(New-QuotaUsage) -Models $models

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        $result.status | Should Be 'Pass'
    }

    It 'does not assume missing lifecycle metadata means GA' {
        Set-QuotaMocks -Usage @(New-QuotaUsage) -Models @(New-ModelRecord -Lifecycle '')

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        $result.status | Should Be 'Warn'
        $result.detail | Should Match 'did not report lifecycleStatus'
    }

    It 'does not assume quota values are in 1K TPM units' {
        Set-QuotaMocks -Usage @(New-QuotaUsage) -Models @(New-ModelRecord -TokenRate 2000)

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        $result.status | Should Be 'Warn'
        $result.detail | Should Match 'one capacity unit to 1,000 tokens per minute'
    }

    It 'returns unverified for a nonnumeric token rate count' {
        Set-QuotaMocks -Usage @(New-QuotaUsage) -Models @(New-ModelRecord -TokenRate 'not-a-number')

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR1.5'

        $result.status | Should Be 'Warn'
        $result.detail | Should Match "count='not-a-number'"
    }

    It 'blocks Stage 3 for a nonnumeric token rate renewal period' {
        Set-QuotaMocks -Usage @(New-QuotaUsage) -Models @(New-ModelRecord -RenewalPeriod 'not-a-number')

        $result = Get-ModelQuotaResult -Config $config -Fr 'FR3.6e'

        $result.status | Should Be 'Fail'
        $result.detail | Should Match "renewalPeriod='not-a-number'"
    }

    It 'counts only allocations still needed on a resumed deployment' {
        $resumeConfig = [pscustomobject]@{
            subscriptionId = $config.subscriptionId
            workloadRegion = $config.workloadRegion
            resourceGroup  = 'rg-test'
            names          = [pscustomobject]@{ workspace = 'ws-test' }
        }
        Mock Get-DiscoveryResourceStateForQuota -ModuleName OnboardingCommon -ParameterFilter {
            $ResourceId -notmatch 'chatModelDeployments'
        } { 'Succeeded' }
        Mock Get-DiscoveryResourceStateForQuota -ModuleName OnboardingCommon -ParameterFilter {
            $ResourceId -match 'chatModelDeployments'
        } { 'NotFound' }
        Set-QuotaMocks -Usage @(New-QuotaUsage -Current 800 -Limit 1000) -Models @(New-ModelRecord)

        $result = Get-ModelQuotaResult -Config $resumeConfig -Fr 'FR3.6e'

        $result.status | Should Be 'Pass'
        $result.data.required | Should Be 200
        $result.data.workspaceState | Should Be 'Succeeded'
        $result.data.chatModelState | Should Be 'NotFound'
    }
}

Describe 'Get-AzJsonResult' {
    It 'forces JSON output when the caller does not specify an output format' {
        Mock Invoke-Az -ModuleName OnboardingCommon { '[]' }

        $result = & (Get-Module OnboardingCommon) {
            Get-AzJsonResult -Args @('cognitiveservices', 'usage', 'list', '-l', 'uksouth')
        }

        $result.succeeded | Should Be $true
        Assert-MockCalled Invoke-Az -ModuleName OnboardingCommon -Times 1 -ParameterFilter {
            $Args -contains '-o' -and $Args -contains 'json'
        }
    }
}
