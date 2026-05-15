#!/bin/bash
# Generate test input files for local testing

set -e

# Create test data directory
TEST_DIR="../test_inputs"
mkdir -p "$TEST_DIR"

echo "Generating test input files in $TEST_DIR/"

# Generate 20 test files with random numbers
for i in {1..20}; do
    FILE="$TEST_DIR/input_file_$(printf "%03d" $i).txt"
    
    # Generate random number of lines (10-50)
    NUM_LINES=$((10 + RANDOM % 40))
    
    # Write header
    echo "Test Input File $i" > "$FILE"
    echo "Generated: $(date)" >> "$FILE"
    echo "---" >> "$FILE"
    
    # Write random numbers
    for j in $(seq 1 $NUM_LINES); do
        # Generate 5-10 random numbers per line
        NUM_NUMBERS=$((5 + RANDOM % 6))
        for k in $(seq 1 $NUM_NUMBERS); do
            echo -n "$((RANDOM % 1000)) " >> "$FILE"
        done
        echo "" >> "$FILE"
    done
    
    echo "Created $FILE with $NUM_LINES lines"
done

echo ""
echo "Test data generation complete!"
echo "Total files: $(ls -1 $TEST_DIR | wc -l)"
echo ""
echo "To run with this test data:"
echo "  cd utils/"
echo "  ./test-local.sh 5"
