# PowerShell script to create S2ROIP workflows by calling New-DiscoveryWorkflow

# List of S2R workflow file paths
$workflowFiles = @(
    './S2R.yaml'
    # Add more S2R workflow file paths here
)

# Resource group name
$resourceGroupName = "<add your RG name here>"

# Iterate through the list and create each workflow
foreach ($workflowFile in $workflowFiles) {
    try {
        Write-Host "Creating workflow from file: $workflowFile in resource group: $resourceGroupName"
        New-DiscoveryWorkflow -ResourceGroupName $resourceGroupName -YamlFilePath $workflowFile
    } catch {
        Write-Host "Failed to create workflow from file: $workflowFile" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
    }
}
