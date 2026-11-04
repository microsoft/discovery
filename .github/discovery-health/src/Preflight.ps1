# Preflight: tools, configuration, Azure access, and discovery-github-test tag guards.

function Test-DhResourceTagged {
  param([System.Collections.IDictionary]$Body, [string]$Tag)
  return ([string](Get-DhValue $Body ('tags.' + $Tag) '') -eq 'true')
}

function Invoke-DhPreflight {
  <#
  .SYNOPSIS Returns @{ ok; problems; warnings } and records the _run/preflight result.
  #>
  param([System.Collections.IDictionary]$Config, [string[]]$Stages)
  $problems = [System.Collections.Generic.List[object]]::new()
  $warnings = [System.Collections.Generic.List[object]]::new()
  $azureStages = @($Stages | Where-Object { $_ -in $script:DhStages })
  foreach ($command in @('git', 'tar')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { $problems.Add(@{ code = 'DH-PRE-004'; params = @{ command = $command } }) }
  }
  if ($azureStages.Count -gt 0 -and -not (Get-Command 'az' -ErrorAction SilentlyContinue)) { $problems.Add(@{ code = 'DH-PRE-004'; params = @{ command = 'az' } }) }
  $configProblems = @(Test-DhConfig -Config $Config -Stages $Stages)
  if ($configProblems.Count -gt 0) {
    $fields = @($configProblems | ForEach-Object { ($_ -replace '^(missing|schema): ', '') -replace '[^\w .:/\-]', '' } | Select-Object -First 6)
    $problems.Add(@{ code = 'DH-PRE-003'; params = @{ fields = ($fields -join '; ') } })
  }
  if ($problems.Count -eq 0 -and $azureStages.Count -gt 0) {
    if (Test-DhOidcAvailable) { try { Update-DhAzLogin -Force | Out-Null } catch { } }
    $account = Invoke-DhAz -Arguments @('account', 'set', '--subscription', [string]$Config.subscriptionId)
    if ($account.exitCode -ne 0) {
      $problems.Add(@{ code = 'DH-PRE-001'; params = @{} })
    } else {
      $rg = Invoke-DhRest -Uri ('https://management.azure.com/subscriptions/{0}/resourcegroups/{1}?api-version=2021-04-01' -f $Config.subscriptionId, $Config.resourceGroup)
      if ($rg.status -ne 200 -or -not (Test-DhResourceTagged -Body $rg.body -Tag $Config.testTag)) {
        $problems.Add(@{ code = 'DH-PRE-002'; params = @{ resource = 'resource group'; tag = $Config.testTag } })
      }
      if ($Stages | Where-Object { $_ -in @('build', 'image-smoke', 'tool-register') }) {
        $acr = Invoke-DhRest -Uri ('{0}/providers/Microsoft.ContainerRegistry/registries/{1}?api-version=2023-07-01' -f (Get-DhArmBase -Config $Config -ResourceGroup $Config.acrResourceGroup), $Config.acrName)
        if ($acr.status -ne 200 -or -not (Test-DhResourceTagged -Body $acr.body -Tag $Config.testTag)) {
          $problems.Add(@{ code = 'DH-PRE-002'; params = @{ resource = 'container registry'; tag = $Config.testTag } })
        }
      }
      $account = [string](Get-DhValue $Config 'evidenceStorage.account' '')
      if ($account) {
        $storage = Invoke-DhRest -Uri ('{0}/providers/Microsoft.Storage/storageAccounts/{1}?api-version=2023-01-01' -f (Get-DhArmBase -Config $Config -ResourceGroup (Get-DhValue $Config 'evidenceStorage.resourceGroup')), $account)
        if ($storage.status -ne 200 -or -not (Test-DhResourceTagged -Body $storage.body -Tag $Config.testTag)) {
          $script:DhEvidenceEnabled = $false
          $warnings.Add(@{ code = 'DH-PRE-002'; params = @{ resource = 'evidence storage'; tag = $Config.testTag } })
        }
      }
      if ($Stages | Where-Object { $_ -in @('tool-run', 'agent-register', 'round-trip') }) {
        $agents = Invoke-DhRest -Method GET -Audience discovery -Uri ('{0}/projects/{1}/agents?api-version={2}' -f $Config.workspaceEndpoint, [Uri]::EscapeDataString([string]$Config.project), $Config.apiVersion)
        if ($agents.status -ne 200) { $problems.Add(@{ code = 'DH-PRE-005'; params = @{ status = $agents.status } }) }
      }
      if ($Stages -contains 'tool-run') {
        $reachable = [System.Collections.Generic.List[object]]::new()
        foreach ($pool in @($Config.nodePools)) {
          $np = Invoke-DhRest -Uri ('https://management.azure.com{0}?api-version={1}' -f $pool.id, $Config.apiVersion)
          if ($np.status -eq 200) { $reachable.Add($pool) } else { $warnings.Add(@{ code = 'DH-PRE-006'; params = @{ nodepool = (($pool.id -split '/')[-1]); status = $np.status } }) }
        }
        $Config.nodePools = $reachable.ToArray()
      }
    }
  }
  $messages = @($problems | ForEach-Object { New-DhMessage -Level error -Code $_.code -Params $_.params }) + @($warnings | ForEach-Object { New-DhMessage -Level warning -Code $_.code -Params $_.params })
  $status = if ($problems.Count -gt 0) { 'failed' } elseif ($warnings.Count -gt 0) { 'warning' } else { 'passed' }
  $result = New-DhResult -Agent '_run' -Stage 'preflight' -Status $status -Category $(if ($problems.Count) { 'infrastructure' } else { '' }) -Messages $messages
  Save-DhResult -Result $result | Out-Null
  return @{ ok = ($problems.Count -eq 0); problems = $problems.ToArray(); warnings = $warnings.ToArray() }
}
