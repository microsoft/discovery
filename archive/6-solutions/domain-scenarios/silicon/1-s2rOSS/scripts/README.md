# Silicon S2R Scripts Directory

This directory contains PowerShell scripts for managing and validating the Silicon Spec-to-RTL (S2R) workflow components.

## Files Description

| Script | Purpose |
|--------|---------|
| `create-agents.ps1` | Creates and deploys all S2R agent definitions to the Discovery platform |
| `create-workflows.ps1` | Creates and deploys the S2R workflow definition to the Discovery platform |
| `validate-agents.ps1` | Validates all S2R agent definition files for syntax and compliance |
| `validate-workflows.ps1` | Validates the S2R workflow definition file and agent references |
| `delete-agents.ps1` | Removes deployed S2R agent definitions from the Discovery platform |
| `delete-workflows.ps1` | Removes deployed S2R workflow definition from the Discovery platform |

## Prerequisites

> **IMPORTANT**: The `discovery-tools.ps1` utility script must be sourced in the PowerShell environment before running any of these scripts. This utility provides the necessary cmdlets for Discovery platform operations.
> 
> Users can inquire with Microsoft for access to the `discovery-tools.ps1` script.

## Usage

1. **Source the Discovery Tools** (required for all operations):
   ```powershell
   . .\path\to\discovery-tools.ps1
   ```

2. **Execute from Parent Directory**: These scripts are designed to be run from the parent directory (one level up from the scripts folder):
   ```powershell
   # Navigate to the S2R sample directory
   cd samples\domain-scenarios\silicon\1-s2rOSS
   
   # Run validation scripts
   .\scripts\validate-agents.ps1
   .\scripts\validate-workflows.ps1
   
   # Deploy components
   .\scripts\create-agents.ps1
   .\scripts\create-workflows.ps1
   ```

3. **Typical Workflow**:
   - Validate agents: `.\scripts\validate-agents.ps1`
   - Validate workflows: `.\scripts\validate-workflows.ps1`
   - Create agents: `.\scripts\create-agents.ps1`
   - Create workflows: `.\scripts\create-workflows.ps1`

## Notes

- All scripts reference agent definitions from the `agent-definitions/` directory
- Workflow scripts reference the `S2R.yaml` file in the parent directory
- **Configuration Required**: Some scripts require updating the Resource Group name and Subscription ID to match your Azure environment before execution
- Ensure proper Azure authentication and Discovery platform access before running deployment scripts