# Tool Invocations and Workload Types on Supercomputers

> **Note:** This guide explains how to invoke data-plane APIs directly, rather than using the Copilot experience. If you prefer to use Copilot for tool execution, you can skip this section.

Microsoft Discovery Supercomputers support a wide variety of scientific computing workloads through flexible tool invocation patterns and optimized node pool configurations. This guide covers the different types of workloads, recommended VM SKUs, and configuration patterns.

## Overview

Microsoft Discovery supports two primary workload categories, each optimized for different computational patterns and resource requirements:

- **Container Workloads (Batch Jobs)**: Containerized applications running on a scheduler
- **Tightly Coupled Workloads**: MPI and distributed HPC jobs requiring inter-node communication

Each workload type has specific VM SKU recommendations and configuration patterns to optimize performance, cost, and resource utilization.

## Workload Types and VM SKU Recommendations

### Container Workloads (Batch Jobs)

Container workloads are containerized applications that run as batch jobs on a scheduler. These workloads are ideal for scientific tools, data processing pipelines, and computational tasks that can be packaged in containers.

**Recommended VM SKUs:**

- `Standard_D4s_v5`, `Standard_D8s_v5`, `Standard_D16s_v5` (D-series) - General purpose
- `Standard_NC96ads_A100_v4`, `Standard_NC24ads_A100_v4` (NC-series) - GPU workloads
- `Standard_F16s_v2`, `Standard_F32s_v2` (F-series) - CPU-intensive
- `Standard_E64s_v5`, `Standard_M128s` (E/M-series) - Memory-intensive
- `Standard_L16s_v2`, `Standard_L32s_v2` (L-series) - Storage-intensive

**Characteristics:**

- Single containerized applications
- Run independently on individual nodes
- Suitable for most scientific computing tasks
- Can be optimized for CPU, GPU, memory, or storage depending on VM SKU choice

**Use Cases:**

- Scientific simulation tools
- Bioinformatics pipelines
- Molecular dynamics simulations

**Example Node Pool Configuration:**

```json
{
  "name": "container-workload-pool",
  "vmSize": "Standard_D8s_v5",
  "minNodes": 0,
  "maxNodes": 20,
  "subnetId": "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/research-vnet/workload-subnet"
}
```

**Tool Definition Example:**

```yaml
name: scientific-analysis-tool
description: General scientific analysis tool for container workloads
infra:
  - name: analysis-worker
    infra_type: container
    image:
      acr: myregistry.azurecr.io/scientific-tool:latest
    compute:
      min_resources:
        cpu: 4
        ram: 8Gi
        storage: 50Gi
        gpu: 0
      max_resources:
        cpu: 8
        ram: 16Gi
        storage: 100Gi
        gpu: 0
      recommended_sku:
        - Standard_D8s_v5
        - Standard_D16s_v5
actions:
  - name: analyze_data
    description: Perform scientific data analysis
    infra_node: analysis-worker
    input_schema:
      type: object
      properties:
        analysis_type:
          type: string
          description: "Type of analysis to perform"
        input_directory:
          type: string
          description: "Directory containing input data"
        output_directory:
          type: string
          description: "Directory for output results"
      required:
        - analysis_type
        - input_directory
        - output_directory
```

**Data Plane API Example:**

```json
{
  "toolId": "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Discovery/tools/scientific-analysis-tool",
  "command": "python /app/analyze.py --type molecular --input /mnt/input --output /mnt/output",
  "storageId": "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Discovery/storages/research-storage",
  "inputData": [
    {
      "uri": "discovery://dataassets/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Discovery/datacontainers/research-data/dataAssets/input-dataset",
      "mountPath": "/mnt/input"
    }
  ],
  "outputData": [
    {
      "uri": "discovery://dataassets/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Discovery/datacontainers/research-data/dataAssets/analysis-results",
      "mountPath": "/mnt/output"
    }
  ],
  "nodePoolIds": [
    "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Discovery/supercomputers/research-cluster/nodepools/container-workload-pool"
  ]
}
```

**How These Components Are Connected:**

1. **Node Pool → Tool Definition**: The tool definition's `recommended_sku` field is compatible with the node pool's `vmSize`.

2. **Tool Definition → Data Plane API**: The `toolId` references the deployed tool.

3. **Node Pool → Data Plane API**: The `nodePoolIds` array specifies which node pool will execute the workload, ensuring the job runs on appropriate VM SKUs.

**Data Flow and Storage Integration:**

4. **Input Data Mapping**: The tool definition's `input_directory` parameter maps to the `inputData` array in the Data Plane API call. The supercomputer mounts DataAssets to specified mount paths, making data accessible to the containerized tool.

5. **Output Data Mapping**: The tool definition's `output_directory` parameter maps to the `outputData` array. The supercomputer monitors the output directory and automatically copies results to persistent DataAsset storage.

6. **DataContainers** act as logical storage units that group related scientific data, while **DataAssets** are individual datasets within containers. The supercomputer handles the translation between container filesystem paths and persistent storage URIs, allowing tools to work with simple directory paths while benefiting from enterprise-grade data management.

### Tightly Coupled Workloads

Tightly coupled workloads require high-bandwidth, low-latency communication between nodes. These are typically MPI (Message Passing Interface) applications and distributed HPC simulations.

**Recommended VM SKUs:**

- `Standard_HB120rs_v3` (HB-series) - HPC CPU workloads with InfiniBand
- `Standard_HC44rs` (HC-series) - High-performance computing

**Characteristics:**

- Require inter-node communication (MPI)
- Need high-bandwidth, low-latency networking
- Scale across multiple nodes simultaneously
- Typically use specialized HPC VM SKUs with InfiniBand

**Use Cases:**

- Large-scale molecular dynamics simulations
- Distributed numerical computations
- Quantum chemistry calculations

**Example Node Pool Configuration:**

```json
{
  "name": "tightly-coupled-pool",
  "vmSize": "Standard_HB120rs_v3",
  "minNodes": 2,
  "maxNodes": 10,
  "subnetId": "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/research-vnet/workload-subnet"
}
```

**Tool Definition Example:**

```yaml
name: mpi-mbrot
description: MPI-based Mandelbrot simulation tool
version: "1.0"
infra:
  - name: worker
    image:
      acr: internaltestingeus2.azurecr.io/mpi-mandelbrot:latest
    internal_ports:
      - destination: 22
        protocol: tcp
    mpi:
      follower_command: "/opt/Microsoft.Discovery/mpid"
    compute:
      pool_size: 3
      min_resources:
        cpu: "500m"
        ram: "1Gi"
        gpu: 0
      max_resources:
        cpu: "4"
        ram: "16Gi"
        gpu: 0
```

**Data Plane API Example:**

```json
{  "toolId": "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Discovery/tools/mpi-mbrot",
  "command": "mpirun --allow-run-as-root --hostfile /var/run/Microsoft.Discovery/mpi-hosts -n 6 /root/mandelbrot --input /mnt/input --output /mnt/output",
  "storageId": "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Discovery/storages/hpc-storage",
  "inputData": [
    {
      "uri": "discovery://dataassets/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Discovery/datacontainers/hpc-data/dataAssets/simulation-config",
      "mountPath": "/mnt/input"
    }
  ],
  "outputData": [
    {
      "uri": "discovery://dataassets/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Discovery/datacontainers/hpc-data/dataAssets/simulation-results",
      "mountPath": "/mnt/output"
    }
  ],
  "nodePoolIds": [
    "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Discovery/supercomputers/research-cluster/nodepools/tightly-coupled-pool"
  ]
}
```

**How These Components Are Connected:**

1. **Node Pool → Tool Definition**: The tool definition specifies `pool_size: 3` to request 3 nodes for the MPI job. The platform allocates nodes from pools with appropriate networking for MPI communication.

2. **Tool Definition → Data Plane API**: The `toolId` references the deployed MPI tool.

3. **Node Pool → Data Plane API**: The `nodePoolIds` array specifies HPC node pools with specialized networking for inter-node communication. The MPI framework handles process coordination across nodes.

**Data Flow and Storage Integration:**

4. **Input Data Mapping**: The tool receives simulation configuration files and initial conditions through mounted DataAssets. The MPI framework automatically handles distribution of data across nodes.

5. **Output Data Mapping**: The tool writes distributed simulation results to the output mount path. The platform aggregates outputs from all MPI processes and stores them as unified DataAssets.

6. **DataContainers** like "hpc-data" organize large-scale simulations with DataAssets for simulation configurations and multi-node results. The MPI framework (`/opt/Microsoft.Discovery/mpid`) provides inter-process communication while the platform handles data mounting and result collection for distributed HPC workloads.

## Additional Resources

- [molToolkit Example](../../6-solutions/tools-and-models/molToolkit/) - Complete working tool implementation
- [Azure VM Sizes Documentation](https://learn.microsoft.com/azure/virtual-machines/sizes)
- [Azure HPC Documentation](https://learn.microsoft.com/azure/architecture/topics/high-performance-computing)
