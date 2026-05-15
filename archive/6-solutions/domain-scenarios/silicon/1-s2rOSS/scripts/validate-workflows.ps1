# PowerShell script to validate S2R workflow files by calling Test-DiscoveryWorkflowValid 
# This script is designed to be executed from the parent directory (one level up from scripts)

# Call Test-DiscoveryWorkflowValid for each S2R workflow file (matching create-workflows.ps1)
Test-DiscoveryWorkflowValid -Path 'S2R.yaml' -AgentPath 'agent-definitions' -AgentFileType 'yaml'
