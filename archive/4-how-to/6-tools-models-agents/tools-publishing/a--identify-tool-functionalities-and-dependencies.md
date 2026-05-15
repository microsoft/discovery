# Identify Tool Functionalities and Dependencies

This guide outlines the essential steps for identifying tool functionalities and dependencies before containerizing and publishing tools to the Microsoft Discovery platform. This process ensures that tools are properly configured, efficient, and ready for deployment.

## Overview

Tool onboarding requires careful analysis of functionality requirements, compute needs, and dependencies. This systematic approach helps ensure that tools are properly containerized and can effectively serve end users in the Discovery environment.

## Phase 1: Identify Key Functionalities

The first and foremost step is to understand the tool that needs to be containerized and collect the necessary requirements for such a tool. Given that a tool can have numerous functions, it's important to determine which actions should be enabled. You might choose to expose only a subset or all the actions. Additionally, it's crucial to identify the key compute requirements for the tool during this stage.

### Functionality Analysis

When analyzing your tool, consider the following:

- **Core Capabilities**: Identify the primary functions your tool performs
- **User Workflows**: Understand how end users will interact with your tool
- **Input/Output Requirements**: Define what data formats your tool accepts and produces
- **Action Granularity**: Determine the appropriate level of granularity for exposed actions

### Gather Other Requirements

Record the resource needs including CPU, memory, storage, GPU, and network requirements. Understand the compute requirements range to support the tool, noting both minimum and maximum compute needs.

**Key Requirements to Document:**

- **Workload type**: Standard workload, intrinsicaslly parallel workload or tighly coupled
- **CPU Requirements**: Number of cores, code environment used
- **Memory Needs**: RAM requirements for typical and peak workloads
- **Storage**: Temporary and persistent storage requirements
- **GPU Requirements**: If applicable, specify GPU memory and compute capabilities
- **Network**: infiniband requirements, ports exposed on container
- **Scalability**: Static vs elastic, where you may want to specify the number of container nodes deployed for processing

Identify and document the necessary actions for the tool. These are the actions that the tool must expose. Tool owner will be responsible for determining and including the correct scripts/endpoints in the tool image to enable such actions on container.

## Phase 2: Tool Type Selection

Based on the tool needs, the tool publisher needs to select one of the possible tool types.

### Available Tool Types

The Discovery platform supports several tool types, each optimized for different use cases:

1. **Action-Based Tools**: Tools that expose specific, well-defined actions
2. **Code Environment Tools**: Tools that provide runtime environments for custom code
3. **Hybrid Tools**: Tools that combine both action-based and code environment capabilities

Please visit [tool type determination guide](../../../3-concepts/tools.md#tool-types) here for more detailed information.

## Phase 3: Writing Action Scripts

For action-based tools, and prior to creating container images for the tool, tool publishers need to ensure that the actions determined in Phase-1 can be exposed to end users and these scripts can accept suitable customer inputs. The tool publisher needs to ensure they have scripts written for each action that is exposed explicitly as a part of tool onboarding.

### Script Development Guidelines

**Input Processing:**

- Scripts should accept standardized input formats
- Implement robust input validation and error handling
- Support batch processing for efficiency

**Example Implementation:**
For example, with ADFT, generating spe (single point energy) might be one of the permissible actions. Tool owners need to implement a suitable script that takes user inputs, generates spe, and provides the expected output.

**Batch Processing:**
The scripts embedded into the tool container image should ensure they can help perform the specified actions, ensures that they are able to process the operations on batch inputs, and process them in chunks that the tools or open API endpoints can consume.

### File System Considerations

For inputs and output processing, tool publishers should assume that the files are mounted to file system within the container while writing these scripts. Design your scripts with the following assumptions:

- Input files will be available at predictable mount points
- Output files should be written to designated output directories

An example script implementation can be found in the sample tools repository.

## Phase 4: Identification of Tool Binaries and Dependencies

To ensure portability, consistency, scalability, and efficiency, images should be self-contained. This means that a tool publisher should carefully identify and include the essential components, such as the base OS image, runtime dependencies, SDKs, application code (scripts), and entrypoint script—if required for tool execution.

### Base Image Requirements

This includes determining base image requirements for this tool. The base image requirements may vary based on requirement for MPI, CUDA drivers etc.

**Common Base Image Considerations:**

- **Operating System**: Choose appropriate Linux distribution
- **Runtime Dependencies**: Python, Node.js, Java, or other language runtimes
- **System Libraries**: Mathematical libraries, image processing, etc.
- **Specialized Requirements**: MPI for parallel computing, CUDA for GPU acceleration

### Code Environment Tools

For code environment-based tools, the images should contain the appropriate runtime and dependencies. However, tool publishers should still account for handling large input datasets efficiently while providing appropriate agent instructions.

### Batch Processing Logic

Implement intelligent batch processing within your container:

For instance, if a tool can process a maximum of 1,000 SMILES strings at a time, either the container image should include logic to split the input file into manageable sets of 1,000 molecules, execute the desired actions on each batch, and then continue processing the next set in sequence or you can leverage agents to generate all in code that handles batching too.

If you intend to manage batch processing within the container image, consider adding a dedicated script responsible for handling this logic. Ensure that all tool execution requests are routed through this script to maintain consistency and efficiency.

**Implementation Strategy:**

- Detect input size and automatically determine optimal batch sizes
- Implement progress tracking and resumption capabilities
- Handle memory management efficiently across batches
- Provide meaningful progress feedback to users

### Dependency Management

**Essential Components Checklist:**

- [ ] Base operating system image
- [ ] Runtime environments (Python, R, Java, etc.)
- [ ] System dependencies and libraries
- [ ] Application-specific dependencies
- [ ] Configuration files and settings
- [ ] Entry point scripts
- [ ] Health check mechanisms

## Security Best Practices

- Use minimal base images when possible
- Keep dependencies up to date
- Implement proper access controls
