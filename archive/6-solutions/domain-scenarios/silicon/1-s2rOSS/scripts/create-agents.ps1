# PowerShell script to create S2ROIP agents by calling New-DiscoveryAgent

# Define resource group
$resourceGroup = 'Siphy-Silicon-East2'

# List of S2R agent YAML file names
$agents = @(
    'Planner.yaml',
    'RouterOSS.yaml',
    'VerilogCreateNoTool.yaml',
    'ChkSyntaxDesign.yaml',
    'FixSyntaxDesign.yaml',
    'GenSpecs.yaml',
    'GenScenarios.yaml',
    'GenBehavior.yaml',
    'GenAssertions.yaml',
    'GenStimulus.yaml',
    'GenGoldenDUT.yaml',
    'GenFinalTB.yaml',
    'SiliconSummarizer.yaml',
    'SNPS-PPA-TSMC-N3P.yaml'
)

# Loop through the list and create each agent
foreach ($agent in $agents) {
    New-DiscoveryAgent -YamlFilePath "../siliconAgents/$agent" -ResourceGroupName $resourceGroup
}
