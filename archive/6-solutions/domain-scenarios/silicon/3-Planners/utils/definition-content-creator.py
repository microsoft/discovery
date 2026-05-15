"""
Definition Content Creator

This script converts YAML files to JSON suitable for embedding in ARM templates or as regular JSON.
It includes special handling for workflow files, where the agent name is copied to the workflow object
and then the agent object is removed from the data.

Usage:
    python Definition-content-creator.py path/to/file.yaml [--output output_file.txt] [--json]
"""
import sys
import json
import yaml
import argparse

def yaml_to_json(yaml_file_path, output_file=None, as_string=True):
    """
    Convert YAML file to JSON, either as a string suitable for embedding in ARM templates
    or as proper formatted JSON.
    
    For files that contain a "workflow" object, this function will:
    1. Copy the name from the "agent" object to the "workflow" object
    2. Remove the "agent" object from the data after copying its name
    
    Args:
        yaml_file_path (str): Path to the YAML file.
        output_file (str, optional): Output file path. If not provided, prints to stdout.
        as_string (bool): If True, outputs an escaped JSON string for ARM templates.
                         If False, outputs proper JSON.
    """
    with open(yaml_file_path, 'r') as f:
        data = yaml.safe_load(f)
    
    # Special handling for files with "workflow" object
    if "workflow" in data:
        if "agent" in data and "name" in data["agent"]:
            # Copy the name from agent object to workflow object
            data["workflow"]["name"] = data["agent"]["name"]
            print(f"Copied agent name '{data['agent']['name']}' to workflow object")
            
            # Remove the agent object after copying its name
            del data["agent"]
            print("Removed agent object after copying its name")
        else:
            print("Warning: Found workflow object but could not find agent name")
            
        # Move workflow content to the root level with states first
        workflow_content = data["workflow"]
        # Remove the workflow property
        del data["workflow"]
        
        # Create a new ordered dictionary to ensure states comes first
        ordered_data = {}
        
        # First add states if it exists in workflow content
        if "states" in workflow_content:
            ordered_data["states"] = workflow_content.pop("states")
        
        # Add remaining workflow content
        for key, value in workflow_content.items():
            ordered_data[key] = value
            
        # Add the rest of the original data
        for key, value in data.items():
            if key not in ordered_data:
                ordered_data[key] = value
                
        # Replace original data with ordered data
        data = ordered_data
        
        print("Moved workflow content to root level with states first and removed workflow property")

    # Add support for new agents and workflows
    supported_agents = ["CodeReviewer", "Coder", "CoderWithSaveTool"]
    supported_workflows = ["CoderWf", "CoderAndReviewerWf", "CoderWithSaveToolWf"]

    if "agent" in data and data["agent"].get("name") not in supported_agents:
        print(f"Warning: Unsupported agent {data['agent']['name']} detected.")

    if "workflow" in data and data["workflow"].get("name") not in supported_workflows:
        print(f"Warning: Unsupported workflow {data['workflow']['name']} detected.")
    
    if as_string:
        # First convert to compact JSON
        json_str = json.dumps(data, separators=(',', ':'), ensure_ascii=True)
        
        # Properly escape for ARM templates:
        # 1. Escape backslashes
        # 2. Escape double quotes
        output_content = json_str.replace('\\', '\\\\').replace('"', '\\"')
        print("Generated ARM-ready JSON string")
    else:
        # Output properly formatted JSON
        output_content = json.dumps(data, indent=2, ensure_ascii=True)
        print("Generated properly formatted JSON")
    
    if output_file:
        with open(output_file, 'w') as f:
            f.write(output_content)
        print(f"Output written to {output_file}")
    else:
        print(output_content)

def main():
    parser = argparse.ArgumentParser(
        description='Convert YAML file to JSON with special handling for workflow files (copies agent name to workflow and removes agent object)')
    parser.add_argument('yaml_file', help='Input YAML file path')
    parser.add_argument('--output', '-o', help='Output file (if not provided, prints to stdout)')
    parser.add_argument('--json', '-j', action='store_true', 
                        help='Output properly formatted JSON instead of ARM-compatible JSON string')
    
    args = parser.parse_args()
    yaml_to_json(args.yaml_file, args.output, not args.json)

if __name__ == "__main__":
    main()