# PowerShell script to delete S2ROIP workflows by calling Remove-DiscoveryWorkflow

# Define resource group and subscription ID
$resourceGroup = '<add your RG name here>'
$subscriptionId = '<add your subscription ID here>'

# List of S2ROIP workflow names to delete (matching create-workflows.ps1)
$workflows = @(
    'S2R'
)

foreach ($workflow in $workflows) {
    try {
        Remove-DiscoveryWorkflow -ResourceId "/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.Discovery/workflows/$workflow"
        Write-Host "Successfully removed workflow: $workflow"
    } catch {
        Write-Host "Failed to remove workflow: $workflow" -ForegroundColor Red
    }
}