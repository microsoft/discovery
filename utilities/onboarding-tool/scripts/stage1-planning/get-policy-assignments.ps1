<#
.DESCRIPTION
Retrieves Azure Policy assignments that apply to a subscription, including assignments
inherited from management groups. Resolves policy and initiative definitions, configured
effects, parameters, scope, enforcement, version, location, and identity details, then
writes the results to a subscription-specific JSON file in the script directory.

.PARAMETER SubscriptionId
The Azure subscription ID to query. If omitted, the script prompts for the ID.

.EXAMPLE
PS> az login
PS> .\get-policy-assignments.ps1

Sign in to Azure, run the script, and enter the target subscription ID when prompted.
The script requires permission to read policy assignments and definitions. Results are
saved as policy-assignments-<subscription-id>.json in the script directory.

.EXAMPLE
PS> .\get-policy-assignments.ps1 -SubscriptionId '00000000-0000-0000-0000-000000000000'

Runs the script for the specified Azure subscription without prompting for its ID.
#>

[CmdletBinding()]
param(
    [Guid] $SubscriptionId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI (az) is not installed or is not available on PATH.'
}

function Invoke-AzJson {
    param(
        [Parameter(Mandatory)]
        [string[]] $Arguments
    )

    $json = & az @Arguments --output json
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Arguments -join ' ')"
    }

    return $json | ConvertFrom-Json
}

function Get-ObjectPropertyValue {
    param(
        [AllowNull()]
        [object] $InputObject,

        [Parameter(Mandatory)]
        [string] $Name
    )

    if ($null -eq $InputObject) {
        return $null
    }

    $property = $InputObject.PSObject.Properties |
        Where-Object Name -EQ $Name |
        Select-Object -First 1

    if ($null -eq $property) {
        return $null
    }

    return $property.Value
}

function Get-ResourcePropertyValue {
    param(
        [Parameter(Mandatory)]
        [object] $Resource,

        [Parameter(Mandatory)]
        [string] $Name
    )

    $value = Get-ObjectPropertyValue -InputObject $Resource -Name $Name
    if ($null -ne $value) {
        return $value
    }

    $properties = Get-ObjectPropertyValue -InputObject $Resource -Name 'properties'
    return Get-ObjectPropertyValue -InputObject $properties -Name $Name
}

function Get-ParameterValue {
    param(
        [AllowNull()]
        [object] $Parameters,

        [Parameter(Mandatory)]
        [string] $Name
    )

    if ($null -eq $Parameters) {
        return $null
    }

    $parameterProperty = $Parameters.PSObject.Properties |
        Where-Object Name -EQ $Name |
        Select-Object -First 1

    if ($null -eq $parameterProperty) {
        return $null
    }

    $valueProperty = $parameterProperty.Value.PSObject.Properties['value']
    if ($null -ne $valueProperty) {
        return $valueProperty.Value
    }

    return $parameterProperty.Value
}

function Get-ParameterDefaultValue {
    param(
        [AllowNull()]
        [object] $ParameterDefinitions,

        [Parameter(Mandatory)]
        [string] $Name
    )

    if ($null -eq $ParameterDefinitions) {
        return $null
    }

    $parameterProperty = $ParameterDefinitions.PSObject.Properties |
        Where-Object Name -EQ $Name |
        Select-Object -First 1

    if ($null -eq $parameterProperty) {
        return $null
    }

    $defaultValueProperty = $parameterProperty.Value.PSObject.Properties['defaultValue']
    if ($null -eq $defaultValueProperty) {
        return $null
    }

    return $defaultValueProperty.Value
}

function ConvertTo-ParameterMap {
    param(
        [AllowNull()]
        [object] $Parameters
    )

    if ($null -eq $Parameters) {
        return [pscustomobject] @{}
    }

    $parameterMap = [ordered] @{}
    foreach ($parameter in $Parameters.PSObject.Properties) {
        $valueProperty = $parameter.Value.PSObject.Properties['value']
        $parameterMap[$parameter.Name] = if ($null -ne $valueProperty) {
            $valueProperty.Value
        }
        else {
            $parameter.Value
        }
    }

    return [pscustomobject] $parameterMap
}

function Resolve-PolicyEffect {
    param(
        [AllowNull()]
        [object] $Effect,

        [AllowNull()]
        [object] $ParameterValues,

        [AllowNull()]
        [object] $ParameterDefinitions
    )

    if ($null -eq $Effect) {
        return $null
    }

    $effectText = [string] $Effect
    if ($effectText -notmatch "^\[parameters\('([^']+)'\)\]$") {
        return $effectText
    }

    $parameterName = $Matches[1]
    $configuredValue = Get-ParameterValue -Parameters $ParameterValues -Name $parameterName
    if ($null -eq $configuredValue) {
        $configuredValue = Get-ParameterDefaultValue `
            -ParameterDefinitions $ParameterDefinitions `
            -Name $parameterName
    }

    if ($null -eq $configuredValue -or [string] $configuredValue -eq $effectText) {
        return $effectText
    }

    return Resolve-PolicyEffect `
        -Effect $configuredValue `
        -ParameterValues $ParameterValues `
        -ParameterDefinitions $ParameterDefinitions
}

if ($SubscriptionId -eq [Guid]::Empty) {
    do {
        $subscriptionIdInput = Read-Host 'Enter the Azure subscription ID'
        $parsedSubscriptionId = [Guid]::Empty
        $isValidSubscriptionId = [Guid]::TryParse(
            $subscriptionIdInput,
            [ref] $parsedSubscriptionId
        )

        if (-not $isValidSubscriptionId) {
            Write-Warning 'Enter a valid subscription ID in GUID format.'
        }
    } until ($isValidSubscriptionId)

    $SubscriptionId = $parsedSubscriptionId
}

$scope = "/subscriptions/$subscriptionId"
$outputPath = Join-Path $PSScriptRoot "policy-assignments-$subscriptionId.json"
$policyDefinitionCache = @{}
$policySetDefinitionCache = @{}

$policyAssignments = Invoke-AzJson -Arguments @(
    'policy',
    'assignment',
    'list',
    '--scope',
    $scope,
    '--disable-scope-strict-match',
    'true',
    '--expand',
    'LatestDefinitionVersion,EffectiveDefinitionVersion'
)

$results = foreach ($assignment in $policyAssignments) {
    $assignmentScope = Get-ResourcePropertyValue -Resource $assignment -Name 'scope'
    if ([string]::IsNullOrWhiteSpace($assignmentScope)) {
        throw 'A policy assignment response did not contain a scope.'
    }

    if ($assignmentScope -ne $scope -and
        -not $assignmentScope.StartsWith('/providers/Microsoft.Management/managementGroups/')) {
        continue
    }

    $definitionId = Get-ResourcePropertyValue -Resource $assignment -Name 'policyDefinitionId'
    if ([string]::IsNullOrWhiteSpace($definitionId)) {
        throw "Policy assignment at scope '$assignmentScope' did not contain a policy definition ID."
    }

    $assignmentParameters = Get-ResourcePropertyValue -Resource $assignment -Name 'parameters'
    $assignmentParameterMap = ConvertTo-ParameterMap -Parameters $assignmentParameters
    $definitionType = 'Policy'
    $memberPolicies = @()
    $configuredEffect = $null

    if ($definitionId -match '/policySetDefinitions/') {
        $definitionType = 'Initiative'
        if (-not $policySetDefinitionCache.ContainsKey($definitionId)) {
            $policySetDefinitionResource = Invoke-AzJson -Arguments @(
                'rest',
                '--method',
                'get',
                '--url',
                "${definitionId}?api-version=2023-04-01"
            )
            $policySetDefinitionCache[$definitionId] = Get-ObjectPropertyValue `
                -InputObject $policySetDefinitionResource `
                -Name 'properties'
        }

        $policySetDefinition = $policySetDefinitionCache[$definitionId]
        $policySetParameters = Get-ObjectPropertyValue `
            -InputObject $policySetDefinition `
            -Name 'parameters'
        $policyReferences = Get-ObjectPropertyValue `
            -InputObject $policySetDefinition `
            -Name 'policyDefinitions'

        foreach ($policyReference in $policyReferences) {
            $referencedDefinitionId = Get-ObjectPropertyValue `
                -InputObject $policyReference `
                -Name 'policyDefinitionId'
            if (-not $policyDefinitionCache.ContainsKey($referencedDefinitionId)) {
                $policyDefinitionResource = Invoke-AzJson -Arguments @(
                    'rest',
                    '--method',
                    'get',
                    '--url',
                    "${referencedDefinitionId}?api-version=2023-04-01"
                )
                $policyDefinitionCache[$referencedDefinitionId] = Get-ObjectPropertyValue `
                    -InputObject $policyDefinitionResource `
                    -Name 'properties'
            }

            $policyDefinition = $policyDefinitionCache[$referencedDefinitionId]
            $policyDefinitionParameters = Get-ObjectPropertyValue `
                -InputObject $policyDefinition `
                -Name 'parameters'
            $policyReferenceParameters = Get-ObjectPropertyValue `
                -InputObject $policyReference `
                -Name 'parameters'
            $policyRule = Get-ObjectPropertyValue -InputObject $policyDefinition -Name 'policyRule'
            $thenClause = Get-ObjectPropertyValue -InputObject $policyRule -Name 'then'
            $definitionEffect = Get-ObjectPropertyValue -InputObject $thenClause -Name 'effect'
            $effect = Resolve-PolicyEffect `
                -Effect $definitionEffect `
                -ParameterValues $policyReferenceParameters `
                -ParameterDefinitions $policyDefinitionParameters
            $effect = Resolve-PolicyEffect `
                -Effect $effect `
                -ParameterValues $assignmentParameters `
                -ParameterDefinitions $policySetParameters

            $policyDisplayName = Get-ObjectPropertyValue `
                -InputObject $policyDefinition `
                -Name 'displayName'
            $policyReferenceId = Get-ObjectPropertyValue `
                -InputObject $policyReference `
                -Name 'policyDefinitionReferenceId'

            $memberPolicies += [pscustomobject] [ordered] @{
                DisplayName          = $policyDisplayName
                ReferenceId          = $policyReferenceId
                DefinitionId         = $referencedDefinitionId
                ConfiguredEffect     = $effect
                ReferenceParameters  = ConvertTo-ParameterMap `
                    -Parameters $policyReferenceParameters
            }
        }
    }
    else {
        if (-not $policyDefinitionCache.ContainsKey($definitionId)) {
            $policyDefinitionResource = Invoke-AzJson -Arguments @(
                'rest',
                '--method',
                'get',
                '--url',
                "${definitionId}?api-version=2023-04-01"
            )
            $policyDefinitionCache[$definitionId] = Get-ObjectPropertyValue `
                -InputObject $policyDefinitionResource `
                -Name 'properties'
        }

        $policyDefinition = $policyDefinitionCache[$definitionId]
        $policyDefinitionParameters = Get-ObjectPropertyValue `
            -InputObject $policyDefinition `
            -Name 'parameters'
        $policyRule = Get-ObjectPropertyValue -InputObject $policyDefinition -Name 'policyRule'
        $thenClause = Get-ObjectPropertyValue -InputObject $policyRule -Name 'then'
        $definitionEffect = Get-ObjectPropertyValue -InputObject $thenClause -Name 'effect'
        $configuredEffect = Resolve-PolicyEffect `
            -Effect $definitionEffect `
            -ParameterValues $assignmentParameters `
            -ParameterDefinitions $policyDefinitionParameters
    }

    $identity = Get-ResourcePropertyValue -Resource $assignment -Name 'identity'
    $identityType = if ($null -eq $identity) {
        $null
    }
    else {
        Get-ObjectPropertyValue -InputObject $identity -Name 'type'
    }

    $assignmentName = Get-ResourcePropertyValue -Resource $assignment -Name 'name'
    $assignmentDisplayName = Get-ResourcePropertyValue -Resource $assignment -Name 'displayName'
    if ([string]::IsNullOrWhiteSpace($assignmentDisplayName)) {
        $assignmentDisplayName = $assignmentName
    }

    [pscustomobject] [ordered] @{
        Assignment       = $assignmentDisplayName
        Name             = $assignmentName
        Definition       = $definitionId
        DefinitionType   = $definitionType
        ConfiguredEffect = $configuredEffect
        AssignmentParameters = $assignmentParameterMap
        MemberPolicies   = @($memberPolicies)
        Scope            = $assignmentScope
        Enforcement      = Get-ResourcePropertyValue -Resource $assignment -Name 'enforcementMode'
        Version          = Get-ResourcePropertyValue -Resource $assignment -Name 'effectiveDefinitionVersion'
        Location         = Get-ResourcePropertyValue -Resource $assignment -Name 'location'
        Identity         = $identityType
    }
}

$results |
    ConvertTo-Json -Depth 10 |
    Set-Content -Path $outputPath -Encoding utf8

Write-Host "Policy assignments written to: $outputPath"
