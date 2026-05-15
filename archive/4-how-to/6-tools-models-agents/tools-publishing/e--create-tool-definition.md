# Tool Definition

After successfully creating and containerizing your tool with Docker, the next crucial step is to define a Tool Definition.

## Introduction

A Tool Definition is a structured YAML document that describes how Microsoft Discovery can deploy, execute, and interact with your containerized tool. It serves as the integration point, outlining the tool’s metadata, configuration options, input and output formats, and resource requirements. By clearly specifying these details, the Tool Definition ensures that your tool can be reliably orchestrated within investigations and workflows.

In essence, the Tool Definition acts as a contract between your tool and the Microsoft Discovery platform. It communicates what your tool does, how it should be invoked, and what is needed for successful operation—enabling seamless integration and consistent behavior across different scenarios.

## Tool Definition Guide

A Tool Definition YAML file consists of several key sections that together define how your tool integrates with the Microsoft Discovery platform.

### 1. Definition Templates

Tools can be defined using three approaches:
- **Action-based tools**: Provide predefined operations with structured inputs (shown in example 1)
- **Code environment tools**: Allow agents to execute custom code within the tool's container (shown in example 2)
- **Hybrid tools**: Combine both actions and code environments in a single tool definition

> **Note**: A tool can include both `actions` and `code_environments` sections, giving agents the flexibility to use predefined operations or write custom code as needed.

#### 1. Action-based Tool Definition

```yaml
name: retroChimera-with-syntheseus-client # Name of the tool, used to identify the tool in the system
description: Tool client that makes RetroChimera model calls to perform chemical retrosynthesis. # Description of the tool, providing context and purpose
version: 1.0.0 # Version of the tool definition, useful for versioning and updates
category: Machine learning model # Category of the tool, useful for organizing tools in a catalog
license: MIT # License for the tool definition
infra: # Infrastructure definition for the tool
  - name: worker # Name of the infrastructure node
    infra_type: container # Type of infrastructure node, here it is a container
    image: # Container image for Tool
      acr: test.azurecr.io/retrochimera-client-image:latest # Container image for GROMACS with MPI support; Absent in case of Marketplace images
    compute: # Compute resources for the container
      min_resources: # Minimum resources for the container, equates to requests in Kubernetes
        cpu: 4 # Could be 4 cores or 4000m
        ram: 16Gi # GiB is the unit for memory
        storage: 64Gi # GiB is the unit for storage
        gpu: 0 # Always integer, 0 means no GPU
      max_resources: # Maximum resources for the container, equates to limits in Kubernetes; Optional
        cpu: 5700m # 5700m is equivalent to 5.7 cores
        ram: 32Gi # GiB is the unit for memory
        storage: 128Gi  # GiB is the unit for storage
        gpu: 0  # Always integer, 0 means no GPU
      infiniband: false # Indicates if Infiniband is required; Optional, default to false
      recommended_sku: # Recommended VM SKUs for this infra node
        - Standard_D4_v4
        - Standard_D8_v4 
      pool_type: static # support for elastic post M2
      pool_size: 1 # Number of containers in the pool
actions: # Actions available for the tool
  - name: chimera_syntheseus # Name of the action, used to identify the action in the system
    description: This action executes the RetroChimera model to predict the reactants give the smiles string. # Description of the action, providing context and purpose
    infra_node: worker # Infrastructure node where this action is available
    input_schema: # Input schema for the action, defining the expected input parameters
      type: object # Type of the input schema, here it is an object
      properties: # Properties of the input schema, defining the expected input parameters; List all the parameters that the action accepts, with their types and descriptions. Provide default values in description if applicable
        workflow: 
          type: string 
          description: "Type of workflow to be executed. Use single_step for straightforward, individual reactions where a single transformation is needed and multi_step for complex synthesis requiring multiple sequential reactions to achieve the final product." 
        inputs: 
          type: array 
          items: 
            type: string 
          description: "List of SMILES strings." 
        num_results:
          type: number 
          description: "Number of reactions. Applicable just for the single_step workflow. Should be set to 5." # Description of the num_results parameter
        time_limit_s: 
          type: number 
          description: "Seconds to pre-empt this call. This is applicable just for the multi_step workflow. Should be set by default to 45."  # Description of the time_limit_s parameter
        output_directory: 
            type: string 
            description: "Directory to write output of model in JSON format." 
      required: # Required parameters for the action, these parameters must be provided when invoking the action
        - workflow 
        - inputs
        - output_directory
    command: "python3 chimera_client.py --workflow {{ workflow }} --inputs {{ inputs }} {{#if num_results}} --num_results {{ num_results }}{{/if}} {{#if time_limit_s}} --time_limit_s {{ time_limit_s }}{{/if}}" # Command to execute the action, using the provided input parameters; To be leveraged by Agent to invoke the action
    environment_variables: # Environment variables for the action, these variables shall be exposed in the container environment
      - name: OUTPUT_DIRECTORY_PATH
        value: "{{ output_directory }}"
```

#### 2. Code-environment Based Tool Definition (molToolkit)

```yaml
name: moltoolkit # Name of the tool, used to identify the tool in the system
description: MolToolkit is a comprehensive toolkit for molecular analysis and data processing, designed to handle tasks such as molecular conformer generation, descriptor calculations, and data logging within a Dockerized environment. # Description of the tool, providing context and purpose
version: 1.0.0 # Version of the tool definition, useful for versioning and updates
category: "Scientific Computing" # Category of the tool, useful for organizing tools in a catalog
license: MIT # License for the tool definition
infra: # Infrastructure definition for the tool
  - name: worker # Name of the infrastructure node
    infra_type: container # Type of infrastructure node, here it is a container
    image: # Container image for Tool
      acr: "{name}.azurecr.io/moltoolkit-image:latest" # Container image for MolToolkit
    compute: # Compute resources for the container
      min_resources: # Minimum resources for the container, equates to requests in Kubernetes
        cpu: 1 # Could be 4 cores or 4000m
        ram: 8Gi # GiB is the unit for memory
        storage: 8Gi # GiB is the unit for storage
        gpu: 0 # Always integer, 0 means no GPU
      max_resources: # Maximum resources for the container, equates to limits in Kubernetes; Optional
        cpu: 2 # 2 cores
        ram: 16Gi # GiB is the unit for memory
        storage: 32Gi  # GiB is the unit for storage
        gpu: 0  # Always integer, 0 means no GPU
      infiniband: false # Indicates if Infiniband is required; Optional, default to false
      recommended_sku: # Recommended VM SKUs for this infra node
        - Standard_D4s_v3
      pool_type: static # support for elastic post M2
      pool_size: 1 # Number of containers in the pool
code_environments: # Code environments available for the tool
  - language: python # Programming language for the code environment
    command: "python \"/{{scriptName}}\"" # Command to run Python scripts in the container
    description: "Python code environment on MolToolkit container image." # Description of the code environment
    infra_node: worker # Infrastructure node where this code environment is available
```

### 2. Sample Tool Definition

In this section, we'll explore the molToolkit tool definition as a comprehensive example to explain each section. This tool uses a code environment approach, allowing agents to execute custom Python code with pre-installed chemistry libraries.

#### 1. Metadata and Basic Information

The top section of the Tool Definition contains essential metadata about your tool:

```yaml
name: moltoolkit
description: A comprehensive molecular analysis toolkit for cheminformatics and molecular modeling.
version: 1.0.0
category: Physics-Based Simulations
license: MIT
```

- **name**: A unique identifier for your tool. Add version as well to name in case you want to maintain multiple versions of a specific tool
- **description**: A detailed explanation of your tool's capabilities and purpose
- **version**: The semantic version of your tool
- **category**: The scientific or technical domain your tool belongs to
- **license**: The license under which your tool is distributed

#### 2. Infrastructure Requirements

This section defines the computational resources your tool needs:

```yaml
infra: 
  - name: worker 
    infra_type: container 
    image:
      acr: mycontainerregistry.azurecr.io/moltoolkit
    compute: 
      min_resources: 
        cpu: 4 
        ram: 16Gi 
        storage: 64Gi 
        gpu: 0 
      max_resources: 
        cpu: 8 
        ram: 32Gi 
        storage: 128Gi  
        gpu: 0  
      recommended_sku: 
        - Standard_D4_v4
        - Standard_D8_v4 
      pool_type: static 
      pool_size: 1 
```

- **name**: Identifier for this infrastructure node
- **infra_type**: The infrastructure type (usually "container" for containerized tools)
- **image**: The container image URL or reference
- **compute**: Resource requirements and recommendations:
  - **min_resources**: Minimum computational requirements. This must be less than the resource available on nodes running this tool, accounting for 1 vcpu and 2.5GiB memory reserved for platform operations.
  - **max_resources**: Maximum computational requirements. If the memory limit is exceeded, the tool may be forcefully stopped.
  - **recommended_sku**: Suggested Azure VM SKUs
  - **pool_type**: How to manage the compute resources. The only supported pool_type is "static" during private preview
  - **pool_size**: Number of instances of this container
 
**NB**: Dynamic GPU sharing is not currently supported. When executing a tool definition with GPUs on a Discovery Supercomputer, the *minimum* GPU requirement will be used.

#### 3. Actions

Actions define the specific operations your tool can perform. See the [molecularGroups tool](../../../6-solutions/tools-and-models/molecularGroups/) for a reference implementation of an action-based tool.

```yaml
actions:
  - name: identify_functional_groups
    description: Identifies common functional groups in molecular structures (carbonyls, amines, alcohols, etc.)...
    infra_node: worker
    input_schema:
      type: object
      properties:
        input_directory:
          type: string
          description: "Directory containing input files (CSV, SMILES, TXT, etc.)."
        output_directory:
          type: string
          description: "Directory where output files and analysis results will be saved."
        column_name:
          type: string
          description: "For CSV/TSV files, the name of the column containing SMILES strings"
        # Additional parameters...
      required:
        - input_directory
        - output_directory
    command: "python3 /app/entrypoint.py --action identify_functional_groups --input {{input_directory}} --output {{output_directory}} {{#if column_name}}--column-name {{column_name}}{{/if}}"
    environment_variables:
      - name: TOOL_INPUT_DIR
        value: "{{ input_directory }}"
      - name: TOOL_OUTPUT_DIR
        value: "{{ output_directory }}"
```

For each action, define:

- **name**: Unique identifier for the action
- **description**: Detailed explanation of what the action does
- **infra_node**: Which infrastructure node should execute this action
- **input_schema**: JSON Schema defining the input parameters:
  - **properties**: All possible parameters, each with type and description
  - **required**: List of mandatory parameters
- **command**: Template for constructing the command to execute the action
  - Uses Handlebars syntax (`{{parameter}}`) to insert parameter values
  - Supports conditional sections with `{{#if parameter}}...{{/if}}`
- **environment_variables**: Environment variables to set when executing the action

#### 4. Code Environments

Code environments allow agents to execute custom code with your tool. See the [molToolkit tool](../../../6-solutions/tools-and-models/molToolkit/) for a reference implementation of a code-environment-based tool.

```yaml
code_environments:
  - language: python
    command: "python \"/{{scriptName}}\""
    description: "Python code environment on MolToolkit container image."
    infra_node: worker
```

- **language**: The programming language supported
- **command**: Template for executing custom scripts
- **description**: Details about the code environment capabilities
- **infra_node**: Which infrastructure node provides this environment

### 3. Best Practices

When creating your Tool Definition:

1. **Be descriptive**: Provide detailed descriptions for your tool, actions, and parameters
2. **Set appropriate resource requirements**: Specify realistic min/max resources based on tool usage patterns
3. **Design flexible actions**: Support optional parameters and batch processing where applicable
4. **Validate input parameters**: Define required parameters and use appropriate JSON Schema types
5. **Document environment variables**: Clearly document any environment variables your tool expects

## Creating Your Tool Definition

Follow these steps to create a Tool Definition for your containerized tool:

1. **Start with a template**: Use the [molToolkit](../../../6-solutions/tools-and-models/molToolkit/) (code environment) or [molecularGroups](../../../6-solutions/tools-and-models/molecularGroups/) (action-based) tool definition files as a reference and starting point.

2. **Define metadata**:
   - Choose a clear, descriptive name for your tool
   - Write a comprehensive description that explains your tool's capabilities
   - Set the appropriate version, category, and license

3. **Specify infrastructure requirements**:
   - Define the container image location
   - Determine minimum and maximum resource requirements based on benchmarking
   - Recommend appropriate SKUs for optimal performance

4. **Define actions**: (if applicable):
   - Identify distinct operations your tool can perform
   - For each action:
     - Create a descriptive name and detailed explanation
     - Define input parameters using JSON Schema
     - Create a command template that maps parameters to the container entrypoint
     - Set environment variables needed by the action

5. **Add code environments** (if applicable):
   - Specify supported programming languages
   - Define how custom scripts should be executed
   - Document available libraries and capabilities

6. **Validate your definition**:
   - Ensure all required fields are present
   - Verify that command templates are correctly formatted
   - Check that parameter references use the correct syntax

7. **Test with sample inputs**:
   - Manually expand command templates with sample values
   - Verify that the resulting commands match what your container expects

## Next Steps

After creating your Tool Definition:

1. **Validate the Tool Definition**: Use a YAML validator to check for syntax errors.

2. **Test locally**: Before publishing, test commands in your Tool Definition with your container image locally to ensure they work together correctly.

3. **Create documentation**: Develop comprehensive documentation for your tool, including:
   - Usage examples
   - Parameter explanations
   - Common workflows
   - Troubleshooting tips

4. **Add an Agent**: Next step is to add appropriate ARM templates for tools resource and ensure you have agent that can use this tool resource.

5. **Create project & investigation and Test Agents/tool in investigations**: Run test investigations using your published agent & tool to validate its integration with the platform.

6. **Gather feedback**: Once users begin working with your tool, collect feedback to inform future improvements and updates.

For detailed guidance on publishing your tool to Microsoft Discovery, refer to the next document in this series.
