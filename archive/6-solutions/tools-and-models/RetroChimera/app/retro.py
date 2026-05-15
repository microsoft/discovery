import os
import json
import requests
import argparse

# Endpoint and authentication configuration
api_key = os.environ.get("API_KEY", None)
http_endpoint = os.environ.get("HTTP_ENDPOINT", None)
if http_endpoint and not http_endpoint.startswith("https://"):
    http_endpoint = "https://" + http_endpoint.lstrip("/")

if not api_key:
    model_endpoint = os.environ.get("MODEL_ENDPOINT")

    # Extract workspace information from the endpoint resource ID
    endpoint_parts = model_endpoint.split('/')
    subscription_id = endpoint_parts[2]
    resource_group = endpoint_parts[4]
    workspace_name = endpoint_parts[8]
    
    # Authenticate with managed identity to retrieve API key from model registry
    from azure.identity import DefaultAzureCredential
    credential = DefaultAzureCredential()
    from azure.ai.ml import MLClient
    ml_client = MLClient(credential, subscription_id, resource_group, workspace_name)

    # Get the endpoint name from the model endpoint resource ID
    endpoint_name = endpoint_parts[-1]

    # Get the endpoint object
    endpoint = ml_client.online_endpoints.get(name=endpoint_name)
    http_endpoint = endpoint.scoring_uri

    # Get the model name and version from the endpoint deployment settings
    model_name = endpoint.deployment_settings['default_deployment'].model.name
    model_version = endpoint.deployment_settings['default_deployment'].model.version

    # Retrieve the API key from the model registry
    model = ml_client.models.get(name=model_name, version=model_version)
    api_key = model.properties["api_key"]

# Parse command line arguments
parser = argparse.ArgumentParser(description='RetroChimera API client')
parser.add_argument('--workflow', type=str, required=True,
                    help='Workflow type (required)')
parser.add_argument('--smiles', type=str, required=True,
                    help='Input SMILES string(s) - single or comma-separated (required)')
parser.add_argument('--num_results', type=int, default=3,
                    help='Number of results to return (default: 3)')
parser.add_argument('--time_limit_s', type=int, default=60,
                    help='Time limit in seconds for multi_step workflow (default: 60)')
parser.add_argument('--num_routes', type=int, default=3,
                    help='Number of routes to consider (default: 3)')
parser.add_argument('--num_routes_for_initial_extraction', type=int, default=500,
                    help='Number of routes for initial extraction (default: 500)')

args = parser.parse_args()

# Process input SMILES strings - split by comma and strip whitespace
input_smiles = [smiles.strip() for smiles in args.smiles.split(',')]

print(f"Using parameters:")
print(f"  Workflow: {args.workflow}")
print(f"  Inputs ({len(input_smiles)} SMILES):")
for i, smiles in enumerate(input_smiles, 1):
    print(f"    {i}. {smiles}")
if args.workflow == "multi_step":
    print(f"  Time limit (seconds): {args.time_limit_s}")
    print(f"  Number of routes: {args.num_routes}")
    print(f"  Number of routes for initial extraction: {args.num_routes_for_initial_extraction}")
else:
    print(f"  Number of results: {args.num_results}")
print()

# Set up headers and endpoint
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}",
    "Accept": "application/json"
}

# Request payload
payload = {
    "input_data": {
        "inputs": input_smiles,
        "workflow": args.workflow
    }
}

# Add workflow-specific parameters
if args.workflow == "multi_step":
    payload["input_data"]["time_limit_s"] = args.time_limit_s
    payload["input_data"]["num_routes"] = args.num_routes
    payload["input_data"]["num_routes_for_initial_extraction"] = args.num_routes_for_initial_extraction
else:
    payload["input_data"]["num_results"] = args.num_results

# Make the POST request
response = requests.post(http_endpoint, headers=headers, data=json.dumps(payload))

# Print the response
print("Status code:", response.status_code)
try:
    response_json = response.json()
    print("Response (JSON):", json.dumps(response_json, indent=2))
except ValueError:
    print("Response (raw):", response.text)