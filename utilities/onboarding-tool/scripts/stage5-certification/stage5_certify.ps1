#Requires -Version 7.0
<#
.SYNOPSIS  Stage 5 / FR5.1-FR5.7 — run hero use-case certification end to end.
.DESCRIPTION Orchestrates connectivity, tool creation, agent binding, investigation/conversation, prompt polling, tool-call assertion, and summary. Spec: ../../script-specs/stage5-certification/stage5_certify.md
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [string]$JsonPath,
    [string]$ResourceGroup,
    [string]$Workspace,
    [string]$Project,
    [string]$ChatModel,
    [string]$ToolArmId,
    [string]$Prompt
)
Import-Module (Join-Path $PSScriptRoot '..\lib\OnboardingCommon.psm1') -Force

function Get-CfgString { param([object]$Object, [string]$Name, [string]$Default = '') if ($Object -and $Object.PSObject.Properties.Name -contains $Name -and $Object.$Name) { [string]$Object.$Name } else { $Default } }
function Add-Many { param([object[]]$Items) foreach ($i in @($Items)) { $results.Add($i) } }
function Has-Fail { param([object[]]$Items) [bool](@($Items | Where-Object { $_.status -eq 'Fail' }).Count) }
function Last-DataById {
    param([object[]]$Items, [string]$Id)
    $r = @($Items | Where-Object { $_.id -eq $Id } | Select-Object -Last 1)
    if ($r.Count) { return $r[0].data }
    return $null
}
function Write-State {
    param([string]$Path, [hashtable]$State)
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    [pscustomobject]$State | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding utf8
}

<#
.SYNOPSIS  Stage 5 / FR5.1 — validate platform private endpoint DNS and 443 reachability.
.DESCRIPTION Creates an ephemeral Linux VM in the onboarding VNet, probes platform privatelink FQDNs, then removes the VM. Spec: ../../script-specs/stage5-certification/stage5_certify.md
#>
function Invoke-Stage5ConnectivityCheck {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [string]$JsonPath,
        [switch]$PassThru,
        [string]$ResourceGroup,
        [string]$NetworkResourceGroup,
        [string]$VNetName,
        [string]$SubnetName,
        [string[]]$Fqdn,
        [switch]$CurrentHostOnly
    )
    $cfg = Get-OnboardingConfig -Path $ConfigPath
    $results = [System.Collections.Generic.List[object]]::new()

    function Get-CfgValue {
        param([object]$Object, [string[]]$Names, [string]$Default = '')
        foreach ($n in $Names) {
            if ($Object -and $Object.PSObject.Properties.Name -contains $n -and $Object.$n) { return [string]$Object.$n }
        }
        return $Default
    }
    function Test-PrivateIp {
        param([string]$Ip)
        if (-not $Ip) { return $false }
        try {
            $u = ConvertTo-UInt32Ip $Ip
            return (Test-CidrContains -Outer '10.0.0.0/8' -Inner "$Ip/32") -or
                (Test-CidrContains -Outer '172.16.0.0/12' -Inner "$Ip/32") -or
                (Test-CidrContains -Outer '192.168.0.0/16' -Inner "$Ip/32") -or
                ($u -ge (ConvertTo-UInt32Ip '100.64.0.0') -and $u -le (ConvertTo-UInt32Ip '100.127.255.255'))
        } catch { return $false }
    }
    function Get-ConfiguredFqdns {
        param([object]$Config, [string[]]$ExplicitFqdn, [string[]]$ResourceGroups)
        $names = @()
        if ($ExplicitFqdn) { $names += $ExplicitFqdn }
        foreach ($p in @('privateEndpointFqdns', 'privateEndpointFQDNs', 'privatelinkFqdns')) {
            if ($Config.PSObject.Properties.Name -contains $p -and $Config.$p) { $names += @($Config.$p) }
            if ($Config.network.PSObject.Properties.Name -contains $p -and $Config.network.$p) { $names += @($Config.network.$p) }
        }
        if ($Config.PSObject.Properties.Name -contains 'privateEndpoints' -and $Config.privateEndpoints) {
            foreach ($pe in @($Config.privateEndpoints)) {
                if ($pe.PSObject.Properties.Name -contains 'fqdn' -and $pe.fqdn) { $names += $pe.fqdn }
                if ($pe.PSObject.Properties.Name -contains 'fqdns' -and $pe.fqdns) { $names += @($pe.fqdns) }
            }
        }
        foreach ($rg in @($ResourceGroups | Where-Object { $_ } | Sort-Object -Unique)) {
            $pes = @(Get-AzJson -Args @('network', 'private-endpoint', 'list', '-g', $rg) -AllowFail)
            foreach ($pe in $pes) {
                foreach ($cfgItem in @($pe.customDnsConfigs)) {
                    if ($cfgItem.fqdn) { $names += $cfgItem.fqdn }
                }
            }
        }
        @($names | Where-Object { $_ -and $_ -like '*privatelink*' } | Sort-Object -Unique)
    }
    function Find-ProbeSubnetId {
        param([object]$Config, [string]$NetRg, [string]$Vnet, [string]$Subnet)
        foreach ($role in @('spare', 'nodepool', 'managedcluster')) {
            foreach ($sn in @($Config.network.subnets)) {
                if ($sn.role -ne $role) { continue }
                if ($sn.PSObject.Properties.Name -contains 'id' -and $sn.id) { return [string]$sn.id }
                if (-not $Subnet -and $sn.PSObject.Properties.Name -contains 'name' -and $sn.name) { $Subnet = [string]$sn.name }
            }
            if ($Subnet) { break }
        }
        if ($NetRg -and $Vnet -and $Subnet) {
            $s = Get-AzJson -Args @('network', 'vnet', 'subnet', 'show', '-g', $NetRg, '--vnet-name', $Vnet, '-n', $Subnet) -AllowFail
            if ($s -and $s.id) { return [string]$s.id }
        }
        if ($NetRg) {
            $vnets = @(Get-AzJson -Args @('network', 'vnet', 'list', '-g', $NetRg) -AllowFail)
            foreach ($vnetObj in $vnets) {
                foreach ($sn in @($vnetObj.subnets)) {
                    foreach ($cfgSn in @($Config.network.subnets | Where-Object { $_.role -in @('spare', 'nodepool', 'managedcluster') })) {
                        $prefixes = @($sn.addressPrefix) + @($sn.addressPrefixes)
                        if ($prefixes -contains $cfgSn.cidr) { return [string]$sn.id }
                    }
                }
            }
        }
        return ''
    }
    function Invoke-LocalProbe {
        param([string[]]$Names)
        foreach ($name in $Names) {
            $ips = @()
            try { $ips = @([System.Net.Dns]::GetHostAddresses($name) | ForEach-Object { $_.IPAddressToString }) } catch {}
            $reachable = $false
            try { $reachable = (Test-NetConnection -ComputerName $name -Port 443 -InformationLevel Quiet) } catch {}
            [pscustomobject]@{ fqdn = $name; ips = $ips; tcp443 = [bool]$reachable }
        }
    }
    function Invoke-VmProbe {
        param([string]$Rg, [string]$SubnetId, [string[]]$Names)
        $suffix = (Get-Random -Maximum 999999).ToString('000000')
        $vm = "stg5probe$suffix"
        $tag = "stage5probe=$vm"
        $script = @"
    set -e
    for h in $($Names -join ' '); do
      ips=`$(getent ahostsv4 "`$h" | awk '{print `$1}' | sort -u | xargs)
      if [ -z "`$ips" ]; then ips=""; fi
      if timeout 5 bash -lc ":</dev/tcp/`$h/443" >/dev/null 2>&1; then tcp=OPEN; else tcp=BLOCKED; fi
      echo "PE `$h `$ips `$tcp"
    done
"@
        try {
            $null = Invoke-Az -Args @('vm', 'create', '-g', $Rg, '-n', $vm, '--image', 'Ubuntu2204', '--size', 'Standard_B1s', '--subnet', $SubnetId, '--public-ip-address', '', '--admin-username', 'azureuser', '--generate-ssh-keys', '--tags', $tag, '-o', 'none')
            $out = Invoke-Az -Args @('vm', 'run-command', 'invoke', '-g', $Rg, '-n', $vm, '--command-id', 'RunShellScript', '--scripts', $script, '--query', 'value[0].message', '-o', 'tsv') -AllowFail
            foreach ($line in ($out -split "`r?`n")) {
                $m = [regex]::Match($line.Trim(), '^PE\s+(\S+)\s+(.*?)\s+(OPEN|BLOCKED)$')
                if ($m.Success) {
                    $ips = @($m.Groups[2].Value -split '\s+' | Where-Object { $_ })
                    [pscustomobject]@{ fqdn = $m.Groups[1].Value; ips = $ips; tcp443 = ($m.Groups[3].Value -eq 'OPEN') }
                }
            }
        }
        finally {
            $ids = @(Get-AzJson -Args @('resource', 'list', '-g', $Rg, '--tag', $tag, '--query', '[].id') -AllowFail)
            foreach ($id in $ids) { if ($id) { Invoke-Az -Args @('resource', 'delete', '--ids', [string]$id) -AllowFail | Out-Null } }
        }
    }

    $ResourceGroup = if ($ResourceGroup) { $ResourceGroup } else { Get-CfgValue $cfg @('resourceGroup', 'deploymentResourceGroup') }
    $NetworkResourceGroup = if ($NetworkResourceGroup) { $NetworkResourceGroup } else { Get-CfgValue $cfg.network @('networkResourceGroup') $ResourceGroup }
    $VNetName = if ($VNetName) { $VNetName } else { Get-CfgValue $cfg.network @('vnetName', 'virtualNetworkName') }
    $probeFqdns = Get-ConfiguredFqdns -Config $cfg -ExplicitFqdn $Fqdn -ResourceGroups @($ResourceGroup, $NetworkResourceGroup)

    if (-not $probeFqdns.Count) {
        $results.Add((New-CheckResult -Id 'fr5-1-fqdn-input' -Name 'platform privatelink FQDN discovery' -Status 'Fail' -Fr 'FR5.1' -Detail 'No platform privatelink FQDNs found in config or private endpoints.' -Remediation 'Populate privateEndpointFqdns/privatelinkFqdns or ensure platform private endpoints exist.'))
    } else {
        $probe = @()
        if ($CurrentHostOnly) {
            $probe = @(Invoke-LocalProbe -Names $probeFqdns)
        } else {
            $subnetId = Find-ProbeSubnetId -Config $cfg -NetRg $NetworkResourceGroup -Vnet $VNetName -Subnet $SubnetName
            if (-not $ResourceGroup -or -not $subnetId) {
                $results.Add((New-CheckResult -Id 'fr5-1-probe-vm-input' -Name 'ephemeral probe VM placement' -Status 'Fail' -Fr 'FR5.1' -Detail 'Resource group or probe subnet could not be resolved.' -Remediation 'Pass -ResourceGroup and either subnet id/name in config or -VNetName/-SubnetName.'))
            } else {
                $probe = @(Invoke-VmProbe -Rg $ResourceGroup -SubnetId $subnetId -Names $probeFqdns)
            }
        }
        foreach ($name in $probeFqdns) {
            $p = $probe | Where-Object { $_.fqdn -eq $name } | Select-Object -First 1
            $ips = if ($p) { @($p.ips) } else { @() }
            $private = @($ips | Where-Object { Test-PrivateIp $_ })
            $ok = $ips.Count -gt 0 -and $private.Count -eq $ips.Count -and $p.tcp443
            $results.Add((New-CheckResult -Id "fr5-1-$name" -Name "private endpoint $name" -Status ($ok ? 'Pass' : 'Fail') -Fr 'FR5.1' -Detail "ips=$($ips -join ',') tcp443=$($p.tcp443)" -Remediation ($ok ? '' : 'Fix private DNS links, private endpoint approval, NSG, or route tables before certifying.') -Data ([pscustomobject]@{ fqdn = $name; ips = $ips; allPrivate = ($ips.Count -gt 0 -and $private.Count -eq $ips.Count); tcp443 = if ($p) { $p.tcp443 } else { $false } })))
        }
    }

    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 5 · connectivity (FR5.1)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

<#
.SYNOPSIS  Stage 5 / FR5.2 — create and verify the Discovery tool resource.
.DESCRIPTION Creates a Discovery tool with ARM PUT and validates Succeeded plus definitionContent. Spec: ../../script-specs/stage5-certification/stage5_certify.md
#>
function Invoke-Stage5CreateTool {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [string]$JsonPath,
        [switch]$PassThru,
        [string]$ResourceGroup,
        [string]$Workspace,
        [string]$ToolArmId,
        [string]$Tool,
        [string]$Supercomputer,
        [string]$NodePool,
        [string]$Image = 'mddemoacr.azurecr.io/corepython:latest',
        [string]$RecommendedSku = 'Standard_D4s_v3'
    )
    $cfg = Get-OnboardingConfig -Path $ConfigPath
    $results = [System.Collections.Generic.List[object]]::new()
    $api = '2026-06-01'

    function Get-CfgString {
        param([object]$Object, [string]$Name, [string]$Default = '')
        if ($Object -and $Object.PSObject.Properties.Name -contains $Name -and $Object.$Name) { return [string]$Object.$Name }
        return $Default
    }
    function Add-Result {
        param([string]$Id, [string]$Name, [string]$Status, [string]$Detail, [string]$Remediation = '', [object]$Data = $null)
        $results.Add((New-CheckResult -Id $Id -Name $Name -Status $Status -Fr 'FR5.2' -Detail $Detail -Remediation $Remediation -Data $Data))
    }

    $ResourceGroup = if ($ResourceGroup) { $ResourceGroup } else { Get-CfgString $cfg 'resourceGroup' (Get-CfgString $cfg 'deploymentResourceGroup') }
    $Workspace = if ($Workspace) { $Workspace } else { Get-CfgString $cfg.names 'workspace' }
    $Tool = if ($Tool) { $Tool } else { Get-CfgString $cfg.names 'tool' 'hero-tool' }
    $Supercomputer = if ($Supercomputer) { $Supercomputer } else { Get-CfgString $cfg.names 'supercomputer' }
    $NodePool = if ($NodePool) { $NodePool } else { Get-CfgString $cfg.names 'nodePool' }
    if (-not $ToolArmId -and $ResourceGroup) {
        $ToolArmId = "/subscriptions/$($cfg.subscriptionId)/resourceGroups/$ResourceGroup/providers/Microsoft.Discovery/tools/$Tool"
    }

    if (-not $ToolArmId) {
        Add-Result 'fr5-2-tool-id' 'tool ARM id resolved' 'Fail' 'ToolArmId could not be resolved.' 'Pass -ToolArmId or set resourceGroup in config.'
    } else {
        if ($ResourceGroup -and $Supercomputer -and $NodePool) {
            $npId = "/subscriptions/$($cfg.subscriptionId)/resourceGroups/$ResourceGroup/providers/Microsoft.Discovery/supercomputers/$Supercomputer/nodePools/$NodePool"
            $np = Get-AzJson -Args @('resource', 'show', '--ids', $npId, '--api-version', $api) -AllowFail
            if ($np -and $np.properties -and $np.properties.vmSize) { $RecommendedSku = [string]$np.properties.vmSize }
        }
        $infraName = 'corepython-container'
        $toolBody = [ordered]@{
            location   = $cfg.workloadRegion
            tags       = @{ category = 'Scientific Computing'; stage = 'stage5-certification' }
            properties = [ordered]@{
                version           = '1.0.0'
                definitionContent = [ordered]@{
                    name              = $Tool
                    description       = "Hero certification Python execution tool. The agent must call GetNodePoolContext before using this tool so execution is pinned to the $Supercomputer/$NodePool supercomputer node pool."
                    version           = '1.0.0'
                    category          = 'scientific-computing'
                    license           = 'MIT'
                    infra             = @([ordered]@{
                            name       = $infraName
                            infra_type = 'container'
                            image      = @{ acr = $Image }
                            compute    = [ordered]@{
                                min_resources  = @{ cpu = 1; ram = '8Gi'; storage = '8Gi'; gpu = 0 }
                                max_resources  = @{ cpu = 2; ram = '16Gi'; storage = '32Gi'; gpu = 0 }
                                infiniband     = $false
                                recommended_sku = @($RecommendedSku)
                                pool_type      = 'static'
                                pool_size      = 1
                            }
                        })
                    code_environments = @([ordered]@{
                            language    = 'python'
                            command     = 'python "/{{scriptName}}"'
                            description = 'Python code environment on the hero certification container image.'
                            infra_node  = $infraName
                        })
                }
            }
        }
        $infraNodes = @($toolBody.properties.definitionContent.infra | ForEach-Object { $_.name })
        $envNodes = @($toolBody.properties.definitionContent.code_environments | ForEach-Object { $_.infra_node })
        $mismatch = @($envNodes | Where-Object { $infraNodes -notcontains $_ })
        if ($mismatch.Count) {
            Add-Result 'fr5-2-tool-shape' 'tool definition shape' 'Fail' "infra_node mismatch: $($mismatch -join ',')" 'Align code_environments[].infra_node with an infra[].name.'
        } else {
            Add-Result 'fr5-2-tool-shape' 'tool definition shape' 'Pass' "infra_node=$($envNodes -join ',') recommended_sku=$RecommendedSku"
            $bodyPath = Join-Path ([System.IO.Path]::GetTempPath()) "stage5-tool-$([guid]::NewGuid().ToString('N')).json"
            try {
                $toolBody | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $bodyPath -Encoding utf8
                $put = Get-AzJson -Args @('rest', '--method', 'put', '--url', "https://management.azure.com$ToolArmId`?api-version=$api", '--body', "@$bodyPath") -AllowFail
                $prov = if ($put -and $put.properties) { [string]$put.properties.provisioningState } else { '' }
                for ($i = 0; $i -lt 36 -and $prov -notin @('Succeeded', 'Failed', 'Canceled'); $i++) {
                    Start-Sleep -Seconds 5
                    $put = Get-AzJson -Args @('resource', 'show', '--ids', $ToolArmId, '--api-version', $api) -AllowFail
                    $prov = if ($put -and $put.properties) { [string]$put.properties.provisioningState } else { '' }
                }
                $hasDefinition = [bool]($put -and $put.properties -and $put.properties.definitionContent)
                $ok = $prov -eq 'Succeeded' -and $hasDefinition
                Add-Result 'fr5-2-tool-created' 'Discovery tool created' ($ok ? 'Pass' : 'Fail') "toolId=$ToolArmId provisioningState=$prov hasDefinition=$hasDefinition" ($ok ? '' : 'Retry after fixing tool body validation errors and confirm the RP returns properties.definitionContent.') ([pscustomobject]@{ toolId = $ToolArmId; provisioningState = $prov; hasDefinition = $hasDefinition; definitionName = if ($hasDefinition) { $put.properties.definitionContent.name } else { $null } })
            }
            finally {
                if (Test-Path -LiteralPath $bodyPath) { Remove-Item -LiteralPath $bodyPath -Force }
            }
        }
    }

    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 5 · create tool (FR5.2)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

<#
.SYNOPSIS  Stage 5 / FR5.3 — create a Discovery agent and bind the tool.
.DESCRIPTION Upserts the data-plane agent with top-level tools[] and instructions that require GetNodePoolContext first. Spec: ../../script-specs/stage5-certification/stage5_certify.md
#>
function Invoke-Stage5CreateAgentBindTool {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [string]$JsonPath,
        [switch]$PassThru,
        [string]$Workspace,
        [string]$Project,
        [string]$ChatModel,
        [string]$Agent,
        [string]$ToolArmId,
        [string]$ResourceGroup
    )
    $cfg = Get-OnboardingConfig -Path $ConfigPath
    $results = [System.Collections.Generic.List[object]]::new()
    $api = '2026-06-01'

    function Get-CfgString { param([object]$Object, [string]$Name, [string]$Default = '') if ($Object -and $Object.PSObject.Properties.Name -contains $Name -and $Object.$Name) { [string]$Object.$Name } else { $Default } }
    function Get-DiscoveryToken { (Invoke-Az -Args @('account', 'get-access-token', '--resource', 'https://discovery.azure.com', '--query', 'accessToken', '-o', 'tsv')).Trim() }
    function Invoke-DiscoveryJson {
        param([string]$Method, [string]$Uri, [object]$Body = $null, [switch]$ReturnHeaders)
        $headers = @{ Authorization = "Bearer $(Get-DiscoveryToken)"; Accept = 'application/json' }
        if ($Body) { $headers['Content-Type'] = 'application/json' }
        $json = if ($Body) { $Body | ConvertTo-Json -Depth 30 } else { $null }
        $resp = Invoke-WebRequest -Method $Method -Uri $Uri -Headers $headers -Body $json -SkipHttpErrorCheck
        $content = if ($resp.Content) { try { $resp.Content | ConvertFrom-Json } catch { $resp.Content } } else { $null }
        if ($ReturnHeaders) { return [pscustomobject]@{ StatusCode = [int]$resp.StatusCode; Headers = $resp.Headers; Body = $content } }
        [pscustomobject]@{ StatusCode = [int]$resp.StatusCode; Body = $content }
    }
    function Add-Result { param([string]$Id, [string]$Name, [string]$Status, [string]$Detail, [string]$Remediation = '', [object]$Data = $null) $results.Add((New-CheckResult -Id $Id -Name $Name -Status $Status -Fr 'FR5.3' -Detail $Detail -Remediation $Remediation -Data $Data)) }

    $Workspace = if ($Workspace) { $Workspace } else { Get-CfgString $cfg.names 'workspace' }
    $Project = if ($Project) { $Project } else { Get-CfgString $cfg.names 'project' }
    $Agent = if ($Agent) { $Agent } else { Get-CfgString $cfg.names 'agent' 'hero-agent' }
    $ChatModel = if ($ChatModel) { $ChatModel } else { Get-CfgString $cfg.names 'chatModel' (Get-CfgString $cfg.names 'chatModelDeployment' 'gpt-5-4') }
    $ResourceGroup = if ($ResourceGroup) { $ResourceGroup } else { Get-CfgString $cfg 'resourceGroup' (Get-CfgString $cfg 'deploymentResourceGroup') }
    if (-not $ToolArmId -and $ResourceGroup) {
        $tool = Get-CfgString $cfg.names 'tool' 'hero-tool'
        $ToolArmId = "/subscriptions/$($cfg.subscriptionId)/resourceGroups/$ResourceGroup/providers/Microsoft.Discovery/tools/$tool"
    }

    if (-not $Workspace -or -not $Project -or -not $ToolArmId) {
        Add-Result 'fr5-3-inputs' 'agent upsert inputs' 'Fail' 'Workspace, Project, or ToolArmId is missing.' 'Pass -Workspace, -Project, and -ToolArmId or set config names/resourceGroup.'
    } else {
        $base = "https://$Workspace.workspace.discovery.azure.com"
        $instructions = @"
    You are a hero use-case certification agent for Microsoft Discovery.

    # CRITICAL: TOOL CALLING RULE
    You MUST call only ONE tool at a time. Always wait for the result of the current tool call before making the next one.

    ## REQUIRED FIRST STEP
    - Use GetNodePoolContext tool to get node pool ARM resource ID before executing script

    ## RULE
    When the user asks for any computed result, script execution, or platform validation, you MUST execute Python using the bound tool rather than answering from memory. Always show the Python script you ran and its complete stdout.
"@
        $body = [ordered]@{
            name           = $Agent
            humanInTheLoop = 'Disabled'
            tools          = @(@{ toolId = $ToolArmId; confirmation = 'Disabled' })
            foundryDetails = [ordered]@{
                description = 'Stage 5 hero certification agent with a Discovery tool attached.'
                definition  = [ordered]@{
                    kind         = 'prompt'
                    model        = $ChatModel
                    instructions = $instructions
                }
            }
        }
        $url = "$base/projects/$Project`:upsertAgent?api-version=$api"
        $upsert = Invoke-DiscoveryJson -Method 'PUT' -Uri $url -Body $body -ReturnHeaders
        $op = @($upsert.Headers['Operation-Location'] + $upsert.Headers['operation-location'] + $upsert.Headers['Azure-AsyncOperation'] + $upsert.Headers['azure-asyncoperation'] | Where-Object { $_ } | Select-Object -First 1)
        $opStatus = ''
        if ($op) {
            for ($i = 0; $i -lt 36 -and $opStatus -notin @('Succeeded', 'Failed', 'Canceled'); $i++) {
                Start-Sleep -Seconds 5
                $poll = Invoke-DiscoveryJson -Method 'GET' -Uri ([string]$op)
                $opStatus = if ($poll.Body -and $poll.Body.status) { [string]$poll.Body.status } else { '' }
            }
        }
        $created = $upsert.StatusCode -in @(200, 201, 202) -and (-not $op -or $opStatus -eq 'Succeeded')
        Add-Result 'fr5-3-agent-created' 'Discovery agent upserted' ($created ? 'Pass' : 'Fail') "agent=$Agent statusCode=$($upsert.StatusCode) operationStatus=$opStatus" ($created ? '' : 'Confirm the workspace data-plane endpoint, model deployment name, and agent schema.')
        $agentUrl = "$base/projects/$Project/agents/$Agent`?api-version=$api"
        $agentGet = Invoke-DiscoveryJson -Method 'GET' -Uri $agentUrl
        $bound = @()
        if ($agentGet.Body -and $agentGet.Body.tools) { $bound = @($agentGet.Body.tools | ForEach-Object { $_.toolId }) }
        $toolBound = @($bound | Where-Object { $_ -and $_.ToLowerInvariant() -eq $ToolArmId.ToLowerInvariant() }).Count -gt 0
        Add-Result 'fr5-3-tool-bound' 'tool bound to agent' ($toolBound ? 'Pass' : 'Fail') "agent=$Agent toolBound=$toolBound tools=$($bound -join ',')" ($toolBound ? '' : 'Ensure tools[] is top-level and contains the tool ARM id.') ([pscustomobject]@{ agentId = $Agent; toolBound = $toolBound; tools = $bound; toolId = $ToolArmId; model = $ChatModel })
    }

    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 5 · create agent and bind tool (FR5.3)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

<#
.SYNOPSIS  Stage 5 / FR5.4 — create investigation and conversation.
.DESCRIPTION Creates the investigation first, then creates a conversation with the full investigationName path. Spec: ../../script-specs/stage5-certification/stage5_certify.md
#>
function Invoke-Stage5CreateInvestigationConversation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [string]$JsonPath,
        [switch]$PassThru,
        [string]$Workspace,
        [string]$Project,
        [string]$Investigation
    )
    $cfg = Get-OnboardingConfig -Path $ConfigPath
    $results = [System.Collections.Generic.List[object]]::new()
    $api = '2026-06-01'
    function Get-CfgString { param([object]$Object, [string]$Name, [string]$Default = '') if ($Object -and $Object.PSObject.Properties.Name -contains $Name -and $Object.$Name) { [string]$Object.$Name } else { $Default } }
    function Get-DiscoveryToken { (Invoke-Az -Args @('account', 'get-access-token', '--resource', 'https://discovery.azure.com', '--query', 'accessToken', '-o', 'tsv')).Trim() }
    function Invoke-DiscoveryJson {
        param([string]$Method, [string]$Uri, [object]$Body = $null)
        $headers = @{ Authorization = "Bearer $(Get-DiscoveryToken)"; Accept = 'application/json' }
        if ($Body) { $headers['Content-Type'] = 'application/json' }
        $json = if ($Body) { $Body | ConvertTo-Json -Depth 20 } else { $null }
        $resp = Invoke-WebRequest -Method $Method -Uri $Uri -Headers $headers -Body $json -SkipHttpErrorCheck
        $content = if ($resp.Content) { try { $resp.Content | ConvertFrom-Json } catch { $resp.Content } } else { $null }
        [pscustomobject]@{ StatusCode = [int]$resp.StatusCode; Body = $content }
    }
    function Add-Result { param([string]$Id, [string]$Name, [string]$Status, [string]$Detail, [string]$Remediation = '', [object]$Data = $null) $results.Add((New-CheckResult -Id $Id -Name $Name -Status $Status -Fr 'FR5.4' -Detail $Detail -Remediation $Remediation -Data $Data)) }

    $Workspace = if ($Workspace) { $Workspace } else { Get-CfgString $cfg.names 'workspace' }
    $Project = if ($Project) { $Project } else { Get-CfgString $cfg.names 'project' }
    $Investigation = if ($Investigation) { $Investigation } else { Get-CfgString $cfg.names 'investigation' 'hero-inv' }
    if (-not $Workspace -or -not $Project -or -not $Investigation) {
        Add-Result 'fr5-4-inputs' 'conversation inputs' 'Fail' 'Workspace, Project, or Investigation is missing.' 'Set config.names.workspace/project/investigation or pass parameters.'
    } else {
        $base = "https://$Workspace.workspace.discovery.azure.com"
        $invPath = "/projects/$Project/investigations/$Investigation"
        $inv = Invoke-DiscoveryJson -Method 'PUT' -Uri "$base/projects/$Project/investigations/$Investigation`?api-version=$api" -Body @{ displayName = 'Stage 5 hero certification'; description = 'Hero use-case certification investigation.' }
        $invOk = $inv.StatusCode -in @(200, 201, 202)
        Add-Result 'fr5-4-investigation' 'investigation created' ($invOk ? 'Pass' : 'Fail') "investigationName=$invPath statusCode=$($inv.StatusCode)" ($invOk ? '' : 'Create the investigation before creating the conversation.')
        if ($invOk) {
            $conv = Invoke-DiscoveryJson -Method 'POST' -Uri "$base/conversations?api-version=$api" -Body @{ displayName = 'stage5-hero-conversation'; investigationName = $invPath; projectName = $Project }
            $convId = if ($conv.Body -and $conv.Body.name) { [string]$conv.Body.name } elseif ($conv.Body -and $conv.Body.id) { [string]$conv.Body.id } else { '' }
            $ok = $conv.StatusCode -in @(200, 201, 202) -and $convId
            Add-Result 'fr5-4-conversation' 'conversation created' ($ok ? 'Pass' : 'Fail') "conversationId=$convId statusCode=$($conv.StatusCode)" ($ok ? '' : 'Use full investigationName path /projects/{project}/investigations/{investigation}.') ([pscustomobject]@{ investigationName = $invPath; conversationId = $convId; projectName = $Project })
        }
    }

    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 5 · investigation and conversation (FR5.4)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

<#
.SYNOPSIS  Stage 5 / FR5.5 — send the hero prompt and poll the response.
.DESCRIPTION Calls the Discovery responses route with array message content and no api-version on the responses URL. Spec: ../../script-specs/stage5-certification/stage5_certify.md
#>
function Invoke-Stage5SendPromptPoll {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [string]$JsonPath,
        [switch]$PassThru,
        [string]$Workspace,
        [string]$ConversationId,
        [string]$Agent,
        [string]$Prompt,
        [int]$PollSeconds = 5,
        [int]$TimeoutSeconds = 900,
        [string]$ResponsePath
    )
    $cfg = Get-OnboardingConfig -Path $ConfigPath
    $results = [System.Collections.Generic.List[object]]::new()
    function Get-CfgString { param([object]$Object, [string]$Name, [string]$Default = '') if ($Object -and $Object.PSObject.Properties.Name -contains $Name -and $Object.$Name) { [string]$Object.$Name } else { $Default } }
    function Get-DiscoveryToken { (Invoke-Az -Args @('account', 'get-access-token', '--resource', 'https://discovery.azure.com', '--query', 'accessToken', '-o', 'tsv')).Trim() }
    function Invoke-DiscoveryJson {
        param([string]$Method, [string]$Uri, [object]$Body = $null)
        $headers = @{ Authorization = "Bearer $(Get-DiscoveryToken)"; Accept = 'application/json' }
        if ($Body) { $headers['Content-Type'] = 'application/json' }
        $json = if ($Body) { $Body | ConvertTo-Json -Depth 30 } else { $null }
        $resp = Invoke-WebRequest -Method $Method -Uri $Uri -Headers $headers -Body $json -SkipHttpErrorCheck
        $content = if ($resp.Content) { try { $resp.Content | ConvertFrom-Json } catch { $resp.Content } } else { $null }
        [pscustomobject]@{ StatusCode = [int]$resp.StatusCode; Body = $content }
    }
    function Add-Result { param([string]$Id, [string]$Name, [string]$Status, [string]$Detail, [string]$Remediation = '', [object]$Data = $null) $results.Add((New-CheckResult -Id $Id -Name $Name -Status $Status -Fr 'FR5.5' -Detail $Detail -Remediation $Remediation -Data $Data)) }

    $Workspace = if ($Workspace) { $Workspace } else { Get-CfgString $cfg.names 'workspace' }
    $Agent = if ($Agent) { $Agent } else { Get-CfgString $cfg.names 'agent' 'hero-agent' }
    if (-not $Prompt) {
        $tool = Get-CfgString $cfg.names 'tool' 'hero-tool'
        $Prompt = "Using the $tool tool, run Python to generate a deterministic 12-row table of SHA256 hashes for the strings stage5-hero-1 through stage5-hero-12. Show the Python script you ran and its complete stdout."
    }
    if (-not $Workspace -or -not $ConversationId -or -not $Agent) {
        Add-Result 'fr5-5-inputs' 'response inputs' 'Fail' 'Workspace, ConversationId, or Agent is missing.' 'Pass -ConversationId from create_investigation_conversation.ps1 and configure workspace/agent names.'
    } else {
        $base = "https://$Workspace.workspace.discovery.azure.com"
        $sendBody = @{
            input = @(@{
                    type    = 'message'
                    role    = 'user'
                    content = @(@{ type = 'input_text'; text = $Prompt })
                })
            agent = @{ type = 'agent_reference'; name = $Agent }
        }
        $send = Invoke-DiscoveryJson -Method 'POST' -Uri "$base/conversations/$ConversationId/openai/responses" -Body $sendBody
        $rid = if ($send.Body -and $send.Body.id) { [string]$send.Body.id } else { '' }
        $sent = $send.StatusCode -in @(200, 201, 202) -and $rid
        Add-Result 'fr5-5-response-started' 'hero response started' ($sent ? 'Pass' : 'Fail') "responseId=$rid statusCode=$($send.StatusCode)" ($sent ? '' : 'Send content as an array of parts and do not add api-version to the responses route.') ([pscustomobject]@{ responseId = $rid; conversationId = $ConversationId })
        if ($sent) {
            $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
            $final = $null
            $status = ''
            while ((Get-Date) -lt $deadline) {
                Start-Sleep -Seconds $PollSeconds
                $poll = Invoke-DiscoveryJson -Method 'GET' -Uri "$base/conversations/$ConversationId/openai/responses/$rid"
                $final = $poll.Body
                $status = if ($final -and $final.status) { [string]$final.status } else { '' }
                if ($status -in @('completed', 'failed', 'cancelled', 'expired', 'incomplete')) { break }
            }
            if ($ResponsePath -and $final) {
                $dir = Split-Path -Parent $ResponsePath
                if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
                $final | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $ResponsePath -Encoding utf8
            }
            $ok = $status -eq 'completed'
            Add-Result 'fr5-5-response-completed' 'hero response completed' ($ok ? 'Pass' : 'Fail') "responseId=$rid status=$status" ($ok ? '' : 'Inspect response error/last_error/incomplete_details; first tool runs may take several minutes.') ([pscustomobject]@{ responseId = $rid; conversationId = $ConversationId; status = $status; responsePath = $ResponsePath; response = $final })
        }
    }

    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 5 · send prompt and poll (FR5.5)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

<#
.SYNOPSIS  Stage 5 / FR5.6 — assert the response contains a real tool invocation.
.DESCRIPTION Fails completed responses that lack function_call/function_call_output evidence and Foundry tracing evidence. Spec: ../../script-specs/stage5-certification/stage5_certify.md
#>
function Invoke-Stage5AssertToolInvocation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [string]$JsonPath,
        [switch]$PassThru,
        [Parameter(ValueFromPipeline)][object]$Response,
        [string]$ResponsePath,
        [switch]$TracingVisible
    )
    begin {
        $cfg = Get-OnboardingConfig -Path $ConfigPath
        $null = $cfg
        $results = [System.Collections.Generic.List[object]]::new()
    }
    process {
        if ($Response) { $script:responseObject = $Response }
    }
    end {
        if (-not $script:responseObject -and $ResponsePath) {
            if (Test-Path -LiteralPath $ResponsePath) { $script:responseObject = Get-Content -LiteralPath $ResponsePath -Raw | ConvertFrom-Json }
        }
        if (-not $script:responseObject) {
            $results.Add((New-CheckResult -Id 'fr5-6-response-input' -Name 'response object supplied' -Status 'Fail' -Fr 'FR5.6' -Detail 'No response object or -ResponsePath was supplied.' -Remediation 'Pass the final response JSON from send_prompt_poll.ps1.'))
        } else {
            $resp = $script:responseObject
            $calls = [System.Collections.Generic.List[string]]::new()
            $outputs = [System.Collections.Generic.List[string]]::new()
            foreach ($item in @($resp.output)) {
                if (-not $item -or -not ($item.PSObject.Properties.Name -contains 'type')) { continue }
                if ($item.type -eq 'function_call') {
                    $name = if ($item.PSObject.Properties.Name -contains 'name') { [string]$item.name } else { '' }
                    $calls.Add($name)
                } elseif ($item.type -eq 'function_call_output') {
                    $out = if ($item.PSObject.Properties.Name -contains 'output') { [string]$item.output } else { '' }
                    $outputs.Add($out)
                }
            }
            $completed = ($resp.PSObject.Properties.Name -contains 'status' -and $resp.status -eq 'completed')
            $toolCallPresent = $calls.Count -gt 0 -and $outputs.Count -gt 0
            $nodePoolCalled = @($calls | Where-Object { $_ -match 'GetNodePoolContext' }).Count -gt 0
            $traceProps = @('traceId', 'foundryTraceId', 'runId', 'tracingVisible')
            $traceEvidence = $false
            foreach ($p in $traceProps) {
                if ($resp.PSObject.Properties.Name -contains $p -and $resp.$p) { $traceEvidence = $true }
            }
            $traceEvidence = $traceEvidence -or [bool]$TracingVisible
            $ok = $completed -and $toolCallPresent -and $traceEvidence
            $detail = "completed=$completed functionCalls=$($calls.Count) functionOutputs=$($outputs.Count) nodePoolContext=$nodePoolCalled tracingVisible=$traceEvidence calls=$($calls -join ',')"
            $results.Add((New-CheckResult -Id 'fr5-6-tool-invoked' -Name 'real tool invocation present' -Status ($ok ? 'Pass' : 'Fail') -Fr 'FR5.6' -Detail $detail -Remediation ($ok ? '' : 'Completed is not enough: require function_call/function_call_output items and Foundry tracing evidence. Confirm GetNodePoolContext is in instructions and tracing shows the run.') -Data ([pscustomobject]@{ completed = $completed; toolCallPresent = $toolCallPresent; tracingVisible = $traceEvidence; calls = $calls.ToArray(); outputCount = $outputs.Count; nodePoolContext = $nodePoolCalled; pass = $ok })))
        }
        if ($PassThru) { return $results.ToArray() }
        $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 5 · assert tool invocation (FR5.6)' -JsonPath $JsonPath
        Complete-Stage -Results $results.ToArray()
    }
}

<#
.SYNOPSIS  Stage 5 / FR5.7 — summarize per-service certification evidence.
.DESCRIPTION Combines Stage 5 state with ARM reads for service provisioning states. Spec: ../../script-specs/stage5-certification/stage5_certify.md
#>
function Invoke-Stage5VerificationSummary {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [string]$JsonPath,
        [switch]$PassThru,
        [string]$StateFile,
        [string]$ResourceGroup,
        [string]$Workspace,
        [string]$Project,
        [string]$ChatModel,
        [string]$Supercomputer,
        [string]$ToolArmId
    )
    $cfg = Get-OnboardingConfig -Path $ConfigPath
    $results = [System.Collections.Generic.List[object]]::new()
    $api = '2026-06-01'
    function Get-CfgString { param([object]$Object, [string]$Name, [string]$Default = '') if ($Object -and $Object.PSObject.Properties.Name -contains $Name -and $Object.$Name) { [string]$Object.$Name } else { $Default } }
    function Add-Result { param([string]$Id, [string]$Name, [string]$Status, [string]$Detail, [string]$Remediation = '', [object]$Data = $null) $results.Add((New-CheckResult -Id $Id -Name $Name -Status $Status -Fr 'FR5.7' -Detail $Detail -Remediation $Remediation -Data $Data)) }
    function Get-StateBool {
        param([object]$State, [string]$Name)
        if (-not $State -or -not ($State.PSObject.Properties.Name -contains $Name)) { return $false }
        return [bool]$State.$Name
    }
    function Test-ArmSucceeded {
        param([string]$Id)
        if (-not $Id) { return [pscustomobject]@{ ok = $false; state = ''; id = $Id } }
        $r = Get-AzJson -Args @('resource', 'show', '--ids', $Id, '--api-version', $api) -AllowFail
        $state = if ($r -and $r.properties -and $r.properties.provisioningState) { [string]$r.properties.provisioningState } else { '' }
        [pscustomobject]@{ ok = ($state -eq 'Succeeded'); state = $state; id = $Id }
    }

    $state = if ($StateFile -and (Test-Path -LiteralPath $StateFile)) { Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json } else { $null }
    $ResourceGroup = if ($ResourceGroup) { $ResourceGroup } else { Get-CfgString $cfg 'resourceGroup' (Get-CfgString $cfg 'deploymentResourceGroup') }
    $Workspace = if ($Workspace) { $Workspace } else { Get-CfgString $cfg.names 'workspace' }
    $Project = if ($Project) { $Project } else { Get-CfgString $cfg.names 'project' }
    $ChatModel = if ($ChatModel) { $ChatModel } else { Get-CfgString $cfg.names 'chatModel' (Get-CfgString $cfg.names 'chatModelDeployment' 'gpt-5-4') }
    $Supercomputer = if ($Supercomputer) { $Supercomputer } else { Get-CfgString $cfg.names 'supercomputer' }
    if (-not $ToolArmId -and $ResourceGroup) { $ToolArmId = "/subscriptions/$($cfg.subscriptionId)/resourceGroups/$ResourceGroup/providers/Microsoft.Discovery/tools/$(Get-CfgString $cfg.names 'tool' 'hero-tool')" }

    if (-not $ResourceGroup) {
        Add-Result 'fr5-7-resource-group' 'resource group resolved' 'Fail' 'Resource group is missing.' 'Pass -ResourceGroup or set resourceGroup in config.'
    } else {
        $baseId = "/subscriptions/$($cfg.subscriptionId)/resourceGroups/$ResourceGroup/providers/Microsoft.Discovery"
        foreach ($svc in @(
                @{ Name = 'supercomputer'; Id = "$baseId/supercomputers/$Supercomputer" },
                @{ Name = 'workspace'; Id = "$baseId/workspaces/$Workspace" },
                @{ Name = 'project'; Id = "$baseId/workspaces/$Workspace/projects/$Project" },
                @{ Name = 'chat-model'; Id = "$baseId/workspaces/$Workspace/chatModelDeployments/$ChatModel" },
                @{ Name = 'tool'; Id = $ToolArmId }
            )) {
            $arm = Test-ArmSucceeded -Id $svc.Id
            Add-Result "fr5-7-$($svc.Name)" "$($svc.Name) ARM state" ($arm.ok ? 'Pass' : 'Fail') "state=$($arm.state) id=$($arm.id)" ($arm.ok ? '' : 'Resource must be Succeeded before certification.') $arm
        }
    }

    if ($cfg.PSObject.Properties.Name -contains 'bookshelf' -and $cfg.bookshelf -and $cfg.bookshelf.inScope) {
        $approved = 0
        $dns = 0
        foreach ($rg in @($ResourceGroup, (Get-CfgString $cfg.network 'networkResourceGroup')) | Where-Object { $_ } | Sort-Object -Unique) {
            $pes = @(Get-AzJson -Args @('network', 'private-endpoint', 'list', '-g', $rg) -AllowFail)
            foreach ($pe in $pes) {
                $isBookshelf = "$($pe.name) $($pe.id)" -match 'bookshelf|storage'
                if (-not $isBookshelf) { continue }
                foreach ($conn in @($pe.privateLinkServiceConnections)) {
                    if ($conn.privateLinkServiceConnectionState.status -eq 'Approved') { $approved++ }
                }
                if (@($pe.customDnsConfigs).Count -gt 0) { $dns++ }
            }
        }
        $ok = $approved -ge 3 -and $dns -ge 3
        Add-Result 'fr5-7-bookshelf' 'bookshelf private endpoints' ($ok ? 'Pass' : 'Fail') "approved=$approved dns=$dns expected=3" ($ok ? '' : 'Approve the three bookshelf private endpoints and confirm custom DNS configs.')
    } else {
        Add-Result 'fr5-7-bookshelf' 'bookshelf private endpoints' 'Skip' 'Bookshelf is out of scope for this config.'
    }

    foreach ($item in @(
            @{ Id = 'tool-created'; Name = 'tool created'; Key = 'toolCreated' },
            @{ Id = 'agent-created'; Name = 'agent created'; Key = 'agentCreated' },
            @{ Id = 'tool-bound'; Name = 'tool bound'; Key = 'toolBound' },
            @{ Id = 'conversation-completed'; Name = 'conversation completed'; Key = 'conversationCompleted' },
            @{ Id = 'tool-invoked'; Name = 'tool actually invoked'; Key = 'toolInvoked' }
        )) {
        $ok = Get-StateBool -State $state -Name $item.Key
        Add-Result "fr5-7-$($item.Id)" $item.Name ($ok ? 'Pass' : 'Fail') "$($item.Key)=$ok" ($ok ? '' : 'Re-run the corresponding Stage 5 step and provide the orchestrator state file.')
    }

    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 5 · verification summary (FR5.7)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

$cfg = Get-OnboardingConfig -Path $ConfigPath
$results = [System.Collections.Generic.List[object]]::new()

Assert-AzLogin -SubscriptionId $cfg.subscriptionId
$ResourceGroup = if ($ResourceGroup) { $ResourceGroup } else { Get-CfgString $cfg 'resourceGroup' (Get-CfgString $cfg 'deploymentResourceGroup') }
$Workspace = if ($Workspace) { $Workspace } else { Get-CfgString $cfg.names 'workspace' }
$Project = if ($Project) { $Project } else { Get-CfgString $cfg.names 'project' }
$ChatModel = if ($ChatModel) { $ChatModel } else { Get-CfgString $cfg.names 'chatModel' (Get-CfgString $cfg.names 'chatModelDeployment' 'gpt-5-4') }
$toolName = Get-CfgString $cfg.names 'tool' 'hero-tool'
$agentName = Get-CfgString $cfg.names 'agent' 'hero-agent'
$investigation = Get-CfgString $cfg.names 'investigation' 'hero-inv'
if (-not $ToolArmId -and $ResourceGroup) { $ToolArmId = "/subscriptions/$($cfg.subscriptionId)/resourceGroups/$ResourceGroup/providers/Microsoft.Discovery/tools/$toolName" }

$outDir = Join-Path $PSScriptRoot 'out'
if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$statePath = Join-Path $outDir "stage5-state-$stamp.json"
$responsePath = Join-Path $outDir "stage5-response-$stamp.json"
$state = @{
    workspace = $Workspace; project = $Project; chatModel = $ChatModel; toolArmId = $ToolArmId
    connectivity = $false; toolCreated = $false; agentCreated = $false; toolBound = $false
    investigationCreated = $false; conversationCompleted = $false; toolInvoked = $false
}

$step = Invoke-Stage5ConnectivityCheck -ConfigPath $ConfigPath -ResourceGroup $ResourceGroup -PassThru
Add-Many $step
$state.connectivity = -not (Has-Fail $step)
Write-State -Path $statePath -State $state
if ($state.connectivity) {
    $step = Invoke-Stage5CreateTool -ConfigPath $ConfigPath -ResourceGroup $ResourceGroup -Workspace $Workspace -ToolArmId $ToolArmId -Tool $toolName -PassThru
    Add-Many $step
    $state.toolCreated = -not (Has-Fail $step)
    $toolData = Last-DataById -Items $step -Id 'fr5-2-tool-created'
    if ($toolData -and $toolData.toolId) { $ToolArmId = [string]$toolData.toolId; $state.toolArmId = $ToolArmId }
    Write-State -Path $statePath -State $state
}
if ($state.toolCreated) {
    $step = Invoke-Stage5CreateAgentBindTool -ConfigPath $ConfigPath -ResourceGroup $ResourceGroup -Workspace $Workspace -Project $Project -ChatModel $ChatModel -Agent $agentName -ToolArmId $ToolArmId -PassThru
    Add-Many $step
    $state.agentCreated = @($step | Where-Object { $_.id -eq 'fr5-3-agent-created' -and $_.status -eq 'Pass' }).Count -gt 0
    $state.toolBound = @($step | Where-Object { $_.id -eq 'fr5-3-tool-bound' -and $_.status -eq 'Pass' }).Count -gt 0
    Write-State -Path $statePath -State $state
}
if ($state.agentCreated -and $state.toolBound) {
    $step = Invoke-Stage5CreateInvestigationConversation -ConfigPath $ConfigPath -Workspace $Workspace -Project $Project -Investigation $investigation -PassThru
    Add-Many $step
    $convData = Last-DataById -Items $step -Id 'fr5-4-conversation'
    $conversationId = if ($convData -and $convData.conversationId) { [string]$convData.conversationId } else { '' }
    $state.investigationCreated = @($step | Where-Object { $_.id -eq 'fr5-4-investigation' -and $_.status -eq 'Pass' }).Count -gt 0
    $state.conversationId = $conversationId
    Write-State -Path $statePath -State $state
}
if ($state.conversationId) {
    $step = Invoke-Stage5SendPromptPoll -ConfigPath $ConfigPath -Workspace $Workspace -ConversationId $state.conversationId -Agent $agentName -Prompt $Prompt -ResponsePath $responsePath -PassThru
    Add-Many $step
    $state.conversationCompleted = @($step | Where-Object { $_.id -eq 'fr5-5-response-completed' -and $_.status -eq 'Pass' }).Count -gt 0
    $state.responsePath = $responsePath
    Write-State -Path $statePath -State $state
}
if ($state.conversationCompleted) {
    $step = Invoke-Stage5AssertToolInvocation -ConfigPath $ConfigPath -ResponsePath $responsePath -PassThru
    Add-Many $step
    $state.toolInvoked = @($step | Where-Object { $_.id -eq 'fr5-6-tool-invoked' -and $_.status -eq 'Pass' }).Count -gt 0
    Write-State -Path $statePath -State $state
}

$summary = Invoke-Stage5VerificationSummary -ConfigPath $ConfigPath -StateFile $statePath -ResourceGroup $ResourceGroup -Workspace $Workspace -Project $Project -ChatModel $ChatModel -ToolArmId $ToolArmId -PassThru
Add-Many $summary
$certified = -not (Has-Fail $results.ToArray()) -and [bool]$state.toolInvoked
$results.Add((New-CheckResult -Id 'fr5-certification-verdict' -Name 'Stage 5 certification verdict' -Status ($certified ? 'Pass' : 'Fail') -Fr 'FR5.1-FR5.7' -Detail ($certified ? 'CERTIFIED' : 'NOT CERTIFIED') -Remediation ($certified ? '' : 'Any failed check blocks certification; a run without a function_call item is not certified.') -Data ([pscustomobject]@{ verdict = ($certified ? 'CERTIFIED' : 'NOT CERTIFIED'); stateFile = $statePath; responsePath = $responsePath })))

$extra = [pscustomobject]@{ verdict = ($certified ? 'CERTIFIED' : 'NOT CERTIFIED'); stateFile = $statePath; responsePath = $responsePath }
$null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 5 · hero use-case certification (FR5.1-FR5.7)' -JsonPath $JsonPath -Extra $extra
Complete-Stage -Results $results.ToArray()

