$modulePath = Join-Path $PSScriptRoot '..\scripts\lib\OnboardingCommon.psm1'
Import-Module $modulePath -Force

Describe 'Physical workload VNet region validation' {
    It 'accepts a workload VNet independently of the control-plane location' {
        $config = [pscustomobject]@{ controlPlaneRegion = 'eastus'; workloadRegion = 'eastus2' }
        Test-WorkloadVNetRegion -WorkloadRegion $config.workloadRegion -VNetRegion 'eastus2' | Should Be $true
    }

    It 'retains same-region behavior' {
        Test-WorkloadVNetRegion -WorkloadRegion 'eastus' -VNetRegion 'eastus' | Should Be $true
    }

    It 'rejects a VNet in the control plane when the workload override differs' {
        Test-WorkloadVNetRegion -WorkloadRegion 'centralus' -VNetRegion 'eastus' | Should Be $false
    }

    It 'does not treat missing region evidence as a match' {
        Test-WorkloadVNetRegion -WorkloadRegion 'centralus' -VNetRegion '' | Should Be $false
        Test-WorkloadVNetRegion -WorkloadRegion '' -VNetRegion 'centralus' | Should Be $false
    }

    It 'compares canonical Azure short names without case or whitespace sensitivity' {
        Test-WorkloadVNetRegion -WorkloadRegion ' CentralUS ' -VNetRegion 'centralus' | Should Be $true
    }

    It 'uses the shared workload guard in planning and both Stage 4 deployment paths' {
        $stage1 = Get-Content (Join-Path $PSScriptRoot '..\scripts\stage1-planning\stage1_plan.ps1') -Raw
        $stage4 = Get-Content (Join-Path $PSScriptRoot '..\scripts\stage4-deployment\stage4_deploy.ps1') -Raw
        $stage1 | Should Match 'Test-WorkloadVNetRegion -WorkloadRegion \$Cfg.workloadRegion -VNetRegion \$loc'
        ([regex]::Matches($stage4, 'Test-WorkloadVNetRegion -WorkloadRegion \$workloadRegion -VNetRegion')).Count | Should Be 2
        $stage4 | Should Not Match '\$preflightRegion -ne \$location|\$subnetRegion -ne \$location'
    }
}
