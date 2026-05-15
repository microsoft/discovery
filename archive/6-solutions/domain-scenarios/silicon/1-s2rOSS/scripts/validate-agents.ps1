# PowerShell script to validate S2R agent files by calling Test-DiscoveryAgentValid 
# This script is designed to be executed from the parent directory (one level up from scripts)

# Call Test-DiscoveryAgentValid for each S2R agent file (matching create-agents.ps1)
Test-DiscoveryAgentValid -Path 'agent-definitions/Planner.yaml'
Test-DiscoveryAgentValid -Path 'agent-definitions/RouterOSS.yaml'
Test-DiscoveryAgentValid -Path 'agent-definitions/VerilogCreateNoTool.yaml'
Test-DiscoveryAgentValid -Path 'agent-definitions/ChkSyntaxDesign.yaml'
Test-DiscoveryAgentValid -Path 'agent-definitions/FixSyntaxDesign.yaml'
Test-DiscoveryAgentValid -Path 'agent-definitions/GenSpecs.yaml'
Test-DiscoveryAgentValid -Path 'agent-definitions/GenScenarios.yaml'
Test-DiscoveryAgentValid -Path 'agent-definitions/GenBehavior.yaml'
Test-DiscoveryAgentValid -Path 'agent-definitions/GenAssertions.yaml'
Test-DiscoveryAgentValid -Path 'agent-definitions/GenStimulus.yaml'
Test-DiscoveryAgentValid -Path 'agent-definitions/GenGoldenDUT.yaml'
Test-DiscoveryAgentValid -Path 'agent-definitions/GenFinalTB.yaml'
Test-DiscoveryAgentValid -Path 'agent-definitions/SiliconSummarizer.yaml'
Test-DiscoveryAgentValid -Path 'agent-definitions/SNPS-PPA-TSMC-N3P.yaml'
