import os
import json
import argparse

def update_json_files(directory, suffix):
    # Add debugging output to log the processing of files and changes made
    print(f"Looking for JSON files in directory: {directory}")

    # Iterate through all JSON files in the directory
    for filename in os.listdir(directory):
        print(f"Processing file: {filename}")
        if filename.endswith('.json'):
            filepath = os.path.join(directory, filename)

            # Read the JSON file
            with open(filepath, 'r') as file:
                data = json.load(file)

            # Check if the 'name' field exists at the top level or under 'agent'
            if 'name' in data:
                original_name = data['name']
                new_name = f"{original_name}{suffix}"
                print(f"Updating top-level name: {original_name} -> {new_name}")
                data['name'] = new_name
            elif 'agent' in data and 'name' in data['agent']:
                original_name = data['agent']['name']
                new_name = f"{original_name}{suffix}"
                print(f"Updating agent name: {original_name} -> {new_name}")
                data['agent']['name'] = new_name

            # Update agent names in workflow files
            if 'states' in data:
                for state in data['states']:
                    if 'actors' in state:
                        for actor in state['actors']:
                            if 'agent' in actor and isinstance(actor['agent'], str):
                                original_agent = actor['agent']
                                actor['agent'] = f"{original_agent}{suffix}"
                                print(f"Updating actor agent: {original_agent} -> {actor['agent']}")

            # Write the updated JSON back to the file
            with open(filepath, 'w') as file:
                json.dump(data, file, indent=4)

            # Rename the file to match the new name while maintaining the suffix
            if '-agent-definition' in filename:
                new_filename = f"{new_name}-agent-definition.json"
            elif '-workflow-definition' in filename:
                new_filename = f"{new_name}-workflow-definition.json"
            else:
                print(f"Skipping file {filename}: Unrecognized file naming convention.")
                continue

            new_filepath = os.path.join(directory, new_filename)
            os.rename(filepath, new_filepath)

            print(f"Updated {filename} -> {new_filename}")

def main():
    parser = argparse.ArgumentParser(description="Update names in JSON files by adding a suffix.")
    parser.add_argument('--suffix', required=True, help="Suffix to append to names.")
    parser.add_argument('--directory', default='./jsonFiles', help="Directory containing the JSON files (default: './jsonFiles').")
    args = parser.parse_args()

    # Resolve the directory path
    json_directory = os.path.abspath(args.directory)

    # Update JSON files with the provided suffix
    update_json_files(json_directory, args.suffix)

if __name__ == "__main__":
    main()
