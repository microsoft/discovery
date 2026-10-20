$stage4Path = Join-Path $PSScriptRoot '..\scripts\stage4-deployment\stage4_deploy.ps1'
$stage5Path = Join-Path $PSScriptRoot '..\scripts\stage5-scenario-enablement\stage5_enable.ps1'
$modulePath = Join-Path $PSScriptRoot '..\scripts\lib\OnboardingCommon.psm1'
Import-Module $modulePath -Force

foreach ($functionSpec in @(
        @{ Path = $stage4Path; Name = 'Get-DefaultStorageContainerName' },
        @{ Path = $stage4Path; Name = 'Get-Stage4WorkspaceConfigFailure' },
        @{ Path = $stage5Path; Name = 'Get-CfgString' },
        @{ Path = $stage5Path; Name = 'Get-Stage5VNetId' },
        @{ Path = $stage5Path; Name = 'Test-StorageBlobPrivateLinkConnection' },
        @{ Path = $stage5Path; Name = 'Test-StoragePrivateEndpointDns' }
    )) {
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        (Resolve-Path $functionSpec.Path),
        [ref]$tokens,
        [ref]$errors
    )
    if ($errors.Count) { throw ($errors.Message -join [Environment]::NewLine) }
    $functionAst = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionSpec.Name
        }, $true)
    if (-not $functionAst) { throw "Function $($functionSpec.Name) was not found in $($functionSpec.Path)." }
    Invoke-Expression $functionAst.Extent.Text
}

Describe 'Stage 4 default storage-container naming' {
    It 'preserves the readable suffix within the 24-character limit' {
        $name = Get-DefaultStorageContainerName -WorkspaceName 'abcdefghijklmnopqrstuvwx'

        $name | Should Be 'abcdefghijklmnop-storage'
        $name.Length | Should Be 24
    }

    It 'does not truncate a workspace name when the derived name already fits' {
        Get-DefaultStorageContainerName -WorkspaceName 'workspace' | Should Be 'workspace-storage'
    }

    It 'does not create consecutive hyphens when truncation ends at a separator' {
        $name = Get-DefaultStorageContainerName -WorkspaceName 'abcdefghijklmno-pqrst'

        $name | Should Be 'abcdefghijklmno-storage'
        $name | Should Not Match '--'
        $name.Length | Should BeLessThan 25
    }

    It 'returns a structured config failure for a blank workspace' {
        $result = Get-Stage4WorkspaceConfigFailure -WorkspaceName ' '

        $result.id | Should Be 'deploy-config-workspace'
        $result.status | Should Be 'Fail'
        $result.detail | Should Match 'names.workspace'
    }

    It 'accepts a nonblank workspace before deriving a default container name' {
        Get-Stage4WorkspaceConfigFailure -WorkspaceName 'workspace' | Should BeNullOrEmpty
        Get-DefaultStorageContainerName -WorkspaceName 'workspace' | Should Be 'workspace-storage'
    }
}

Describe 'Stage 5 storage private endpoint DNS validation' {
    $vnetId = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/discovery-vnet'
    $zoneId = '/subscriptions/sub/resourceGroups/storage-rg/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net'
    $privateEndpoint = [pscustomobject]@{
        name             = 'pe-storage-blob'
        customDnsConfigs = @([pscustomobject]@{ fqdn = 'storage.blob.core.windows.net' })
    }

    It 'rejects custom DNS metadata without a DNS zone group' {
        Mock Get-AzJson { @() }

        $result = Test-StoragePrivateEndpointDns -PrivateEndpoint $privateEndpoint -ResourceGroup 'storage-rg' -VNetId $vnetId

        $result.zoneGroupConfigured | Should Be $false
        $result.vnetLinked | Should Be $false
    }

    It 'accepts a blob DNS zone group linked to the configured VNet' {
        Mock Get-AzJson {
            @([pscustomobject]@{
                    provisioningState      = 'Succeeded'
                    privateDnsZoneConfigs = @([pscustomobject]@{ privateDnsZoneId = $zoneId })
                })
        } -ParameterFilter { $Args -contains 'dns-zone-group' }
        Mock Get-AzJson {
            @([pscustomobject]@{
                    provisioningState = 'Succeeded'
                    virtualNetwork    = [pscustomobject]@{ id = $vnetId }
                })
        } -ParameterFilter { $Args -contains 'private-dns' }

        $result = Test-StoragePrivateEndpointDns -PrivateEndpoint $privateEndpoint -ResourceGroup 'storage-rg' -VNetId $vnetId

        $result.zoneGroupConfigured | Should Be $true
        $result.vnetLinked | Should Be $true
    }

    It 'rejects a blob DNS zone group linked only to another VNet' {
        Mock Get-AzJson {
            @([pscustomobject]@{
                    provisioningState      = 'Succeeded'
                    privateDnsZoneConfigs = @([pscustomobject]@{ privateDnsZoneId = $zoneId })
                })
        } -ParameterFilter { $Args -contains 'dns-zone-group' }
        Mock Get-AzJson {
            @([pscustomobject]@{
                    provisioningState = 'Succeeded'
                    virtualNetwork    = [pscustomobject]@{ id = "$vnetId-other" }
                })
        } -ParameterFilter { $Args -contains 'private-dns' }

        $result = Test-StoragePrivateEndpointDns -PrivateEndpoint $privateEndpoint -ResourceGroup 'storage-rg' -VNetId $vnetId

        $result.zoneGroupConfigured | Should Be $true
        $result.vnetLinked | Should Be $false
    }

    It 'rejects a blob DNS zone group that has not succeeded' {
        Mock Get-AzJson {
            @([pscustomobject]@{
                    provisioningState      = 'Failed'
                    privateDnsZoneConfigs = @([pscustomobject]@{ privateDnsZoneId = $zoneId })
                })
        } -ParameterFilter { $Args -contains 'dns-zone-group' }

        $result = Test-StoragePrivateEndpointDns -PrivateEndpoint $privateEndpoint -ResourceGroup 'storage-rg' -VNetId $vnetId

        $result.zoneGroupConfigured | Should Be $false
        $result.vnetLinked | Should Be $false
    }
}

Describe 'Stage 5 storage private endpoint targeting' {
    It 'uses the schema-supported default VNet name when vnetName is omitted' {
        $config = [pscustomobject]@{
            subscriptionId = 'sub'
            network        = [pscustomobject]@{}
            names          = [pscustomobject]@{ workspace = 'workspace' }
        }

        Get-Stage5VNetId -Config $config -DefaultResourceGroup 'platform-rg' -DefaultWorkspace 'workspace' |
            Should Be '/subscriptions/sub/resourceGroups/platform-rg/providers/Microsoft.Network/virtualNetworks/vnet-workspace'
    }

    It 'accepts only a blob connection to the configured storage account' {
        $blobConnection = [pscustomobject]@{
            privateLinkServiceId = '/subscriptions/sub/resourceGroups/storage-rg/providers/Microsoft.Storage/storageAccounts/projectdata'
            groupIds             = @('blob')
        }
        $fileConnection = [pscustomobject]@{
            privateLinkServiceId = $blobConnection.privateLinkServiceId
            groupIds             = @('file')
        }

        Test-StorageBlobPrivateLinkConnection -Connection $blobConnection -StorageAccountName 'projectdata' | Should Be $true
        Test-StorageBlobPrivateLinkConnection -Connection $fileConnection -StorageAccountName 'projectdata' | Should Be $false
        Test-StorageBlobPrivateLinkConnection -Connection $blobConnection -StorageAccountName 'differentaccount' | Should Be $false
    }
}
