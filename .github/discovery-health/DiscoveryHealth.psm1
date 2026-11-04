# StrictMode 1.0: catch uninitialized variables while allowing absent keys in external
# JSON/YAML (API responses, tool.yaml, specs) to resolve to $null instead of throwing.
Set-StrictMode -Version 1.0

$script:DhRoot = $PSScriptRoot
foreach ($file in (Get-ChildItem -Path (Join-Path $PSScriptRoot 'src') -Filter '*.ps1' -Recurse | Sort-Object FullName)) {
  . $file.FullName
}

Export-ModuleMember -Function '*-Dh*'
