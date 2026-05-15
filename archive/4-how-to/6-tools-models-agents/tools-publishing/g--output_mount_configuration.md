# Promote tools generated results (Output Mount configurations)

This guide describes the mechanics that Microsoft Discovery exposes to promote the results from Action-based tools. This feature simplifies the process of persisting output files generated during tool execution.

## Overview

The usage of output mount configuration in tools let end users address a key customer requirement: the ability to specify hardcoded output mounts that are always collected as part of a tool run, with configurable automatic promotion to data assets. This capability is particularly valuable for tools that generate significant output data, simulation results, processed datasets, or any other files that need to be preserved and made accessible to users and downstream processes.

## Key Features

### Deterministic Data Handling
The above mentioned functionality addresses a critical customer requirement for more determinism in data handling by providing:

- **Predictable Output Collection**: Hardcoded output mounts ensure specific paths are always collected
- **Consistent Asset Creation**: Automatic data assets creation provides reliable data cataloging
- **Configurable Promotion**: Customers control when outputs become discoverable assets
- **Reliable Storage**: Direct uploads to data containers eliminate intermediate storage steps

### Robust Validation
- **Filename Standards**: Enforces strict naming conventions to ensure compatibility and security
- **Size Limitations**: Implements reasonable constraints to prevent storage abuse
- **Format Validation**: Validates file formats and content types as appropriate

### Centralized Storage
- **Data Container Storage**: All saved files are stored in the dedicated data container storage account
- **Automatic Asset Linking**: Data assets automatically point to the stored content location
- **Easy Retrieval**: Files are accessible through standard Discovery interfaces and APIs
- **Persistent Storage**: Files remain available for future reference and downstream processing

## How does tools output promotion works?

### 1. Hardcoded Output Mounts Integration

The platform supports hardcoded output mounts that customers can specify in their tool definitions. These mounts are always collected as part of a tool run, regardless of the specific execution parameters. This provides deterministic behavior that customers can rely on:

```yaml
# Example tool definition with output mount configuration
actions:
  - name: data_analysis
    description: "Performs comprehensive data analysis and generates reports"
    output_mount_configurations:
      - mount_path: "/app/outputs/"
        auto_promote: true
        output_name: "AnalysisResults"
        output_description: "Data analysis reports and visualizations"
```

> **Note**: The `output_name` and `output_description` parameters serve dual purposes: they provide metadata for agent interactions and, when `auto_promote` is set to `true`, they become the name and description of the automatically created data assets.

### 2. File Processing Pipeline

The default functionality follows a systematic pipeline:

1. **Detection**: Monitors output directories for newly created files
2. **Validation**: Applies filename and content validation rules
3. **Direct Upload**: Uploads content directly to Azure Blob Storage data containers
4. **Data Asset Creation**: Automatically creates data assets that point to the stored content
5. **Auto-Promotion**: Conditionally promotes outputs based on configuration settings
6. **Notification**: Provides feedback on successful storage or any errors

### 3. Output Mount Configuration

The `output_mount_configurations` section in tool definitions controls how the functionality handles outputs:

```yaml
output_mount_configurations:
  - mount_path: "/app/results/"           # Container path for output files
    auto_promote: true                    # Enable automatic file promotion
    output_name: "SimulationData"         # User-friendly name for the output (suffix shall be appended to it)
    output_description: "Molecular dynamics simulation results in CSV format" # Description of data asset as seen by the agents
```

## Configuration Parameters

### Hardcoded Output Mount Configuration

Hardcoded output mounts allow customers to specify predetermined output paths that are always collected during tool execution, providing deterministic data handling behavior.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `mount_path` | string | Yes | Absolute path within the container where output files are generated (hardcoded and always collected) |
| `auto_promote` | boolean | No | If `true`, files are automatically promoted as data assets (default: `false`) |
| `output_name` | string | No | Human-readable name for the output collection |
| `output_description` | string | No | Detailed description of the output contents and format |

## Implementation Guide

### 1. Tool Definition Example

Configure your tool definition to use the functionality by adding output mount configurations:

```yaml
name: molecular-simulator
description: "Advanced molecular simulation tool with deterministic output handling"
version: 1.0.0
category: Physics-Based Simulations
license: MIT

actions:
  - name: run_simulation
    description: "Executes molecular dynamics simulation with hardcoded output collection"
    input_schema:
      type: object
      properties:
        input_file:
          type: string
          description: "Path to input molecular structure file"
        simulation_parameters:
          type: string
          description: "JSON string containing simulation parameters"
      required:
        - input_file
        - simulation_parameters
    
    command: "python simulate.py --input {{ input_file }} --params '{{ simulation_parameters }}'"
    
    # Hardcoded output mounts - these paths are ALWAYS collected regardless of execution parameters
    output_mount_configurations:
      - mount_path: "/app/simulation_results/"  # Always collected - deterministic behavior
        auto_promote: true                      # Automatically create data assets
        output_name: "SimulationResults"
        output_description: "Complete molecular dynamics simulation outputs including trajectories, energies, and analysis files"
      
      - mount_path: "/app/logs/"               # Always collected for debugging
        auto_promote: false                    # Store but don't auto-promote
        output_name: "SimulationLogs"
        output_description: "Detailed simulation execution logs and debug information"
      
      - mount_path: "/app/intermediate/"       # Always collected for workflow chaining
        auto_promote: false                    # Internal use only
        output_name: "IntermediateData"
        output_description: "Intermediate calculation data for downstream processing"
    
    environment_variables:
      - name: RESULTS_PATH
        value: "/app/simulation_results/"      # Hardcoded path reference
      - name: LOG_PATH
        value: "/app/logs/"                    # Hardcoded path reference
```

### 2. Container Script Implementation

Design your container scripts to generate files in the specified output directories:

```python
#!/usr/bin/env python3
import os
import json
import csv
from pathlib import Path

def run_simulation(input_file, output_directory):
    """Execute simulation and save results to output directory"""
    
    # Ensure output directory exists
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Run simulation logic here
    simulation_data = perform_simulation(input_file)
    
    # Save results with valid filenames
    results_file = output_path / "simulation_results.json"
    with open(results_file, 'w') as f:
        json.dump(simulation_data, f, indent=2)
    
    # Save summary CSV
    summary_file = output_path / "energy_summary.csv"
    with open(summary_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Step', 'Energy', 'Temperature'])
        for step, energy, temp in simulation_data['trajectory']:
            writer.writerow([step, energy, temp])
    
    # Generate analysis plots
    plot_file = output_path / "energy_plot.png"
    create_energy_plot(simulation_data, plot_file)
    
    print(f"Simulation completed. Results saved to {output_directory}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    
    run_simulation(args.input, args.output)
```

### 3. Multiple Output Types

Handle different types of outputs with separate mount configurations:

```yaml
output_mount_configurations:
  # Primary results - automatically promoted
  - mount_path: "/app/primary_results/"
    auto_promote: true
    output_name: "PrimaryResults"
    output_description: "Main analysis results including processed data and summary statistics"
  
  # Intermediate files - not automatically promoted
  - mount_path: "/app/intermediate/"
    auto_promote: false
    output_name: "IntermediateFiles"
    output_description: "Intermediate processing files and temporary data"
  
  # Visualization outputs
  - mount_path: "/app/visualizations/"
    auto_promote: true
    output_name: "Visualizations"
    output_description: "Generated plots, charts, and graphical representations"
```

For additional guidance on tool definition, refer to the other documents in this series, particularly the [Tool Definition Guide](e--create-tool-definition.md).
