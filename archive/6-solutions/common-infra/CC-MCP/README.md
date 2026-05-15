# Azure NetApp Files MCP services

This example provides both the server and Discovery client solutions to implement an MCP connection to Cyclecloud. Cyclecloud enables the orchestration of Azure VM resources in conjuction with job schedulers such as SLURM used in this example.

This solution enables Discovery to dispatch workloads that require a traditional job scheduler such as SLURM, LSF, GridEngine, or PBSPro. It also accommodates HPC workloads that are either too large or too complex to containerize, and workloads that rely on extensive associated workload or data files.

## Structural Elements

This solution consists of three components:

1. **Cyclecloud**: Azure CycleCloud is an enterprise-friendly tool for orchestrating and managing High Performance Computing (HPC) environments on Azure. With CycleCloud, you can provision infrastructure for HPC systems, deploy familiar HPC schedulers, and automatically scale the infrastructure to run jobs efficiently at any scale. Through CycleCloud, you can create different types of file systems and mount them to the compute cluster nodes to support HPC workloads.

Configure Cyclecloud following the instructions included in:

https://learn.microsoft.com/en-us/azure/cyclecloud

Configure Cyclecloud to use the same NFS volume defined in the ANF-S3-MCP setup as the shared volume for all workload VMs. That volume should contain all your working files and HPC tool binaries.

Provision a persistent login node. This node is used by the MCP server to connect to and dispatch jobs to Cyclecloud.

Configure a SLURM cluster for the following MCP server to interface with.

2. ** AI Infrastructure Server**: This is a MCP server developed by a hackathon team within Microsoft led by Paul Edwards. The repository for the source is located at:

https://github.com/Azure/ai-infrastructure-on-azure

This MCP server allows AI agents to dispatch SLURM commands to Cyclecloud along with some basic file operations. Currently enabled functions are:

- sacct - Slurm job accounting
- squeue - queue inspection
- sinfo - cluster node/partition information
- sbatch - dispatch job to SLURM cluster
- head_file - display the first lines of a file
- tail_file - display the last lines of a file
- file_search - search for a pattern in a file
- create_file - create a new file with specified content

The version of the MCP server included in this example enables the http interface by default.

After creating your virtual environment, ensure that the following environment variables are provisioned in your environment:

CLUSTER_HOST="<IP Address of your Cyclecloud login node>"
CLUSTER_USER="<username running cyclecloud>"
CLUSTER_PRIVATE_KEY="<key used to log into the login node>"
CLUSTER_PORT=22

One way to so this to edit the .venv/bin/activate file to include:

export CLUSTER_HOST="<IP Address of your Cyclecloud login node>"
export CLUSTER_USER="<Cyclecloud username>"
export CLUSTER_PRIVATE_KEY="<key used to log into the login node>"
export CLUSTER_PORT=22

After successfully implementing and running your MCP server, make sure that you are able to connect to the Cyclecloud login node from the MCP server.

ssh -i <key used to log into the login node> <Cyclecloud username>@<IP Address of your Cyclecloud login node>"


3. **Discovery MCP Client**: The Discovery MCP client files are located in the cc-mcp-client directory. It consists of the docker container definition as well as included Discovery tool, agents, and workflow examples. Refer to the README.md in that directory for details.

   **Supporting Tools**: The MCP client provides access to the following tools defined in `cc-mcp-client/tools/cc-MCPTool.yaml`:

   **SLURM Job Management:**
   - `checkqueue` - Run Slurm squeue to check job queue with optional output format
   - `submitjob` - Submit a job using sbatch with optional partition specification
   - `clusterinfo` - Get cluster node and partition info using sinfo with optional format
   - `jobaccounting` - Retrieve job accounting data using sacct with time range options

   **File Operations:**
   - `filehead` - Read first lines of a file (configurable number of lines)
   - `filetail` - Read last lines of a file (configurable number of lines)
   - `filesearch` - Search for a pattern in a file
   - `createfile` - Create a file with specified content

   **Azure/HPC Queries:**
   - `getinfinibandpkeys` - Retrieve InfiniBand P_Keys for hosts
   - `getphysicalhostnames` - Retrieve Azure physical hostnames for VMs

