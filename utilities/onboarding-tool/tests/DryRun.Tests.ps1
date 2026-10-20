$scriptsRoot = Join-Path $PSScriptRoot '..\scripts'
$sampleConfig = Join-Path $scriptsRoot 'examples\sample-config.json'
$stageScripts = @(
    'stage2-landing-zone\stage2_prepare.ps1',
    'stage3-validation\stage3_validate.ps1',
    'stage4-deployment\stage4_deploy.ps1',
    'stage5-scenario-enablement\stage5_enable.ps1'
)

Describe 'Offline stage plans' {
    BeforeEach {
        $global:OnboardingDryRunCalls = [System.Collections.Generic.List[string]]::new()
        function global:az {
            $global:OnboardingDryRunCalls.Add('az')
            throw 'Azure CLI must not run during an offline plan.'
        }
        Mock Invoke-WebRequest {
            $global:OnboardingDryRunCalls.Add('http')
            throw 'HTTP must not run during an offline plan.'
        }
        Mock Invoke-RestMethod {
            $global:OnboardingDryRunCalls.Add('rest')
            throw 'HTTP must not run during an offline plan.'
        }
    }

    AfterEach {
        Remove-Item Function:\az
        Remove-Variable OnboardingDryRunCalls -Scope Global
    }

    It 'exposes offline dry-run behavior through parameter help for every stage' {
        foreach ($script in $stageScripts) {
            $help = Get-Help (Join-Path $scriptsRoot $script) -Parameter DryRun
            ($help.description.Text -join ' ') | Should Match 'offline'
            ($help.description.Text -join ' ') | Should Match 'PLAN'
        }
    }

    It 'returns only unexecuted Skip results for all four stages without external calls' {
        foreach ($script in $stageScripts) {
            $results = @(& (Join-Path $scriptsRoot $script) -ConfigPath $sampleConfig -DryRun -PassThru)
            ($results.Count -gt 1) | Should Be $true
            @($results | Where-Object status -ne 'Skip').Count | Should Be 0
            foreach ($result in $results | Select-Object -Skip 1) {
                $result.data.dryRun | Should Be $true
                $result.data.executed | Should Be $false
            }
        }
        $global:OnboardingDryRunCalls.Count | Should Be 0
    }

    It 'writes PLAN reports rather than GO or certification evidence for every stage' {
        for ($i = 0; $i -lt $stageScripts.Count; $i++) {
            $path = Join-Path $TestDrive "stage-$i.json"
            & (Join-Path $scriptsRoot $stageScripts[$i]) -ConfigPath $sampleConfig -DryRun -JsonPath $path
            $report = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
            $report.verdict | Should Be 'PLAN'
            $report.pass | Should Be 0
            $report.extra.dryRun | Should Be $true
            $report.extra.stage | Should Be ($i + 2)
            $markdown = Get-Content -LiteralPath ([IO.Path]::ChangeExtension($path, '.md')) -Raw
            $markdown | Should Match 'PLAN - offline dry run only'
            $markdown | Should Not Match '\*\*GO\*\*|CERTIFIED'
        }
        $global:OnboardingDryRunCalls.Count | Should Be 0
        @(Get-ChildItem $TestDrive -Filter 'stage5-state-*').Count | Should Be 0
        @(Get-ChildItem $TestDrive -Filter 'stage5-response-*').Count | Should Be 0
    }

    It 'honors profile selection and plans VM creation and cleanup only with WithVm' {
        $script = Join-Path $scriptsRoot $stageScripts[1]
        $results = @(& $script -ConfigPath $sampleConfig -DryRun -PassThru -Profile bookshelf -WithVm)
        $results[0].data.options.Profile | Should Be 'bookshelf'
        $results[0].data.options.WithVm | Should Be $true
        @($results | Where-Object id -like '*check_quota').Count | Should Be 0
        ($results | Where-Object id -eq 'plan-stage3-testvm').detail | Should Match 'Create a temporary VM.*cleanup'
        $results = @(& $script -ConfigPath $sampleConfig -DryRun -PassThru)
        $results[0].data.options.Profile | Should Be 'supercomputer'
        @($results | Where-Object id -like '*check_quota').Count | Should Be 1
        ($results | Where-Object id -eq 'plan-stage3-testvm').detail | Should Match 'Skip'
        $global:OnboardingDryRunCalls.Count | Should Be 0
    }

    It 'writes no reports when PassThru is used even with JsonPath' {
        foreach ($script in $stageScripts) {
            $path = Join-Path $TestDrive ([IO.Path]::GetFileNameWithoutExtension($script) + '-suppressed.json')
            $results = @(& (Join-Path $scriptsRoot $script) -ConfigPath $sampleConfig -DryRun -PassThru -JsonPath $path)
            ($results.Count -gt 1) | Should Be $true
            Test-Path -LiteralPath $path | Should Be $false
            Test-Path -LiteralPath ([IO.Path]::ChangeExtension($path, '.md')) | Should Be $false
        }
        $global:OnboardingDryRunCalls.Count | Should Be 0
    }

    It 'rejects a generated Stage 3 plan at the actual Stage 4 readiness gate' {
        $planPath = Join-Path $TestDrive 'readiness-plan.json'
        & (Join-Path $scriptsRoot $stageScripts[1]) -ConfigPath $sampleConfig -DryRun -JsonPath $planPath
        $tokens = $null
        $errors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile(
            (Join-Path $scriptsRoot $stageScripts[2]), [ref]$tokens, [ref]$errors)
        $errors.Count | Should Be 0
        $helper = $ast.Find({
                param($node)
                $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-ObjProp'
            }, $true)
        Invoke-Expression $helper.Extent.Text
        $gate = $ast.EndBlock.Statements | Where-Object {
            $_ -is [System.Management.Automation.Language.IfStatementAst] -and
            $_.Clauses[0].Item1.Extent.Text -eq '$ReadinessReport'
        }
        $ReadinessReport = @($planPath)
        $readinessGateOpen = $true
        $results = [System.Collections.Generic.List[object]]::new()
        . ([scriptblock]::Create($gate.Extent.Text))
        $readinessGateOpen | Should Be $false
        @($results | Where-Object status -eq 'Fail').Count | Should Be 1
        $results[0].detail | Should Match 'verdict=PLAN'
        $global:OnboardingDryRunCalls.Count | Should Be 0
    }

    It 'plans targeted recovery without entering the recovery executor' {
        $results = @(& (Join-Path $scriptsRoot $stageScripts[2]) -ConfigPath $sampleConfig -DryRun -PassThru `
            -Recovery -Subscription 'override-sub' -ResourceGroup 'override-rg' -Workspace 'override-ws')
        $results[0].data.subscriptionId | Should Be 'override-sub'
        $results[0].data.resourceGroup | Should Be 'override-rg'
        $results[0].data.names.workspace | Should Be 'override-ws'
        @($results | Where-Object id -eq 'plan-stage4-recovery').Count | Should Be 1
        @($results | Where-Object id -eq 'plan-stage4-deploy').Count | Should Be 0
        $global:OnboardingDryRunCalls.Count | Should Be 0
    }

    It 'preserves Stage 5 target and prompt overrides without inference' {
        $results = @(& (Join-Path $scriptsRoot $stageScripts[3]) -ConfigPath $sampleConfig -DryRun -PassThru `
            -ResourceGroup 'other-rg' -Workspace 'other-ws' -Project 'other-project' -ChatModel 'other-model' -Prompt 'Test question')
        $results[0].data.resourceGroup | Should Be 'other-rg'
        $results[0].data.names.workspace | Should Be 'other-ws'
        $results[0].data.names.project | Should Be 'other-project'
        $results[0].data.names.chatModel | Should Be 'other-model'
        $results[0].data.options.Prompt | Should Be 'Test question'
        $global:OnboardingDryRunCalls.Count | Should Be 0
    }

    It 'describes existing networking without promising a network deployment' {
        $config = Get-Content -LiteralPath $sampleConfig -Raw | ConvertFrom-Json
        $config.network.model = 'byo-existing'
        $path = Join-Path $TestDrive 'existing.json'
        $config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $path
        $results = @(& (Join-Path $scriptsRoot $stageScripts[0]) -ConfigPath $path -DryRun -PassThru)
        ($results | Where-Object id -eq 'plan-stage2-network').detail | Should Match 'Skip network deployment'
    }

    It 'fails on missing or invalid config without producing a success-shaped plan' {
        $invalid = Join-Path $TestDrive 'invalid.json'
        $malformed = Join-Path $TestDrive 'malformed.json'
        '{}' | Set-Content -LiteralPath $invalid
        '{"schemaVersion":' | Set-Content -LiteralPath $malformed
        foreach ($script in $stageScripts) {
            $stagePath = Join-Path $scriptsRoot $script
            foreach ($configPath in @($invalid, $malformed, (Join-Path $TestDrive 'missing.json'))) {
                $threw = $false
                try { & $stagePath -ConfigPath $configPath -DryRun -PassThru }
                catch { $threw = $true }
                $threw | Should Be $true
            }
        }
        $global:OnboardingDryRunCalls.Count | Should Be 0
    }

    It 'returns actual process exit codes for valid, missing, malformed and invalid config' {
        $pwsh = (Get-Process -Id $PID).Path
        $invalid = Join-Path $TestDrive 'cli-invalid.json'
        $malformed = Join-Path $TestDrive 'cli-malformed.json'
        '{}' | Set-Content -LiteralPath $invalid
        '{"schemaVersion":' | Set-Content -LiteralPath $malformed
        foreach ($script in $stageScripts) {
            $path = Join-Path $scriptsRoot $script
            $output = & $pwsh -NoProfile -File $path -ConfigPath $sampleConfig -DryRun 2>&1
            $LASTEXITCODE | Should Be 0
            ($output -join "`n") | Should Match 'Verdict: PLAN'
            foreach ($configPath in @($invalid, $malformed, (Join-Path $TestDrive 'cli-missing.json'))) {
                $output = & $pwsh -NoProfile -File $path -ConfigPath $configPath -DryRun 2>&1
                ($LASTEXITCODE -ne 0) | Should Be $true
                ($output -join "`n") | Should Not Match 'Verdict: PLAN|Verdict: GO'
            }
        }
    }
}
