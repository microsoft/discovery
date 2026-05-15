# PowerShell script to delete S2ROIP agents by calling Remove-DiscoveryAgent

# Define resource group and subscription ID
$resourceGroup = '<add your RG name here>'
$subscriptionId = '<add your subscription ID here>'

# List of S2R agent names to delete (matching create-agents.ps1)
$agents = @(
    'Planner',
    'RouterOSS',
    'VerilogCreateNoTool',
    'ChkSyntaxDesign',
    'FixSyntaxDesign',
    'GenSpecs',
    'GenScenarios',
    'GenBehavior',
    'GenAssertions',
    'GenStimulus',
    'GenGoldenDUT',
    'GenFinalTB',
    'SiliconSummarizer',
    'SNPS-PPA-TSMC-N3P'
)

foreach ($agent in $agents) {
    try {
        Remove-DiscoveryAgent -ResourceId "/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.Discovery/agents/$agent"
        Write-Host "Successfully removed agent: $agent"
    } catch {
        Write-Host "Failed to remove agent: $agent" -ForegroundColor Red
    }
}
