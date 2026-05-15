# MPI Example

A generic MPI master-worker pattern demonstrating dynamic load balancing and task distribution, deployable on Microsoft Discovery platform.

## Overview

This example demonstrates:
- **Master-Worker Pattern**: One master process (rank 0) coordinates multiple worker processes
- **Dynamic Load Balancing**: Work is distributed as workers become available
- **Scalability**: Easily scale by changing the pool size
- **Real-world Structure**: Production-ready containerization and deployment configuration

> **Note**: Microsoft Discovery currently supports MPI communication over Ethernet only. InfiniBand is not supported at this time.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Master Node (Rank 0)               │
│  - Distributes tasks to workers                     │
│  - Collects results                                 │
│  - Implements dynamic load balancing                │
│  - Generates final output                           │
└──────────────┬──────────────────────┬───────────────┘
               │                      │
       ┌───────┴────────┐    ┌───────┴────────┐
       │  Worker Node   │    │  Worker Node   │
       │   (Rank 1)     │    │   (Rank 2)     │
       │                │    │                │
       │  - Receives    │    │  - Receives    │
       │    tasks       │    │    tasks       │
       │  - Processes   │    │  - Processes   │
       │  - Returns     │    │  - Returns     │
       │    results     │    │    results     │
       └────────────────┘    └────────────────┘
```

## Files Structure

```
mpi-example/
├── src/
│   ├── master_worker.c                  # Main MPI application (444 lines)
│   └── Makefile                         # Build configuration with GNU extensions
├── test-scripts/
│   ├── test-local.sh                    # Local testing script
│   └── generate-test-data.sh            # Test data generator (creates 20 files)
├── test_inputs/
│   └── input_file_*.txt                 # Generated test data files (20 files)
├── test_outputs/
│   └── results.txt                      # Processing results output
├── Dockerfile                           # Multi-stage container build (Azure Linux 3.0)
├── mpi-example-tool-definition.yaml     # Discovery tool definition (Ethernet, static pool)
├── mpi-example-tool-definition.json     # JSON version of tool definition
├── mpi-example-agent-definition.yaml    # Discovery agent definition with instructions
├── mpi-example-agent-definition.json    # JSON version of agent definition
├── mpi-example-workflow.yaml            # Workflow orchestration definition
├── mpi-example-workflow.json            # JSON version of workflow definition
├── .dockerignore                        # Docker build exclusions
└── README.md                            # This file
```

## How It Works

### 1. Master Node (Rank 0)
- Seeds workers with initial tasks
- Waits for results from any worker
- When a result arrives, immediately sends the next task to that worker
- Continues until all tasks are complete
- Sends termination signals to all workers
- Writes final results to `results.txt`

### 2. Worker Nodes (Rank 1+)
- Wait for task from master
- Process the task (compute square of input)
- Send result back to master
- Repeat until receiving termination signal

### 3. Dynamic Load Balancing
Workers that complete tasks faster automatically receive more work, ensuring efficient resource utilization even with variable task durations.

## Building the Container

### Prerequisites
- Docker or Podman
- Azure Container Registry (ACR) access

### Build Steps

```bash
# Build the container
docker build -t mpi-example:latest .

# Tag for your ACR
docker tag mpi-example:latest <YOUR_ACR_NAME>.azurecr.io/mpi-example:latest

# Login to ACR
az acr login --name <YOUR_ACR_NAME>

# Push to ACR
docker push <YOUR_ACR_NAME>.azurecr.io/mpi-example:latest
```

## Local Testing (without Discovery)

You can test the MPI application locally on a single machine. Ensure you create a directory for storing output results `test_outputs` under current working directory.

```bash
# Generate test data first
cd test-scripts/
./generate-test-data.sh

# Use the automated test script (recommended)
./test-local.sh 5  # Runs with 5 processes (1 master + 4 workers)

# Or build and run manually with Docker
cd ..
docker run --rm \
  -v $(pwd)/test_inputs:/app/inputs:ro \
  -v $(pwd)/test_outputs:/app/outputs \
  -e INPUT_DIR=/app/inputs \
  -e OUTPUT_DIR=/app/outputs \
  mduatestacr.azurecr.io/mpi-example:latest \
  bash -c 'source /etc/profile.d/modules.sh && module load mpi/openmpi-x86_64 && mpirun --allow-run-as-root -np 5 /root/master_worker'

# Or compile and run natively (requires OpenMPI installed)
cd src/
make
cd ..
INPUT_DIR=test_inputs OUTPUT_DIR=test_outputs \
  bash -c 'source /etc/profile.d/modules.sh && module load mpi/openmpi-x86_64 && mpirun --allow-run-as-root -np 5 src/master_worker'
```

## Deploying to Microsoft Discovery

### 1. Update Configuration

Edit `mpi-example-tool-definition.yaml` and replace:
- `<YOUR_ACR_NAME>` with your Azure Container Registry name

### 2. Adjust Pool Size

Change `pool_size` in the tool definition to set the number of containers:
```yaml
compute:
  pool_size: 5  # Total containers for MPI execution
```

### 3. Deploy to Discovery

Deploy the Discovery Tool Control plane resource through REST API or portal.

### 4. Run the Tool

Once deployed, invoke the `process_files` action with:
- `num_processes`: Number of MPI processes to use (must be at least 2)

Input files should be mounted to `/app/inputs/` and outputs will be written to `/app/outputs/results.txt`.

>**Note**: Create a data asset and ensure you have all the files under ./test_inputs folder to the Data Asset.

**Command executed by the platform**:
```bash
bash -c 'source /etc/profile.d/modules.sh && module load mpi/openmpi-x86_64 && mpirun --allow-run-as-root --hostfile /var/run/Microsoft.Discovery/mpi-hosts -np 5 /root/master_worker'
```

The platform provides `/var/run/Microsoft.Discovery/mpi-hosts` which maps MPI processes across multiple containers in your pool.

### 5. Running via VS Code Extension

If using the Discovery VS Code extension for testing:

```bash
# Command for Discovery platform (uses hostfile for multi-container distribution)
bash -c 'source /etc/profile.d/modules.sh && module load mpi/openmpi-x86_64 && mpirun --allow-run-as-root --hostfile /var/run/Microsoft.Discovery/mpi-hosts -np 5 /root/master_worker'
```

## Key Differences: Discovery Platform vs Local Testing

| Aspect | Discovery Platform | Local Testing |
|--------|-------------------|---------------|
| MPI Distribution | Multi-container via hostfile | Single machine |
| Command | Uses `/var/run/Microsoft.Discovery/mpi-hosts` | Not required |
| Worker Nodes | Different container hostnames (e.g., `sc-xxx-worker-w-0-0`, `sc-xxx-worker-w-0-1`) | Same hostname |
| Parallelism | True distributed across physical nodes | Process-level parallelism on single CPU |
| Performance | Linear scaling with containers | Limited by single machine resources |
| Output | Shows different MPI ranks on different nodes | All ranks on same machine |

## Example Output

After running successfully, you'll see results in `/app/outputs/results.txt`:

```
MPI Master-Worker Processing Results
====================================

Total files processed: 20
Total time: 2.00 seconds
Workers used: 4

Task ID  | Filename                       | Lines    | Numbers Sum  | MPI Rank   | Worker Node                      | Status
---------|--------------------------------|----------|--------------|------------|----------------------------------|----------
0        | input_file_001.txt             | 28       | 88686        | 1          | sc-xxx-worker-l-0-0              | SUCCESS
1        | input_file_002.txt             | 49       | 177826       | 2          | sc-xxx-worker-w-0-0              | SUCCESS
2        | input_file_003.txt             | 29       | 90823        | 2          | sc-xxx-worker-w-0-0              | SUCCESS
3        | input_file_004.txt             | 37       | 137601       | 3          | sc-xxx-worker-w-0-1              | SUCCESS

Summary:
  Total lines processed: 629
  Total sum of numbers: 2217875
```

**Note**: The MPI Rank column shows which worker process handled each file, and Worker Node shows the container hostname, demonstrating true distributed execution.

## Troubleshooting

**Problem**: Tool deployment fails with "Infiniband not supported" error  
**Solution**: Set `infiniband: false` in the tool definition. Standard Ethernet networking works fine for this workload.

**Problem**: "Not enough slots available" error when running  
**Solution**: Verify command configuration:
- **Discovery platform**: Must use `--hostfile /var/run/Microsoft.Discovery/mpi-hosts`

**Problem**: Slow performance  
**Solution**: Increase `num_processes` parameter. Each additional worker improves parallelism up to the number of files being processed.

**Problem**: Build fails locally  
**Solution**: Ensure OpenMPI and build tools are installed:
```bash
# Ubuntu/Debian
sudo apt-get install build-essential openmpi-bin libopenmpi-dev

# RHEL/CentOS/Fedora
sudo dnf install make gcc openmpi openmpi-devel

# After installation, load MPI module
module load mpi/openmpi-x86_64
```

## References

- [OpenMPI Documentation](https://www.open-mpi.org/doc/)
- [Microsoft Discovery Documentation](https://learn.microsoft.com/azure/discovery)
- [MPI Standard](https://www.mpi-forum.org/)

## License

This example is provided as-is for educational and development purposes.
