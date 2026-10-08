#Requires -Version 7.0
<#
.SYNOPSIS  Stage 5 / FR5.1-FR5.7 — run agent Q&A certification end to end.
.DESCRIPTION Orchestrates connectivity, agent creation (no tool), investigation/conversation, prompt polling, response verification, and summary. Spec: ../../script-specs/stage5-scenario-enablement/stage5_enable.md
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
.DESCRIPTION Creates an ephemeral Linux VM in the onboarding VNet, probes platform privatelink FQDNs, then removes the VM. Spec: ../../script-specs/stage5-scenario-enablement/stage5_enable.md
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
    function Get-WorkspaceManagedRg {
        param([object]$Config, [string]$DeployRg)
        $wsName = if ($Config.names -and ($Config.names.PSObject.Properties.Name -contains 'workspace') -and $Config.names.workspace) { [string]$Config.names.workspace } else { '' }
        if (-not $wsName -or -not $DeployRg) { return @() }
        $wsId = "/subscriptions/$($Config.subscriptionId)/resourceGroups/$DeployRg/providers/Microsoft.Discovery/workspaces/$wsName"
        $ws = Get-AzJson -Args @('resource', 'show', '--ids', $wsId, '--api-version', '2026-06-01') -AllowFail
        $mrg = ''
        if ($ws -and ($ws.PSObject.Properties.Name -contains 'properties') -and $ws.properties) {
            foreach ($p in @('managedResourceGroupId', 'managedResourceGroup')) {
                if (($ws.properties.PSObject.Properties.Name -contains $p) -and $ws.properties.$p) { $mrg = [string]$ws.properties.$p; break }
            }
        }
        if ($mrg -like '/subscriptions/*') { $mrg = ($mrg -split '/')[-1] }
        if ($mrg) { return @($mrg) }
        $groups = @(Get-AzJson -Args @('group', 'list', '--query', "[?starts_with(name, 'mrg-dwsp-$wsName')].name") -AllowFail)
        return @($groups | Where-Object { $_ })
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
    $managedRgs = Get-WorkspaceManagedRg -Config $cfg -DeployRg $ResourceGroup
    $probeFqdns = Get-ConfiguredFqdns -Config $cfg -ExplicitFqdn $Fqdn -ResourceGroups (@($ResourceGroup, $NetworkResourceGroup) + $managedRgs)

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
.SYNOPSIS  Stage 5 / FR5.3 — create a Discovery agent (no tool bound).
.DESCRIPTION Upserts the data-plane Q&A agent with an empty tools[] and scientist instructions. Spec: ../../script-specs/stage5-scenario-enablement/stage5_enable.md
#>
function Invoke-Stage5CreateAgent {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ConfigPath,
        [string]$JsonPath,
        [switch]$PassThru,
        [string]$Workspace,
        [string]$Project,
        [string]$ChatModel,
        [string]$Agent
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
    $Agent = if ($Agent) { $Agent } else { Get-CfgString $cfg.names 'qnaAgent' 'scientistQnAAgent' }
    $ChatModel = if ($ChatModel) { $ChatModel } else { Get-CfgString $cfg.names 'chatModel' (Get-CfgString $cfg.names 'chatModelDeployment' 'gpt-5-4') }

    if (-not $Workspace -or -not $Project) {
        Add-Result 'fr5-3-inputs' 'agent upsert inputs' 'Fail' 'Workspace or Project is missing.' 'Pass -Workspace and -Project or set config names.'
    } else {
        $base = "https://$Workspace.workspace.discovery.azure.com"
        $instructions = @"
    You are $Agent, a scientific question-answering assistant for Microsoft Discovery.

    ## RULE
    Answer the user's scientific questions directly and concisely from your own knowledge.
    You have no external tools bound, so do not claim to run code or call tools. If a question
    is outside your knowledge, say so plainly rather than inventing an answer.
"@
        $body = [ordered]@{
            name           = $Agent
            humanInTheLoop = 'Disabled'
            tools          = @()
            foundryDetails = [ordered]@{
                description = 'Stage 5 scientist Q&A agent (no Discovery tool bound).'
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
        Add-Result 'fr5-3-agent-created' 'Discovery agent upserted' ($created ? 'Pass' : 'Fail') "agent=$Agent statusCode=$($upsert.StatusCode) operationStatus=$opStatus" ($created ? '' : 'Confirm the workspace data-plane endpoint, model deployment name, and agent schema.') ([pscustomobject]@{ agentId = $Agent; model = $ChatModel })
    }

    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 5 · create agent (FR5.3)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

<#
.SYNOPSIS  Stage 5 / FR5.4 — create investigation and conversation.
.DESCRIPTION Creates the investigation first, then creates a conversation with the full investigationName path. Spec: ../../script-specs/stage5-scenario-enablement/stage5_enable.md
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
.SYNOPSIS  Stage 5 / FR5.5 — send the Q&A prompt and poll the response.
.DESCRIPTION Calls the Discovery responses route with array message content and no api-version on the responses URL. Spec: ../../script-specs/stage5-scenario-enablement/stage5_enable.md
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
    $Agent = if ($Agent) { $Agent } else { Get-CfgString $cfg.names 'qnaAgent' 'scientistQnAAgent' }
    if (-not $Prompt) {
        $Prompt = 'In two or three sentences, explain what CRISPR-Cas9 is and why it is significant for gene editing.'
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
        Add-Result 'fr5-5-response-started' 'agent response started' ($sent ? 'Pass' : 'Fail') "responseId=$rid statusCode=$($send.StatusCode)" ($sent ? '' : 'Send content as an array of parts and do not add api-version to the responses route.') ([pscustomobject]@{ responseId = $rid; conversationId = $ConversationId })
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
            Add-Result 'fr5-5-response-completed' 'agent response completed' ($ok ? 'Pass' : 'Fail') "responseId=$rid status=$status" ($ok ? '' : 'Inspect response error/last_error/incomplete_details; the first response may take a minute.') ([pscustomobject]@{ responseId = $rid; conversationId = $ConversationId; status = $status; responsePath = $ResponsePath; response = $final })
        }
    }

    if ($PassThru) { return $results.ToArray() }
    $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 5 · send prompt and poll (FR5.5)' -JsonPath $JsonPath
    Complete-Stage -Results $results.ToArray()
}

<#
.SYNOPSIS  Stage 5 / FR5.6 — verify the agent answered the prompt.
.DESCRIPTION Fails responses that did not complete or returned no assistant text. Spec: ../../script-specs/stage5-scenario-enablement/stage5_enable.md
#>
function Invoke-Stage5AssertResponse {
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
            $texts = [System.Collections.Generic.List[string]]::new()
            foreach ($item in @($resp.output)) {
                if (-not $item -or -not ($item.PSObject.Properties.Name -contains 'type')) { continue }
                if ($item.type -eq 'message') {
                    foreach ($part in @($item.content)) {
                        $t = if ($part -and $part.PSObject.Properties.Name -contains 'text') { [string]$part.text } else { '' }
                        if ($t) { $texts.Add($t) }
                    }
                }
            }
            $completed = ($resp.PSObject.Properties.Name -contains 'status' -and $resp.status -eq 'completed')
            $answer = ($texts -join "`n").Trim()
            $hasText = $answer.Length -gt 0
            $ok = $completed -and $hasText
            $preview = if ($answer.Length -gt 160) { $answer.Substring(0, 160) + '...' } else { $answer }
            $detail = "completed=$completed textParts=$($texts.Count) chars=$($answer.Length) preview=$preview"
            $results.Add((New-CheckResult -Id 'fr5-6-response-content' -Name 'agent answered prompt' -Status ($ok ? 'Pass' : 'Fail') -Fr 'FR5.6' -Detail $detail -Remediation ($ok ? '' : 'Response did not complete with assistant text. Inspect response error/last_error/incomplete_details and confirm the chat model deployment is healthy.') -Data ([pscustomobject]@{ completed = $completed; hasText = $hasText; chars = $answer.Length; answer = $answer; pass = $ok })))
        }
        if ($PassThru) { return $results.ToArray() }
        $null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 5 · verify agent response (FR5.6)' -JsonPath $JsonPath
        Complete-Stage -Results $results.ToArray()
    }
}

<#
.SYNOPSIS  Stage 5 / FR5.7 — summarize per-service certification evidence.
.DESCRIPTION Combines Stage 5 state with ARM reads for service provisioning states. Spec: ../../script-specs/stage5-scenario-enablement/stage5_enable.md
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

    if (-not $ResourceGroup) {
        Add-Result 'fr5-7-resource-group' 'resource group resolved' 'Fail' 'Resource group is missing.' 'Pass -ResourceGroup or set resourceGroup in config.'
    } else {
        $baseId = "/subscriptions/$($cfg.subscriptionId)/resourceGroups/$ResourceGroup/providers/Microsoft.Discovery"
        foreach ($svc in @(
                @{ Name = 'supercomputer'; Id = "$baseId/supercomputers/$Supercomputer" },
                @{ Name = 'workspace'; Id = "$baseId/workspaces/$Workspace" },
                @{ Name = 'project'; Id = "$baseId/workspaces/$Workspace/projects/$Project" },
                @{ Name = 'chat-model'; Id = "$baseId/workspaces/$Workspace/chatModelDeployments/$ChatModel" }
            )) {
            $arm = Test-ArmSucceeded -Id $svc.Id
            Add-Result "fr5-7-$($svc.Name)" "$($svc.Name) ARM state" ($arm.ok ? 'Pass' : 'Fail') "state=$($arm.state) id=$($arm.id)" ($arm.ok ? '' : 'Resource must be Succeeded before certification.') $arm
        }
    }

    if ($cfg.PSObject.Properties.Name -contains 'bookshelf' -and $cfg.bookshelf -and $cfg.bookshelf.inScope) {
        $approved = 0
        $dns = 0
        $qualified = 0
        foreach ($rg in @($ResourceGroup, (Get-CfgString $cfg.network 'networkResourceGroup')) | Where-Object { $_ } | Sort-Object -Unique) {
            $pes = @(Get-AzJson -Args @('network', 'private-endpoint', 'list', '-g', $rg) -AllowFail)
            foreach ($pe in $pes) {
                $isBookshelf = "$($pe.name) $($pe.id)" -match 'bookshelf|storage'
                if (-not $isBookshelf) { continue }
                $peApproved = @($pe.privateLinkServiceConnections | Where-Object { $_.privateLinkServiceConnectionState.status -eq 'Approved' }).Count -gt 0
                $peDns = @($pe.customDnsConfigs).Count -gt 0
                if ($peApproved) { $approved++ }
                if ($peDns) { $dns++ }
                if ($peApproved -and $peDns) { $qualified++ }
            }
        }
        $ok = $qualified -ge 3
        Add-Result 'fr5-7-bookshelf' 'bookshelf private endpoints' ($ok ? 'Pass' : 'Fail') "qualified=$qualified approved=$approved dns=$dns expected=3" ($ok ? '' : 'Ensure at least three bookshelf private endpoints are each both Approved and have a non-empty custom DNS config.')
    } else {
        Add-Result 'fr5-7-bookshelf' 'bookshelf private endpoints' 'Skip' 'Bookshelf is out of scope for this config.'
    }

    foreach ($item in @(
            @{ Id = 'agent-created'; Name = 'agent created'; Key = 'agentCreated' },
            @{ Id = 'conversation-completed'; Name = 'conversation completed'; Key = 'conversationCompleted' },
            @{ Id = 'response-received'; Name = 'agent answered prompt'; Key = 'responseReceived' }
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
$agentName = Get-CfgString $cfg.names 'qnaAgent' 'scientistQnAAgent'
$investigation = Get-CfgString $cfg.names 'investigation' 'hero-inv'

$outDir = Join-Path $PSScriptRoot 'out'
if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$statePath = Join-Path $outDir "stage5-state-$stamp.json"
$responsePath = Join-Path $outDir "stage5-response-$stamp.json"
$state = @{
    workspace = $Workspace; project = $Project; chatModel = $ChatModel
    connectivity = $false; agentCreated = $false
    investigationCreated = $false; conversationCompleted = $false; responseReceived = $false
}

$step = Invoke-Stage5ConnectivityCheck -ConfigPath $ConfigPath -ResourceGroup $ResourceGroup -PassThru
Add-Many $step
$state.connectivity = -not (Has-Fail $step)
Write-State -Path $statePath -State $state
if ($state.connectivity) {
    $step = Invoke-Stage5CreateAgent -ConfigPath $ConfigPath -Workspace $Workspace -Project $Project -ChatModel $ChatModel -Agent $agentName -PassThru
    Add-Many $step
    $state.agentCreated = @($step | Where-Object { $_.id -eq 'fr5-3-agent-created' -and $_.status -eq 'Pass' }).Count -gt 0
    Write-State -Path $statePath -State $state
}
if ($state.agentCreated) {
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
    $step = Invoke-Stage5AssertResponse -ConfigPath $ConfigPath -ResponsePath $responsePath -PassThru
    Add-Many $step
    $state.responseReceived = @($step | Where-Object { $_.id -eq 'fr5-6-response-content' -and $_.status -eq 'Pass' }).Count -gt 0
    Write-State -Path $statePath -State $state
}

$summary = Invoke-Stage5VerificationSummary -ConfigPath $ConfigPath -StateFile $statePath -ResourceGroup $ResourceGroup -Workspace $Workspace -Project $Project -ChatModel $ChatModel -PassThru
Add-Many $summary
$certified = -not (Has-Fail $results.ToArray()) -and [bool]$state.responseReceived
$results.Add((New-CheckResult -Id 'fr5-certification-verdict' -Name 'Stage 5 certification verdict' -Status ($certified ? 'Pass' : 'Fail') -Fr 'FR5.1-FR5.7' -Detail ($certified ? 'CERTIFIED' : 'NOT CERTIFIED') -Remediation ($certified ? '' : 'Any failed check blocks certification; a run without an agent answer is not certified.') -Data ([pscustomobject]@{ verdict = ($certified ? 'CERTIFIED' : 'NOT CERTIFIED'); stateFile = $statePath; responsePath = $responsePath })))

$extra = [pscustomobject]@{ verdict = ($certified ? 'CERTIFIED' : 'NOT CERTIFIED'); stateFile = $statePath; responsePath = $responsePath }
$null = Write-OnboardingReport -Results $results.ToArray() -Title 'Stage 5 · agent Q&A certification (FR5.1-FR5.7)' -JsonPath $JsonPath -Extra $extra
Complete-Stage -Results $results.ToArray()

