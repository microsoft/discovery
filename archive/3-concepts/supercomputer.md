# Microsoft Discovery Supercomputer

Microsoft Discovery’s high-performance computing backbone comprises a Supercomputer and its Nodepools, which together empower advanced simulations, large-scale data processing. The Supercomputer brings massively parallel compute power into the Discovery platform, allowing researchers and engineers to run complex experiments or design simulations that were once impractical or time-prohibitive. Integrated with Discovery’s AI agents and tools, this HPC infrastructure accelerates innovation. In essence, the Supercomputer and its Nodepools deliver cloud-scale computational might on demand, so scientists can iterate faster from hypothesis to insight.

## Supercomputer & Nodepool Overview

The Microsoft Discovery Supercomputer provides massive parallel computing capabilities, enabling thousands of CPU/GPU cores to tackle scientific problems in tandem. Researchers and engineers interact with the HPC resources through natural language via Discovery Copilot; the platform’s AI agents schedule workloads to the appropriate nodepools automatically, hiding complexity.

### What is the Microsoft Discovery Supercomputer?

The Microsoft Discovery Supercomputer is a virtual high-performance computing cluster dedicated to the Discovery platform. It acts as the compute engine for running intensive R&D workloads – from simulating physical phenomena and chemical reactions to running complex computation workflows– all within a secure, enterprise-controlled environment. The Supercomputer aggregates cloud-based HPC resources (like Azure’s powerful GPU and CPU instances) under one resource, making massive parallelism available for Discovery Agents and Tools. Researchers do not need specialist HPC skills to use it; through the Discovery Copilot interface, they can simply describe their experiment or analysis in natural language, and the platform will harness the Supercomputer’s power to execute it.

Key capabilities of the Supercomputer in Microsoft Discovery include:

**Massive Parallel Compute:** It can run many computations concurrently, drastically shortening time to results for large-scale experiments or engineering analyses.

**Enterprise-Grade Security & Compliance:** As part of the enterprise environment, the Supercomputer ensures that proprietary data and models remain in a controlled, isolated compute environment. All HPC jobs run within the organization’s Azure boundary, inheriting compliance and security policies. All the data, including intermediate computational data remains in customer subscription.

**Scalability:** The Supercomputer can scale its capacity depending on the workload. It is not a fixed piece of hardware, but a cloud-managed cluster that can grow by adding more Nodepools/nodes or shrink when demand is low, optimizing resource usage.

In summary, the Microsoft Discovery Supercomputer is the high-octane engine of the platform, bringing Azure’s supercomputing capabilities to scientists’ and engineers fingertips without requiring them to manage HPC infrastructure.

### What are Nodepools in Microsoft Discovery?

Nodepools are the fundamental units of compute within the Supercomputer. A Nodepool represents a group of compute nodes in the cluster with a common configuration. If the Supercomputer is analogous to an entire research lab’s computing center, each Nodepool is like a dedicated room full of identical servers, can be  assigned to specific types of tasks or projects. Nodepools allow fine-grained control of the Supercomputer’s resources by categorizing and scaling them according to workload needs.

Each Nodepool is defined by several key attributes:

**Hardware Profile (VM Size):** The type of Azure VM that all nodes in the pool use. For instance, a Nodepool might consist of GPU-accelerated VMs (such as NC-series VMs with NVIDIA A100 GPUs) for heavy AI computations, or CPU-only VMs for data preprocessing tasks. Microsoft Discovery supports a range of Azure HPC VM SKUs for nodepools (e.g., Standard\_NC series for GPU, ND series for GPU with more memory, etc.) . This means you can tailor Nodepools to the specific computational intensity of your workload. For example, a “GPU Nodepool” could use Standard_NC48ads_A100_v4 VMs (each with multiple A100 GPUs) for simulation, while a “CPU Nodepool” might use general-purpose VMs for lighter tasks.

**Number of Nodes (Capacity):** How many VM instances the Nodepool contains. This can typically be configured as a scalable range, with a minimum and maximum node count. Discovery’s Nodepools support auto-scaling; you might set a minNodeCount (which can even be 0 for purely on-demand pools) and a maxNodeCount to allow elasticity. For instance, a nodepool could scale from 0 up to 10 nodes depending on the current workload. When no jobs are running, it can scale down to zero to save cost, and when a big job arrives, it will scale out up to 10 nodes as needed.

**Networking and Location:** All nodes in a pool are attached to a specified virtual network subnet (more on this in the artifacts section) so they can communicate with other platform services (like storage) and with the Supercomputer’s orchestration system. Nodepools exist within the same Azure region and network as the Supercomputer, ensuring low-latency interconnect for MPI tasks or data sharing between nodes if needed.

**Purpose / Workload Assignment:** In practice, each Nodepool can be used to separate different types of workloads. For example, one nodepool might be designated for running simulation tools (with high-end GPUs), another for data cleaning and transformation tasks (with high-memory CPU nodes), and another for visualization or interactive analysis (perhaps smaller, faster-launch VMs).

By splitting the Supercomputer into multiple Nodepools, Microsoft Discovery ensures flexibility and efficiency. You get the benefit of a multi-purpose supercomputer that can concurrently handle diverse workloads – all optimized, without one job starving others for resources. Nodepools, in essence, are how the Discovery Supercomputer adapts to different kinds of science: whether it's crunching numbers for a physics simulation or rendering a complex 3D visualization, or running an intensive circuit simulation, there’s a nodepool ready for the job.

## Nodepool Configurations and Types

Not all scientific workloads are the same, so Nodepools in Microsoft Discovery are designed to be configurable to meet various needs. Generally, we classify nodepools along two axes: hardware type and scaling behavior. Understanding these types will help in setting up the right nodepools for your research environment.

**Hardware-Oriented Nodepool Types:** Depending on the nature of computation, you may configure nodepools with different hardware profiles:

- **GPU-Accelerated Nodepools:** These pools use VMs equipped with GPUs (Graphics Processing Units), ideal for massively parallel tasks like deep learning model training, molecular dynamics simulations, or any algorithms benefiting from GPU acceleration. For instance, a GPU nodepool might use Azure’s NC-series VMs with NVIDIA A100 GPUs for maximum throughput on matrix computations. Such nodepools excel at tasks in computational chemistry, genomics (e.g., DNA sequence analysis), image processing, and so on.

- **CPU-Optimized Nodepools:** These pools consist of high-CPU VMs (no GPUs). They are well-suited for workloads that scale with CPU cores or require large memory but don't benefit from GPUs. Examples include data parsing, statistical analysis, or running legacy scientific code that isn't GPU-aware. CPU nodepools are typically cheaper per hour than GPU pools and can be useful for preprocessing data before feeding it into GPU-intensive steps, or for running control logic and orchestration tasks.

- **High-Memory or Specialized Nodepools:** In some cases, tools might need machines with extra large memory (for in-memory data mining or handling very large datasets), or other specialized hardware (like FPGA or high-bandwidth networking for MPI clusters). Microsoft Discovery can support such specialization by choosing VM sizes that match those needs (for example, ND-series VMs for large GPU memory, or specialized NIC configurations for tightly-coupled simulations). Each nodepool is homogeneous, meaning all nodes have identical specs, to ensure predictable performance for jobs assigned there.

By mixing these hardware-specific nodepools under one supercomputer, an organization can support a diverse set of R&D activities on the same platform. For instance, a pharmaceutical company might maintain one GPU nodepool for AI-driven drug molecule generation, another GPU nodepool with different GPUs for simulation of those molecules, and a CPU nodepool for processing experimental data – all orchestrated by the Discovery platform. Similarly, an electronics engineering team could set up a GPU nodepool for electromagnetic simulations and a CPU nodepool for design verification tasks, illustrating the platform's flexibility beyond traditional scientific domains.

### Scaling and Availability Types

- **Auto-scaling (On-Demand) Nodepools:** These pools are configured with a minimum node count of 0, meaning they have no running nodes when idle, and they automatically provision nodes when work arrives. This is a cost-effective setup for workloads that are burst-y or infrequent – you don’t pay for idle compute. When a researcher’s task is submitted, the platform will spin up the necessary VMs (up to the defined maxNodeCount) in that pool, run the jobs, then scale them back down. Auto-scaling nodepools ensure you have elastic capacity: always enough for the job, but no waste when there’s no work.

- **Persistent (Always-On) Nodepools:** In contrast, some nodepools might be configured with a minNodeCount greater than 0 (even equal to the max, for a fixed-size pool). These guarantee that a certain level of compute is always available. This is useful for mission-critical or latency-sensitive tasks – for example, if you have an interactive analysis tool or a real-time data processing pipeline, you’d want at least one node always running to handle requests immediately, without waiting for a VM to boot. Persistent pools trade a bit of cost efficiency for readiness and throughput consistency. You might use this type for a nodepool servicing a web-based science application or continuously running background simulations.

In summary, Nodepools are highly configurable to match your research computing needs. When planning your Discovery environment, you’ll decide on the types and numbers of nodepools by considering questions like: Do we need GPUs, CPUs, or both? How much baseline capacity should we keep running? Should each lab have its own pool or use common pools? The platform supports all these models, giving IT departments control over resource allocation and giving scientists and engineers the freedom to run experiments or design iterations without worrying about the underlying machine details.

## Supercomputer and Nodepool Artifacts & Requirements

Deploying a Microsoft Discovery Supercomputer and its nodepools requires setting up certain artifacts and configurations in advance. These are the pieces that ensure the HPC environment can operate smoothly within your enterprise infrastructure. The artifacts include networking setups, identity assignments, container images for tools, and resource definitions. Below we detail each of these requirements and how they fit into the overall deployment.

### Network Infrastructure

Because the Discovery Supercomputer runs in your Azure environment, you must provide networking details so that the HPC cluster can integrate with your enterprise network and security controls. Specifically:

Virtual Network and Subnets: The Supercomputer needs an Azure Virtual Network (VNet) for all its nodes to reside in. Within this VNet, typically two subnets are used: one for the Supercomputer’s internal orchestration and management components (often called the system subnet), and another for the compute nodes (the nodepool subnet(s)). When creating the supercomputer resource, you’ll supply a subnetId for the system subnet. Each Nodepool resource will likewise require a subnetId indicating which subnet its VMs should join. It’s recommended (and by default, expected) that the system subnet and nodepool subnets are part of the same VNet so that the Supercomputer’s control plane can coordinate the nodes. In fact, the system subnet should have connectivity to the child NodePool subnets.  This ensures that management traffic (like scheduling commands, health checks, etc.) flows unimpeded between the head node and the worker nodes.

**Note:** The subnets must have adequate IP addresses (/24) for the planned number of nodes and should be configured according to your organization’s network security policies (NSGs, firewalls). If your experiments need access to on-prem resources or internet, those network paths should be enabled similar to how you’d configure any Azure VMs in that VNet.

#### Networking for Data Access

If external API calls are part of your workflow (though often in research computing, data is internal), internet egress may be required. Generally, because the supercomputer lives in your VNet, you have full control of its network traffic: you can enforce that all traffic stays within company network boundaries for compliance, or open specific egress as needed.

### Security and Identity

Enterprise environments require strict access control. The Discovery Supercomputer uses Azure Managed Identities to securely interact with other Azure services on your behalf and to manage the provisioning of VMs:

**Cluster Identity:** When deploying the Supercomputer resource, you will assign a User-Assigned Managed Identity to act as the Cluster Identity. This identity is used by the control plane of the supercomputer to perform Azure operations (like creating VMs for nodepools, mounting storage, etc.) within your subscription. It needs sufficient IAM roles, for example the ability to read the nodepool subnet or attach network interfaces, and to pull container images from your registry. The cluster identity essentially runs the supercomputer’s management service in your subscription.

**Node (Kubelet) Identity:** In addition to the cluster identity, the Supercomputer requires a second managed identity often referred to as the kubelet identity (since under the hood, it’s akin to an AKS cluster’s kubelet identity). This identity is given to the VM instances (nodes) themselves, allowing each node to, for example, access Azure Container Registry (to fetch tool container images) or other Azure resources as needed. For security, the kubelet identity is typically granted more limited scope – but it must be granted the Managed Identity Operator role on the Cluster Identity. This specific requirement allows the node VMs to indirectly use the cluster identity’s privileges for certain operations (without exposing full credentials). It’s a layered security approach - one identity for control plane, one for the node plane, with clear separation of duties.

**Workload Identities:** The Discovery platform also allows specifying workload identities – additional user-assigned identities that tools or agents can use when running on the supercomputer. This is particularly useful if a tool container needs to call an external SaaS API or another Azure service (like querying a Cosmos DB with managed identity). Instead of baking secrets into the tool, you can attach a managed identity to the workload through the platform. The supercomputer resource can be configured with a set of such identities and they are made available as federated credentials to workloads on the nodes.

**Image Registry Credentials:** Typically, container images for your tools will be stored in an Azure Container Registry (ACR) or another registry. The supercomputer’s identities should have pull access to these registries. Often, you can use an ACR that trusts the supercomputer’s managed identity (using AAD authentication) rather than managing docker credentials manually. Ensuring this connectivity means any tool defined in Discovery can be seamlessly launched on the nodepool with its image pulled securely.

**Managed Resource Group:** A noteworthy artifact is that when you create a Supercomputer resource, the platform will automatically create a managed resource group in your subscription to hold the actual Azure resources (like the VM scale sets, etc.) that underpin the supercomputer. This managed RG is usually named by the service (and shown as a property of the supercomputer) and is read-only to you; it exists so Microsoft’s service can lifecycle manage the low-level pieces without cluttering your own resource group. You do not manually create resources in there – any needed VM or storage for the cluster is handled by the Discovery resource provider. Just be aware it exists and ensure your subscription has quota for those resources (e.g., enough cores of the chosen VM sizes). The managed RG approach ensures that all the complex infra (VM scale sets for nodepools, NICs, network configs, etc.) is isolated and doesn’t interfere with your other Azure assets – deletion of the supercomputer resource will clean up that RG automatically.

### Tool Container Images and Software Environment

While “Tools” themselves are covered in separate documentation, it’s worth noting the relationship between tool artifacts and the supercomputer/nodepool environment:

**Container Images:** All computational work executed on the Nodepools runs inside container images. These images package the scientific software, libraries, and any custom code needed for a given tool or task. For example, if you have a tool for genome sequencing, its Docker image might include the genomic analysis binaries and Python libraries. These images must be built to be compatible with the node OS (e.g., Linux images if the node VMs are running Linux, which is the default in Discovery). During deployment of a tool or execution of a task, the platform will pull the required image onto the node from the registry. If you are bringing your own tools, you need to provide the container images as described in the Tools documentation (including any GPU drivers or HPC libraries your tool needs – though note, the base VM image on nodepools will already have necessary GPU drivers/CUDA libraries if it’s a GPU SKU).

**Node OS and Drivers:** Microsoft Discovery’s nodepools use Azure’s HPC-optimized VM images, which come pre-configured with appropriate NVIDIA drivers and HPC SDKs when needed. This means when your container requests access to a GPU, the host has the driver ready. The containers should ideally use CUDA libraries matching the host driver version. Microsoft often provides base container images or guidelines to ensure compatibility. As an artifact, ensure you know the Ubuntu (or other OS) version that the nodepool VMs run, and use a compatible base image for your containers.

**Tool Definitions:** Each tool integrated into Discovery has a tool definition (JSON/YAML) that the control plane uses to know how to deploy it – for code environment tools, it might include a runtime specification; for action-based tools, it lists scripts to run. These definitions aren’t specific to the supercomputer per se, but the supercomputer will reference them when scheduling work. For example, a tool definition might specify it needs a GPU – the scheduler will then place that tool’s run onto a GPU-capable nodepool. In effect, the Nodepool’s characteristics must align with tool requirements. When registering a new tool, you may indicate in its definition what kind of node (GPU/CPU, how much memory, etc.) it needs, which helps the platform choose the correct nodepool.

### Summary of Key Artifacts

To clarify the various artifacts and their roles, the table below summarizes them:

**Step 1:** Create the Supercomputer (Control Plane)

An IT administrator deploys a new **Supercomputer** resource via Azure Portal, CLI, or ARM template. In this step, you choose a name, region, link the required network subnet and assign the managed identities.

**Step 2:** Provisioning of HPC Cluster (Data Plane)

Once the control plane resource is created, the Discovery service automatically sets up the **data plane**: it creates a managed resource group and deploys the necessary Azure resources for the cluster. This includes allocating an internal orchestrator (which could be based on Azure Kubernetes Service or similar HPC scheduler), configuring the system subnet, and preparing the cluster’s baseline environment. This step is handled by Azure asynchronously – when complete, your Supercomputer resource status will transition to `Succeeded`, indicating the HPC cluster is ready.

**Step 3:** Define Nodepools (Control Plane)

Next, you create one or more **Nodepool** resources associated with the Supercomputer. For each Nodepool, you specify the supercomputer it belongs to, the VM size (e.g., GPU type), the node subnet, and scaling parameters (min/max nodes). Each nodepool you add appears under the Supercomputer in Azure Portal. The Discovery service will then provision the corresponding VM Scale Set or VM pool in the managed resource group (data plane). Initially, nodepools can be created with 0 nodes (if auto-scale) or with the minimum nodes running. Over time, you can add more nodepools or adjust their sizes to match your workload needs.

**Step 4:** Deploy Tools & Agents (Control Plane)

With the infrastructure in place, you or tool providers register **Tools** and perhaps custom **Agents** into the Discovery platform (often done via the Discovery Studio interface or CLI). Each tool’s definition includes the container image location and any resource requirements (like “needs GPU”). These tools are now available for use via the Copilot or programmatically, but they don’t “live” on the nodes yet – they are registered in the Discovery catalog, waiting to be invoked.

**Step 5:** Execution on Nodepools (Data Plane)

When a researcher initiates an experiment – say, asking the Copilot to run a simulation or an agent automatically kicking off a workflow – the **Discovery orchestration** kicks in. In addtion jobs can be submitted on the nodepool by the user by directly invoking the data-plane APIs.

**Step 6:** Job Monitoring and Completion

The Supercomputer’s control plane monitors the running jobs on the nodepools. This might involve a job queue, logging, and health checks from the orchestrator (e.g., Kubernetes control plane) back to the Discovery service. As jobs run, researchers can get status updates via Copilot (since the agents are tracking progress). When a job finishes, the results (files, data) can be saved to the designated storage (which could be one of the linked Storage resources in Discovery) and the container terminates. The platform may then spin down idle nodes if using auto-scaling.

**Step 7:** Iteration and Scaling

At this point, the heavy lifting is done – the researcher reviews results, maybe asks follow-up questions, leading to new runs. The Nodepools will dynamically scale as per demand. Administrators can always adjust Nodepool sizes or add new nodepools if projects grow. The separation of concerns is clear: scientists focus on the experiments, while IT ensures the Supercomputer and Nodepools remain healthy and cost-efficient.

**Step 8:** Management and Decommission

If the Supercomputer is no longer needed, deleting the Supercomputer resource will automatically clean up all nodepools and associated VMs in the managed resource group. The control plane (ARM resources) goes away, and the data plane cluster is torn down accordingly. This lifecycle management is handled in a governed manner – for instance, deletions are a long-running operation with proper status monitoring and confirmations to avoid accidental loss.

## Integration with Microsoft.Discovery/Storages

The Microsoft Discovery platform provides seamless integration between Supercomputers and Azure HPC storage resources through the Microsoft.Discovery/Storages resource type. For high-performance computing workloads that require fast, scalable file storage, Azure NetApp Files (ANF) offers an optimal solution.

### Azure NetApp Files Integration

Azure NetApp Files provides enterprise-grade, high-performance file storage for scientific computing workloads. When integrated with Microsoft Discovery Supercomputers, it enables:

- Ultra-low latency for I/O-intensive HPC applications
- Scalable storage performance that can match compute capabilities
- Support for various protocols (NFSv3, NFSv4.1) that scientific applications require
- Enterprise-grade data protection and snapshots

The Microsoft.Discovery/Storages resource with Azure NetApp Files can be deployed and linked to your Supercomputer during job submission, making it available to all workloads running on the nodepools.

### DataContainers and Data Assets Integration

Beyond the storage infrastructure itself, Microsoft Discovery provides structured ways to manage scientific data through DataContainers and Data assets. These components form a crucial part of the tool execution pipeline on the supercomputer.

#### DataContainers

DataContainers in Microsoft Discovery represent logical data stores that abstract the underlying storage technology details, providing researchers with a consistent interface regardless of whether the data is stored in Azure Blob Storage, or Discovery Storage. Key aspects of DataContainers include:

- **Storage Abstraction**: DataContainers provide a unified way to access data across different storage types
- **Access Control**: They include credential management for secure access to the underlying storage

- **Integration Point**: They serve as the integration layer between storage resources and research tools

DataContainers are created as Microsoft.Discovery.DataContainer resources and linked to specific storage accounts or volumes:

#### Data Assets

Data assets represent the actual files, datasets, or collections within DataContainers. They provide:

- **Contextual Organization**: Data assets help organize research data by experiment, project, or scientific domain
- **Provenance**: Information about data origins and transformations
- **Metadata Management**: DataAssets support descriptive metadata to improve discoverability and organization
- **Tool Input/Output**: Structured mechanism for tools to consume and produce data

Data assets typically include metadata that describes their contents, format, and relationships to other assets, making them discoverable and usable in scientific workflows.

#### Supercomputer Data-Plane API for Tool Execution

The integration of DataContainers and Data assets with the supercomputer's data-plane API provides a powerful mechanism for tool execution in scientific workflows:

1. **Tool Invocation with Data References**: When a tool is invoked, it can reference specific Data assets as inputs:
2. **Data-Plane Execution**: The supercomputer's data-plane API handles:
   - Resolving data references to actual storage locations
   - Mounting or accessing the required data for the tool
   - Scheduling the tool on appropriate nodepools
   - Managing authentication between the tool and data sources
   - Capturing outputs to the specified locations
3. **Containerized Execution**: When the tool runs on the supercomputer, it receives the input data paths as environment variables or configuration files, and the containerized environment has the necessary access to read and write data.
