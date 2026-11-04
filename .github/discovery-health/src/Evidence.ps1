# Private evidence (complete raw logs/payloads), run checkpoints and the image ledger.
# Local runs keep evidence on disk. CI streams it to a private, tagged storage account;
# public artifacts never include the evidence directory.

$script:DhEvidenceEnabled = $true

function Get-DhEvidenceBase {
  $account = [string](Get-DhValue $script:Dh.Config 'evidenceStorage.account')
  if (-not $account -or -not $script:DhEvidenceEnabled) { return '' }
  $container = [string](Get-DhValue $script:Dh.Config 'evidenceStorage.container' 'discovery-health')
  return ('https://{0}.blob.core.windows.net/{1}' -f $account, $container)
}

function Get-DhBlobPrefix {
  return ('{0}/runs/{1}' -f (Get-DhValue $script:Dh.Config 'testTag' 'discovery-github-test'), $script:Dh.RunId)
}

function Send-DhBlob {
  param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)]$Content, [string]$ContentType = 'text/plain; charset=utf-8')
  $base = Get-DhEvidenceBase
  if (-not $base) { return $false }
  $uri = '{0}/{1}' -f $base, (($Name -split '/' | ForEach-Object { [Uri]::EscapeDataString($_) }) -join '/')
  $headers = @{ 'x-ms-version' = '2023-11-03'; 'x-ms-blob-type' = 'BlockBlob' }
  $response = Invoke-DhRest -Method PUT -Uri $uri -Audience storage -Body $Content -ContentType $ContentType -Headers $headers -MaxAttempts 3
  if ($response.status -in @(200, 201)) { return $true }
  if ($response.status -in @(0, 401, 403, 404)) {
    $script:DhEvidenceEnabled = $false
    Write-DhLog -Level warn -Message (Get-DhMessage -Code 'DH-PRE-008' -Params @{ status = $response.status })
  }
  return $false
}

function Send-DhCheckpoint {
  param([Parameter(Mandatory)][string]$RelativePath, [Parameter(Mandatory)][string]$Content)
  if (-not (Get-DhEvidenceBase)) { return }
  $name = '{0}/{1}' -f (Get-DhBlobPrefix), ($RelativePath -replace '\\', '/')
  Send-DhBlob -Name $name -Content $Content -ContentType 'application/json' | Out-Null
}

function Save-DhEvidence {
  <#
  .SYNOPSIS Stores raw evidence privately and returns its relative reference.
  #>
  param(
    [Parameter(Mandatory)][string]$Agent,
    [string]$Tool = '',
    [Parameter(Mandatory)][string]$Stage,
    [Parameter(Mandatory)][string]$Name,
    [AllowEmptyString()]$Content
  )
  $toolPart = if ($Tool) { $Tool } else { '_agent' }
  $relative = ('evidence/{0}/{1}/{2}/{3}' -f $Agent, $toolPart, $Stage, $Name)
  $text = if ($Content -is [string]) { $Content } else { ConvertTo-DhJson $Content }
  try {
    Write-DhTextFile -Path (Join-Path $script:Dh.OutputDir $relative) -Content $text
  } catch {
    Write-DhLog -Level warn -Message ('Could not write evidence {0}: {1}' -f $relative, $_.Exception.Message)
  }
  try {
    if (Get-DhEvidenceBase) { Send-DhBlob -Name ('{0}/{1}' -f (Get-DhBlobPrefix), $relative) -Content $text | Out-Null }
  } catch {
    Write-DhLog -Level warn -Message ('Could not upload evidence {0}.' -f $relative)
  }
  return $relative
}

function Get-DhBlobList {
  param([Parameter(Mandatory)][string]$Prefix)
  $base = Get-DhEvidenceBase
  if (-not $base) { return @() }
  $names = [System.Collections.Generic.List[string]]::new()
  $marker = ''
  do {
    $uri = '{0}?restype=container&comp=list&prefix={1}{2}' -f $base, [Uri]::EscapeDataString($Prefix), $(if ($marker) { '&marker=' + [Uri]::EscapeDataString($marker) } else { '' })
    $response = Invoke-DhRest -Method GET -Uri $uri -Audience storage -Headers @{ 'x-ms-version' = '2023-11-03' }
    if ($response.status -ne 200) { break }
    $xml = [xml]($response.raw -replace '^\xEF\xBB\xBF', '' -replace '^\uFEFF', '')
    foreach ($blob in @($xml.EnumerationResults.Blobs.Blob)) { if ($blob) { $names.Add([string]$blob.Name) } }
    $marker = [string]$xml.EnumerationResults.NextMarker
  } while ($marker)
  return $names.ToArray()
}

function Get-DhBlobText {
  param([Parameter(Mandatory)][string]$Name)
  $base = Get-DhEvidenceBase
  if (-not $base) { return $null }
  $uri = '{0}/{1}' -f $base, (($Name -split '/' | ForEach-Object { [Uri]::EscapeDataString($_) }) -join '/')
  $response = Invoke-DhRest -Method GET -Uri $uri -Audience storage -Headers @{ 'x-ms-version' = '2023-11-03' }
  if ($response.status -eq 200) { return [string]$response.raw }
  return $null
}

function Save-DhRunEvidenceCopy {
  <#
  .SYNOPSIS Downloads all private evidence and checkpoints for a run (maintainer use).
  #>
  param([Parameter(Mandatory)][string]$RunId, [Parameter(Mandatory)][string]$Destination)
  $prefix = '{0}/runs/{1}/' -f (Get-DhValue $script:Dh.Config 'testTag' 'discovery-github-test'), $RunId
  $count = 0
  foreach ($name in (Get-DhBlobList -Prefix $prefix)) {
    $text = Get-DhBlobText -Name $name
    if ($null -eq $text) { continue }
    Write-DhTextFile -Path (Join-Path $Destination ($name.Substring($prefix.Length))) -Content $text
    $count++
  }
  return $count
}

function Get-DhLedgerDir {
  $dir = [string](Get-DhValue $script:Dh.Config 'ledgerDir')
  if (-not $dir) { $dir = Join-Path (Split-Path -Parent $script:Dh.OutputDir) 'ledger' }
  return $dir
}

function Get-DhLedgerEntry {
  param([Parameter(Mandatory)][string]$Key)
  $local = Join-Path (Get-DhLedgerDir) ($Key + '.json')
  if (Test-Path -LiteralPath $local) { try { return (Read-DhJsonFile -Path $local) } catch { } }
  if (Get-DhEvidenceBase) {
    $text = Get-DhBlobText -Name ('{0}/ledger/{1}.json' -f (Get-DhValue $script:Dh.Config 'testTag' 'discovery-github-test'), $Key)
    if ($text) { try { return (ConvertFrom-DhJson $text) } catch { } }
  }
  return $null
}

function Set-DhLedgerEntry {
  param([Parameter(Mandatory)][string]$Key, [Parameter(Mandatory)][System.Collections.IDictionary]$Value)
  $json = ConvertTo-DhJson $Value
  try { Write-DhTextFile -Path (Join-Path (Get-DhLedgerDir) ($Key + '.json')) -Content $json } catch { }
  if (Get-DhEvidenceBase) {
    Send-DhBlob -Name ('{0}/ledger/{1}.json' -f (Get-DhValue $script:Dh.Config 'testTag' 'discovery-github-test'), $Key) -Content $json -ContentType 'application/json' | Out-Null
  }
}
