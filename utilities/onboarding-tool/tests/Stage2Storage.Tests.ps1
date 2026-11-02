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
foreach ($name in @('Ensure-PrivateDnsZoneLink', 'Ensure-NetworkPrivateDnsZones', 'Ensure-StoragePrivateEndpointDns')) {
    $functionAst = $ast.Find({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
        }, $true)
    if (-not $functionAst) { throw "$name was not found in $stage2Path." }
    Invoke-Expression $functionAst.Extent.Text
}

$subscriptionId = 'sub'
$endpointRg = 'storage-rg'
$dnsRg = 'network-rg'
$endpointName = 'pe-storage-blob'
$vnetId = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/vnet'
$zoneId = '/subscriptions/sub/resourceGroups/network-rg/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net'

Describe 'Stage 2 storage private endpoint DNS' {
    BeforeEach {
        $global:Stage2DnsZone = [pscustomobject]@{ id = $zoneId }
        $global:Stage2DnsLinks = @([pscustomobject]@{
                name              = 'canonical-link'
                provisioningState = 'Succeeded'
                virtualNetwork    = [pscustomobject]@{ id = $vnetId }
            })
        $global:Stage2DnsZoneGroup = [pscustomobject]@{
            name                  = 'blob-zone-group'
            provisioningState     = 'Succeeded'
            privateDnsZoneConfigs = @([pscustomobject]@{ privateDnsZoneId = $zoneId })
        }
        Mock Get-AzJson { $global:Stage2DnsZone } -ParameterFilter {
            $Args -contains 'private-dns' -and $Args -contains 'zone' -and $Args -contains 'show'
        }
        Mock Get-AzJson { @($global:Stage2DnsLinks) } -ParameterFilter {
            $Args -contains 'private-dns' -and $Args -contains 'link' -and $Args -contains 'list'
        }
        Mock Get-AzJson { $global:Stage2DnsZoneGroup } -ParameterFilter {
            $Args -contains 'dns-zone-group' -and $Args -contains 'show'
        }
        Mock Invoke-Az {}
    }

    AfterEach {
        Remove-Variable Stage2DnsZone, Stage2DnsLinks, Stage2DnsZoneGroup -Scope Global -ErrorAction SilentlyContinue
    }

    It 'reuses the canonical network resource group zone and existing VNet link' {
        $result = Ensure-StoragePrivateEndpointDns -SubscriptionId $subscriptionId `
            -EndpointResourceGroup $endpointRg -EndpointName $endpointName `
            -DnsResourceGroup $dnsRg -VNetId $vnetId

        $result.state | Should Be 'linked'
        $result.dnsZoneResourceGroup | Should Be $dnsRg
        Assert-MockCalled Get-AzJson -Times 1 -ParameterFilter {
            $Args -contains 'private-dns' -and $Args -contains 'zone' -and
            $Args -contains $dnsRg -and $Args -notcontains $endpointRg
        }
        Assert-MockCalled Invoke-Az -Times 0
    }

    It 'creates and verifies a missing VNet link in the DNS resource group' {
        $global:Stage2DnsLinks = @()
        Mock Invoke-Az {
            $global:Stage2DnsLinks = @([pscustomobject]@{
                    name              = 'created-link'
                    provisioningState = 'Succeeded'
                    virtualNetwork    = [pscustomobject]@{ id = $vnetId }
                })
        } -ParameterFilter { $Args -contains 'private-dns' -and $Args -contains 'link' }

        $result = Ensure-StoragePrivateEndpointDns -SubscriptionId $subscriptionId `
            -EndpointResourceGroup $endpointRg -EndpointName $endpointName `
            -DnsResourceGroup $dnsRg -VNetId $vnetId

        $result.vnetLink | Should Be 'created-link'
        Assert-MockCalled Invoke-Az -Times 1 -ParameterFilter {
            $Args -contains 'private-dns' -and $Args -contains 'link' -and $Args -contains $dnsRg
        }
    }

    It 'fails instead of reporting success when the VNet link is not succeeded' {
        $global:Stage2DnsLinks[0].provisioningState = 'Failed'

        $threw = $false
        try {
            Ensure-StoragePrivateEndpointDns -SubscriptionId $subscriptionId `
                -EndpointResourceGroup $endpointRg -EndpointName $endpointName `
                -DnsResourceGroup $dnsRg -VNetId $vnetId | Out-Null
        }
        catch {
            $threw = $true
            $_.Exception.Message | Should Match 'state=Failed'
        }
        $threw | Should Be $true
    }

    It 'creates the zone group on the endpoint using the canonical cross-RG zone' {
        $global:Stage2DnsZoneGroup = $null
        Mock Invoke-Az {
            $global:Stage2DnsZoneGroup = [pscustomobject]@{
                name                  = 'blob-zone-group'
                provisioningState     = 'Succeeded'
                privateDnsZoneConfigs = @([pscustomobject]@{ privateDnsZoneId = $zoneId })
            }
        } -ParameterFilter { $Args -contains 'dns-zone-group' }

        $result = Ensure-StoragePrivateEndpointDns -SubscriptionId $subscriptionId `
            -EndpointResourceGroup $endpointRg -EndpointName $endpointName `
            -DnsResourceGroup $dnsRg -VNetId $vnetId

        $result.dnsZoneId | Should Be $zoneId
        Assert-MockCalled Invoke-Az -Times 1 -ParameterFilter {
            $Args -contains 'dns-zone-group' -and
            $Args -contains $endpointRg -and
            $Args -contains $zoneId
        }
    }
}

Describe 'Stage 2 centralized private DNS zones' {
BeforeEach {
    $global:Stage2DnsZoneShowCalls = 0
    $global:Stage2DnsLinkListCalls = 0
    Mock Get-AzJson {
        $global:Stage2DnsZoneShowCalls++
        if ($global:Stage2DnsZoneShowCalls % 2 -eq 0) {
            return [pscustomobject]@{ id = "/subscriptions/sub/resourceGroups/dns-rg/providers/Microsoft.Network/privateDnsZones/zone-$global:Stage2DnsZoneShowCalls" }
        }
        return $null
    } -ParameterFilter { $Args -contains 'private-dns' -and $Args -contains 'zone' -and $Args -contains 'show' }
    Mock Get-AzJson {
        $global:Stage2DnsLinkListCalls++
        if ($global:Stage2DnsLinkListCalls % 2 -eq 0) {
            return @([pscustomobject]@{
                    name              = 'link-vnet'
                    provisioningState = 'Succeeded'
                    virtualNetwork    = [pscustomobject]@{ id = $vnetId }
                })
        }
        return @()
    } -ParameterFilter { $Args -contains 'private-dns' -and $Args -contains 'link' -and $Args -contains 'list' }
    Mock Invoke-Az {}
}

AfterEach {
    Remove-Variable Stage2DnsZoneShowCalls, Stage2DnsLinkListCalls -Scope Global -ErrorAction SilentlyContinue
}

It 'creates and verifies every requested zone in a distinct centralized DNS resource group' {
    $zones = @('privatelink.blob.core.windows.net', 'privatelink.queue.core.windows.net')

    $result = Ensure-NetworkPrivateDnsZones -SubscriptionId 'sub' -DnsResourceGroup 'dns-rg' `
        -VNetId $vnetId -DnsZones $zones -LinkName 'link-vnet'

    $result.state | Should Be 'linked'
    $result.resourceGroup | Should Be 'dns-rg'
    $result.zones.Count | Should Be 2
    Assert-MockCalled Invoke-Az -Scope It -Times 2 -ParameterFilter {
        $Args -contains 'zone' -and $Args -contains 'create' -and $Args -contains 'dns-rg'
    }
    Assert-MockCalled Invoke-Az -Scope It -Times 2 -ParameterFilter {
        $Args -contains 'link' -and $Args -contains 'create' -and $Args -contains 'dns-rg'
    }
}
}
