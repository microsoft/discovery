#!/bin/bash
# Local testing script for MPI Master-Worker example

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== Local MPI Test Script ===${NC}"
echo ""

# Check if MPI is installed
if ! command -v mpirun &> /dev/null; then
    echo -e "${RED}Error: mpirun not found. Please install OpenMPI:${NC}"
    echo "  Ubuntu/Debian: sudo apt-get install openmpi-bin libopenmpi-dev"
    echo "  RHEL/CentOS:   sudo yum install openmpi openmpi-devel"
    echo "  macOS:         brew install open-mpi"
    exit 1
fi

# Generate test data if it doesn't exist
if [ ! -d "../test_inputs" ] || [ -z "$(ls -A ../test_inputs 2>/dev/null)" ]; then
    echo -e "${YELLOW}Generating test input files...${NC}"
    ./generate-test-data.sh
    echo ""
fi

# Create output directory
mkdir -p ../test_outputs

# Check if make is installed
if ! command -v make &> /dev/null; then
    echo -e "${RED}Error: make not found. Please install build tools:${NC}"
    echo "  Ubuntu/Debian: sudo apt-get install build-essential"
    echo "  RHEL/CentOS:   sudo yum groupinstall 'Development Tools'"
    echo "  macOS:         xcode-select --install"
    exit 1
fi

# Build the application
cd ../src/
echo -e "${YELLOW}Building application...${NC}"
make clean 2>/dev/null || true
make
if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Build failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Build successful${NC}"
echo ""

# Test with different numbers of processes
NUM_PROCESSES=${1:-5}  # Default to 5 processes if not specified

echo -e "${YELLOW}Running MPI test with ${NUM_PROCESSES} processes (1 master + $((NUM_PROCESSES-1)) workers)...${NC}"
echo ""

# Run with test data
INPUT_DIR="../test_inputs" OUTPUT_DIR="../test_outputs" mpirun -np ${NUM_PROCESSES} ./master_worker

echo ""
echo -e "${GREEN}=== Test Complete ===${NC}"
echo ""

if [ -f "../test_outputs/results.txt" ]; then
    echo "Results written to: test_outputs/results.txt"
    echo ""
    echo "Results summary:"
    head -20 ../test_outputs/results.txt
    echo ""
    echo "Full results available at: test_outputs/results.txt"
fi

echo ""
echo "To run with different number of processes:"
echo "  ./test-local.sh <number_of_processes>"
echo ""
echo "To enable debug output:"
echo "  cd src/ && make debug && INPUT_DIR=../test_inputs OUTPUT_DIR=../test_outputs mpirun -np ${NUM_PROCESSES} ./master_worker"
echo ""
echo "To regenerate test data:"
echo "  cd utils/ && ./generate-test-data.sh"