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
$functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Invoke-NspPerimeterJoinerRole'
    }, $true)
if (-not $functionAst) { throw "Invoke-NspPerimeterJoinerRole was not found in $stage2Path." }
Invoke-Expression $functionAst.Extent.Text

function New-NspRole {
    param(
        [string]$Name = 'role-guid',
        [string]$RoleName = 'Discovery NSP Perimeter Joiner',
        [string[]]$Actions = @(
            'Microsoft.Network/networkSecurityPerimeters/joinPerimeterRule/action',
            'Microsoft.Network/locations/networkSecurityPerimeterOperationStatuses/read'
        ),
        [string[]]$NotActions = @()
    )
    [pscustomobject]@{
        name        = $Name
        roleName    = $RoleName
        permissions = @([pscustomobject]@{
                actions        = $Actions
                notActions     = $NotActions
                dataActions    = @()
                notDataActions = @()
            })
    }
}

function New-NspConfig {
    [pscustomobject]@{ subscriptionId = 'sub-id' }
}

Describe 'Invoke-NspPerimeterJoinerRole' {
    BeforeEach {
        $global:NspCanonicalRole = New-NspRole
        $global:NspRoleAfterCreate = New-NspRole
        $global:NspCanonicalLookups = 0
        $global:NspSp = [pscustomobject]@{ id = 'sp-object-id' }
        $global:NspJoinerAssignment = @([pscustomobject]@{ id = 'joiner-assignment' })
        $global:NspReaderAssignment = @([pscustomobject]@{ id = 'reader-assignment' })
        $global:NspAllAssignments = @()
        $global:NspEquivalentRole = $null

        Mock Assert-AzLogin {}
        Mock Get-AzJson { $global:NspSp } -ParameterFilter { $Args[0] -eq 'ad' }
        Mock Get-AzJson {
            $global:NspCanonicalLookups++
            @($global:NspCanonicalRole)
        } -ParameterFilter {
            $Args[0] -eq 'role' -and $Args[1] -eq 'definition' -and
            $Args -contains 'Discovery NSP Perimeter Joiner'
        }
        Mock Get-AzJson { @($global:NspEquivalentRole) } -ParameterFilter {
            $Args[0] -eq 'role' -and $Args[1] -eq 'definition' -and
            $global:NspEquivalentRole -and $Args -contains $global:NspEquivalentRole.roleName
        }
        Mock Get-AzJson { @($global:NspAllAssignments) } -ParameterFilter {
            $Args[0] -eq 'role' -and $Args[1] -eq 'assignment' -and $Args -notcontains '--role'
        }
        Mock Get-AzJson { @($global:NspReaderAssignment) } -ParameterFilter {
            $Args[0] -eq 'role' -and $Args[1] -eq 'assignment' -and
            $Args -contains 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
        }
        Mock Get-AzJson { @($global:NspJoinerAssignment) } -ParameterFilter {
            $Args[0] -eq 'role' -and $Args[1] -eq 'assignment' -and
            $Args -contains '--role' -and $Args -notcontains 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
        }
        Mock Get-AzJson { $null }
        Mock Invoke-Az { [pscustomobject]@{} }
    }

    AfterEach {
        Remove-Variable NspCanonicalRole, NspRoleAfterCreate, NspCanonicalLookups, NspSp, NspJoinerAssignment,
            NspReaderAssignment, NspAllAssignments, NspEquivalentRole `
            -Scope Global -ErrorAction SilentlyContinue
    }

    It 'reuses the exact role and both existing assignments without writes' {
        $result = @(Invoke-NspPerimeterJoinerRole -Config (New-NspConfig) -ConfigPath 'config.json' -PassThru)

        $result[0].status | Should Be 'Pass'
        $result[0].detail | Should Match 'state=exists'
        $result[0].detail | Should Match 'joinerAssignment=exists'
        $result[0].detail | Should Match 'readerAssignment=exists'
        Assert-MockCalled Invoke-Az -Times 0 -Scope It
    }

    It 'creates a missing role and missing joiner and Reader assignments' {
        $global:NspCanonicalRole = $null
        $global:NspJoinerAssignment = @()
        $global:NspReaderAssignment = @()
        Mock Get-AzJson -ParameterFilter {
            $Args[0] -eq 'role' -and $Args[1] -eq 'definition' -and
            $Args -contains '--name' -and $Args -contains 'Discovery NSP Perimeter Joiner'
        } {
            param($Args)
            $global:NspCanonicalLookups++
            if ($global:NspCanonicalLookups -eq 1) { return @() }
            return @($global:NspRoleAfterCreate)
        }

        $result = @(Invoke-NspPerimeterJoinerRole -Config (New-NspConfig) -ConfigPath 'config.json' -PassThru)

        $result[0].status | Should Be 'Pass'
        $result[0].detail | Should Match 'created-or-updated'
        $result[0].detail | Should Match 'joinerAssignment=created'
        $result[0].detail | Should Match 'readerAssignment=created'
        Assert-MockCalled Invoke-Az -ParameterFilter { $Args[0] -eq 'role' -and $Args[1] -eq 'definition' -and $Args[2] -eq 'create' } -Times 1 -Scope It
        Assert-MockCalled Invoke-Az -ParameterFilter { $Args[0] -eq 'role' -and $Args[1] -eq 'assignment' -and $Args[2] -eq 'create' } -Times 2 -Scope It
    }

    It 'updates a role whose permission shape differs' {
        $global:NspCanonicalRole = New-NspRole -Actions @('Microsoft.Network/networkSecurityPerimeters/joinPerimeterRule/action') -NotActions @('Microsoft.Network/*/delete')

        $result = @(Invoke-NspPerimeterJoinerRole -Config (New-NspConfig) -ConfigPath 'config.json' -PassThru)

        $result[0].status | Should Be 'Pass'
        Assert-MockCalled Invoke-Az -ParameterFilter { $Args[0] -eq 'role' -and $Args[1] -eq 'definition' -and $Args[2] -eq 'update' } -Times 1 -Scope It
    }

    It 'reuses a differently named equivalent role after an inaccessible name collision' {
        $global:NspCanonicalRole = $null
        $global:NspEquivalentRole = New-NspRole -Name 'equivalent-guid' -RoleName 'Approved Discovery NSP Role'
        $global:NspAllAssignments = @([pscustomobject]@{ roleDefinitionName = 'Approved Discovery NSP Role' })
        Mock Invoke-Az { throw 'RoleDefinitionWithSameNameExists' } -ParameterFilter {
            $Args[0] -eq 'role' -and $Args[1] -eq 'definition'
        }

        $result = @(Invoke-NspPerimeterJoinerRole -Config (New-NspConfig) -ConfigPath 'config.json' -PassThru)

        $result[0].status | Should Be 'Pass'
        $result[0].data.roleName | Should Be 'Approved Discovery NSP Role'
        $result[0].detail | Should Match 'existing-equivalent'
    }

    It 'fails clearly when a collided name has no assigned equivalent role' {
        $global:NspCanonicalRole = $null
        Mock Invoke-Az { throw 'RoleDefinitionWithSameNameExists' } -ParameterFilter {
            $Args[0] -eq 'role' -and $Args[1] -eq 'definition'
        }

        $result = @(Invoke-NspPerimeterJoinerRole -Config (New-NspConfig) -ConfigPath 'config.json' -PassThru)

        $result[0].status | Should Be 'Fail'
        $result[0].detail | Should Match 'name is already in use elsewhere in the tenant'
    }

    It 'fails when the Discovery service principal cannot be resolved' {
        $global:NspSp = $null

        $result = @(Invoke-NspPerimeterJoinerRole -Config (New-NspConfig) -ConfigPath 'config.json' -PassThru)

        $result[0].status | Should Be 'Fail'
        $result[0].detail | Should Match 'Control-plane service principal not found'
    }

    It 'removes its temporary role-definition file when creation fails' {
        $global:NspCanonicalRole = $null
        Mock Invoke-Az { throw 'role definition write denied' } -ParameterFilter {
            $Args[0] -eq 'role' -and $Args[1] -eq 'definition'
        }
        $before = @(Get-ChildItem ([IO.Path]::GetTempPath()) -Filter 'discovery-nsp-joiner-*.json').FullName

        $result = @(Invoke-NspPerimeterJoinerRole -Config (New-NspConfig) -ConfigPath 'config.json' -PassThru)
        $after = @(Get-ChildItem ([IO.Path]::GetTempPath()) -Filter 'discovery-nsp-joiner-*.json').FullName

        $result[0].status | Should Be 'Fail'
        @($after | Where-Object { $_ -notin $before }).Count | Should Be 0
    }
}
