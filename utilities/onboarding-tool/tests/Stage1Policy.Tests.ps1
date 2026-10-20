$scriptPath = Join-Path $PSScriptRoot '..\scripts\stage1-planning\stage1_plan.ps1'
$modulePath = Join-Path $PSScriptRoot '..\scripts\lib\OnboardingCommon.psm1'
Import-Module $modulePath -Force
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path $scriptPath),
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count) { throw ($errors.Message -join [Environment]::NewLine) }

foreach ($name in @('Get-Stage1PropertyValue', 'Get-LivePolicyAssignments')) {
    $functionAst = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
        }, $true)
    if (-not $functionAst) { throw "Function $name was not found in $scriptPath." }
    Invoke-Expression $functionAst.Extent.Text
}

Describe 'Get-LivePolicyAssignments' {
    BeforeEach {
        $script:definitionCalls = 0
    }

    It 'normalizes assignments that omit displayName and parameters' {
        Mock Get-AzJson -ParameterFilter { $Args -contains 'list' } {
            @([pscustomobject]@{
                    name               = 'assignment-one'
                    scope              = '/subscriptions/sub-id'
                    policyDefinitionId = '/providers/Microsoft.Authorization/policyDefinitions/definition-one'
                })
        }
        Mock Get-AzJson -ParameterFilter { $Args -contains 'show' } {
            [pscustomobject]@{
                policyType = 'BuiltIn'
                policyRule = [pscustomobject]@{
                    then = [pscustomobject]@{ effect = 'Deny' }
                }
            }
        }

        $result = @(Get-LivePolicyAssignments -SubscriptionId 'sub-id')

        $result.Count | Should Be 1
        $result[0].name | Should Be 'assignment-one'
        $result[0].displayName | Should Be 'assignment-one'
        $result[0].effect | Should Be 'Deny'
    }

    It 'uses a definition parameter default when assignment parameters are absent' {
        Mock Get-AzJson -ParameterFilter { $Args -contains 'list' } {
            @([pscustomobject]@{
                    name               = 'parameterized-assignment'
                    displayName        = 'Parameterized assignment'
                    scope              = '/subscriptions/sub-id'
                    policyDefinitionId = '/providers/Microsoft.Authorization/policyDefinitions/definition-two'
                })
        }
        Mock Get-AzJson -ParameterFilter { $Args -contains 'show' } {
            [pscustomobject]@{
                policyType = 'Custom'
                policyRule = [pscustomobject]@{
                    then = [pscustomobject]@{ effect = "[parameters('effect')]" }
                }
                parameters = [pscustomobject]@{
                    effect = [pscustomobject]@{ defaultValue = 'Audit' }
                }
            }
        }

        $result = @(Get-LivePolicyAssignments -SubscriptionId 'sub-id')

        $result[0].effect | Should Be 'Audit'
        $result[0].policyType | Should Be 'Custom'
    }

    It 'returns unknown values for a sparse assignment and definition instead of throwing' {
        Mock Get-AzJson -ParameterFilter { $Args -contains 'list' } {
            @([pscustomobject]@{ name = 'sparse-assignment' })
        }

        $result = @(Get-LivePolicyAssignments -SubscriptionId 'sub-id')

        $result.Count | Should Be 1
        $result[0].displayName | Should Be 'sparse-assignment'
        $result[0].policyType | Should Be 'Unknown'
        $result[0].effect | Should Be 'unknown'
        $result[0].scope | Should Be ''
    }

    It 'reads assignment parameter values from hashtable-shaped payloads' {
        Mock Get-AzJson -ParameterFilter { $Args -contains 'list' } {
            @([pscustomobject]@{
                    name               = 'hashtable-assignment'
                    parameters         = @{ effect = @{ value = 'Disabled' } }
                    policyDefinitionId = '/providers/Microsoft.Authorization/policyDefinitions/definition-three'
                })
        }
        Mock Get-AzJson -ParameterFilter { $Args -contains 'show' } {
            [pscustomobject]@{
                policyType = 'BuiltIn'
                policyRule = [pscustomobject]@{
                    then = [pscustomobject]@{ effect = "[parameters('effect')]" }
                }
            }
        }

        $result = @(Get-LivePolicyAssignments -SubscriptionId 'sub-id')

        $result[0].effect | Should Be 'Disabled'
    }
}
