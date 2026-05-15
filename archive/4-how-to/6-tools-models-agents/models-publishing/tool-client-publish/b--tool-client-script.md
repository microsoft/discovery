# Sample action script files

## client.py
```
#!/usr/bin/env python
"""
Linear Regression Model Inference Tool

This script allows for inferencing with a Linear Regression model using Azure ML Online Endpoints.

Usage:
    python lr_client.py --batch_size 2 --inputs '[0.7490802377, 0.5234518291]'
    python lr_client.py --inputs_file path/to/input_file.txt
    python lr_client.py --inputs '[0.7490802377, 0.5234518291, 0.9123476234]'

"""

import urllib.request
import argparse
import json
import os
import ssl
import re
import glob
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
import time
from urllib.error import HTTPError
from dotenv import load_dotenv
from azure.ai.ml import MLClient
from azure.identity import DefaultAzureCredential, ClientSecretCredential, InteractiveBrowserCredential
from io_utils import setup_session_logger, log_message, log_step, log_result, log_error, finalize_session_log

# Load environment variables from .env file
load_dotenv()

# Constants
ENDPOINT_RESOURCE_ID = os.environ.get('MODEL_ENDPOINT')
if not ENDPOINT_RESOURCE_ID:
    raise ValueError("Environment variable 'MODEL_ENDPOINT' is not set. Please set it in .env file.")

# Authentication configuration
AZURE_CLIENT_ID = os.environ.get('AZURE_CLIENT_ID')
AZURE_CLIENT_SECRET = os.environ.get('AZURE_CLIENT_SECRET')
AZURE_TENANT_ID = os.environ.get('AZURE_TENANT_ID')
AUTH_METHOD = os.environ.get('AUTH_METHOD', 'default')  # Options: 'service_principal', 'interactive', 'default'

def parse_inputs(inputs_str: str) -> List[float]:
    """Parse input string as JSON array and return list of floats."""
    try:
        inputs_list = json.loads(inputs_str)
        if not isinstance(inputs_list, list):
            raise ValueError("Inputs must be a JSON array")
        
        # Convert all inputs to float
        return [float(x) for x in inputs_list]
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        raise ValueError(f"Invalid input format. Expected JSON array of numbers, got: {inputs_str}. Error: {e}")

def read_inputs_from_file(file_path: str) -> List[float]:
    """Read inputs from a text file (one number per line)."""
    try:
        inputs = []
        with open(file_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line:  # Skip empty lines
                    try:
                        inputs.append(float(line))
                    except ValueError:
                        log_error(f"Invalid number on line {line_num}: {line}")
                        continue
        
        if not inputs:
            raise ValueError(f"No valid numbers found in file: {file_path}")
        
        log_message(f"Read {len(inputs)} inputs from file: {file_path}")
        return inputs
    except FileNotFoundError:
        raise ValueError(f"Input file not found: {file_path}")
    except Exception as e:
        raise ValueError(f"Error reading input file {file_path}: {e}")

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Linear Regression Inference Tool")
    parser.add_argument("--batch_size", type=int, default=0, help="Batch size for inference")
    
    # Input options - either direct inputs or file
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--inputs", type=str, help="Input data as JSON array string, e.g., '[0.7490802377, 0.5234518291]'")
    input_group.add_argument("--inputs_file", type=str, help="Path to file containing input values (one per line)")

    return parser.parse_args()

def get_ml_client() -> MLClient:
    """Create and return an MLClient using the specified authentication method."""
    try:
        # Choose authentication method based on environment variable
        if AUTH_METHOD == 'service_principal':
            if not all([AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID]):
                raise ValueError(
                    "For service principal authentication, you must set: "
                    "AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, and AZURE_TENANT_ID in your .env file"
                )
            
            log_message("Using Service Principal authentication")
            credential = ClientSecretCredential(
                tenant_id=AZURE_TENANT_ID,
                client_id=AZURE_CLIENT_ID,
                client_secret=AZURE_CLIENT_SECRET
            )
        
        elif AUTH_METHOD == 'interactive':
            log_message("Using Interactive Browser authentication")
            credential = InteractiveBrowserCredential(
                tenant_id=AZURE_TENANT_ID if AZURE_TENANT_ID else None
            )
        
        elif AUTH_METHOD == 'default':
            log_message("Using Default Azure Credential (requires Azure CLI login or managed identity)")
            credential = DefaultAzureCredential()
        
        else:
            raise ValueError(f"Unknown AUTH_METHOD: {AUTH_METHOD}. Use 'service_principal', 'interactive', or 'default'")
        
        # Extract workspace information from the endpoint resource ID
        endpoint_parts = ENDPOINT_RESOURCE_ID.split('/')
        subscription_id = endpoint_parts[2]
        resource_group = endpoint_parts[4]
        workspace_name = endpoint_parts[8]
        
        log_message(f"Connecting to ML workspace: {workspace_name}")
        log_message(f"In resource group: {resource_group}")
        log_message(f"In subscription: {subscription_id}")
        
        # Create the ML client
        ml_client = MLClient(
            credential=credential,
            subscription_id=subscription_id,
            resource_group_name=resource_group,
            workspace_name=workspace_name
        )
        
        return ml_client
    
    except Exception as e:
        log_error(f"Error creating ML client", e)
        return None

def get_online_endpoint_info(ml_client: MLClient) -> Dict[str, str]:
    """Get the online endpoint's scoring URI and API key."""
    try:
        # Extract endpoint name from resource ID
        endpoint_name = ENDPOINT_RESOURCE_ID.split('/')[-1]

        # Get the endpoint
        endpoint = ml_client.online_endpoints.get(name=endpoint_name)
        
        # Get the scoring URI and key
        scoring_uri = endpoint.scoring_uri
        key = ml_client.online_endpoints.get_keys(name=endpoint_name).primary_key
        
        log_message(f"Successfully retrieved endpoint information for: {endpoint_name}")
        
        return {
            "scoring_uri": scoring_uri,
            "endpoint_name": endpoint_name,
            "key": key
        }
    
    except Exception as e:
        log_error(f"Error getting endpoint information", e)
        sys.exit(1)

def run_inference(endpoint_info: Dict[str, str], inputs: List[float]) -> Dict[str, Any]:
    """Run inference on the Linear Regression model."""
    try:
        # Validate inputs
        if not inputs or not isinstance(inputs, list):
            raise ValueError("Inputs must be a non-empty list of numbers")
        
        # Prepare the model input data in the required format
        # Each input value should be in its own row
        data = [[float(x)] for x in inputs]
        index = list(range(len(inputs)))
        
        input_data = {
            "columns": ["X"],
            "index": index,
            "data": data
        }
        
        # Format request data according to MLflow's expected schema
        request_data = {
            "input_data": input_data,
            "params": {}
        }

        log_message(f"Sending request to endpoint: {endpoint_info['endpoint_name']}")
        log_message(f"Input data shape: {len(data)} rows x {len(data[0]) if data else 0} columns")
        log_message(f"Request data: {json.dumps(request_data, indent=2)}", level="DEBUG")

        # Measure time for the inference
        start_time = time.time()
        
        # Prepare the request
        body = json.dumps(request_data).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {endpoint_info['key']}"
        }
        
        # Create SSL context that can handle self-signed certificates
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Create and send the request
        req = urllib.request.Request(endpoint_info['scoring_uri'], body, headers)
        try:
            response = urllib.request.urlopen(req, context=ssl_context)
            result = json.loads(response.read())
        except HTTPError as error:
            error_content = error.read().decode('utf8', 'ignore')
            log_error(f"Request failed with status code: {error.code}")
            # Don't log headers as they might contain sensitive information
            log_error(f"Error content: {error_content}")
            raise RuntimeError(f"HTTP request failed with status code {error.code}: {error_content}")
        except json.JSONDecodeError as error:
            log_error(f"Failed to parse response as JSON", error)
            raise RuntimeError(f"Failed to parse response as JSON: {str(error)}")
        
        # Calculate execution time
        exec_time = time.time() - start_time
        log_result("Execution Time", f"{exec_time:.2f}s")
        
        return {
            "result": result,
            "execution_time_s": exec_time,
            "input_count": len(inputs)
        }
    
    except Exception as e:
        log_error(f"Error during inference", e)
        raise e

def save_results(results: List[Dict[str, Any]], output_file: str) -> bool:
    """Helper function to save results to a file.
    
    Args:
        results: List of results to save
        output_file: Path to the output file
        
    Returns:
        bool: True if the save was successful, False otherwise
    """
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        log_message(f"Results saved to: {output_file}")
        return True
    except Exception as e:
        log_error(f"Error saving results to file", e)
        return False

def main():
    """Main function."""
    # Set up logging session
    session_name = "lr_client"

    # Create output directory if it doesn't exist
    OUTPUT_DIR = "./outputs"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    logger = setup_session_logger(session_name, OUTPUT_DIR)
    log_step("Initialization", "Starting Linear Regression client")
    
    # Parse arguments
    args = parse_args()
    
    # Determine inputs from arguments
    inputs = []
    
    try:
        if args.inputs:
            # Parse inputs from command line argument
            inputs = parse_inputs(args.inputs)
            log_message(f"Parsed {len(inputs)} inputs from command line")
        elif args.inputs_file:
            # Read inputs from file
            inputs = read_inputs_from_file(args.inputs_file)
            log_message(f"Read {len(inputs)} inputs from file: {args.inputs_file}")
        else:
            log_error("No inputs provided. Use --inputs or --inputs_file")
            sys.exit(1)
    except ValueError as e:
        log_error(f"Input parsing error: {e}")
        sys.exit(1)
    
    if not inputs:
        log_error("No valid inputs found.")
        sys.exit(1)
    
    log_message(f"Processing {len(inputs)} total inputs")
    
    # Initialize ML client
    log_step("ML Client Initialization", "Connecting to Azure ML")
    ml_client = get_ml_client()
    if ml_client is None:
        log_error("Failed to initialize Azure ML client. Check your credentials and environment variables.")
        sys.exit(1)
    
    # Get endpoint information
    endpoint_info = get_online_endpoint_info(ml_client)
    log_message(f"Successfully connected to endpoint: {endpoint_info['endpoint_name']}")
    
    # Set up results storage
    results = []
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    output_file = os.path.join(OUTPUT_DIR, f"lr_results_{timestamp}.json")

    log_message(f"Processing the data with batch size: {args.batch_size}")

    # Process inputs in batches
    if args.batch_size > 0:
        log_step("Batch Processing", f"Batch size: {args.batch_size}")
        
        for i in range(0, len(inputs), args.batch_size):
            batch_inputs = inputs[i:i+args.batch_size]
            batch_num = i // args.batch_size + 1
            total_batches = (len(inputs) + args.batch_size - 1) // args.batch_size
            
            log_message(f"Processing batch {batch_num} of {total_batches} (size: {len(batch_inputs)})")
            
            try:
                result = run_inference(
                    endpoint_info=endpoint_info,
                    inputs=batch_inputs
                )
                results.append(result)
                log_result("Batch Processing", "Success", f"Batch {batch_num}, Execution time: {result['execution_time_s']:.2f}s")
                
                # Save intermediate results
                save_results(results, output_file)
            except Exception as e:
                log_error(f"Error processing batch {batch_num}", e)
    else:
        # Process all inputs at once
        log_step("Single Processing", f"Processing all {len(inputs)} inputs")
        
        try:
            result = run_inference(
                endpoint_info=endpoint_info,
                inputs=inputs
            )
            results.append(result)
            log_result("Processing", "Success", f"Execution time: {result['execution_time_s']:.2f}s")
            
            # Save results
            save_results(results, output_file)
        except Exception as e:
            log_error(f"Error processing inputs", e)

    # Print final results summary
    log_step("Completion", "All processing complete")
    log_result("Total Batches Processed", len(results))
    log_result("Total Input Values", sum(r.get('input_count', 0) for r in results))
    log_result("Output File", output_file)
    
    # Finalize log session
    log_file_path = finalize_session_log(session_name)
    print(f"Log saved to: {log_file_path}")

if __name__ == "__main__":
    main()
```

## io_utils.py
```
import os
import json
import glob
import csv
import logging
from datetime import datetime
from typing import Optional

# Global logger configuration
_session_logger = None
_log_file_path = None

def setup_session_logger(session_name: str = "analysis", output_dir: str = "./output"):
    """
    Set up a global logger for analysis operations with timestamped log files.
    
    Creates a logger that outputs to both console and a timestamped file.
    The log file follows the format: {session_name}_{timestamp}.log
    
    Args:
        session_name: Name prefix for the log file (default: "analysis")
        output_dir: Directory to store log files (default: "./logs")
    
    Returns:
        logging.Logger: Configured logger instance
    """
    global _session_logger, _log_file_path
    
    if _session_logger is not None:
        return _session_logger
    
    # Create timestamp for log file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_file_path = os.path.join(output_dir, f"{session_name}_{timestamp}.log")
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Create logger
    _session_logger = logging.getLogger(f"{session_name}_session")
    _session_logger.setLevel(logging.DEBUG)
    
    # Clear any existing handlers
    _session_logger.handlers.clear()
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    console_formatter = logging.Formatter('%(message)s')
    
    # Console handler (for existing behavior)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    _session_logger.addHandler(console_handler)
    
    # File handler (new persistent logging)
    file_handler = logging.FileHandler(_log_file_path, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    _session_logger.addHandler(file_handler)
    
    # Log the initialization
    _session_logger.info("=" * 60)
    _session_logger.info(f"{session_name.upper()} SESSION STARTED")
    _session_logger.info(f"Log file: {_log_file_path}")
    _session_logger.info("=" * 60)
    
    return _session_logger


def log_message(message: str, level: str = "INFO", session_name: str = "analysis"):
    """
    Log a message to both console and file with appropriate formatting.
    
    Args:
        message: Message to log
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        session_name: Session name for the logger
    """
    logger = setup_session_logger(session_name)
    
    # Map string levels to logging levels
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO, 
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR
    }
    
    log_level = level_map.get(level.upper(), logging.INFO)
    logger.log(log_level, message)


def log_step(step_name: str, details: str = "", session_name: str = "analysis"):
    """
    Log a major workflow step with consistent formatting.
    
    Args:
        step_name: Name of the step (e.g., "Data Processing")
        details: Additional details about the step
        session_name: Session name for the logger
    """
    logger = setup_session_logger(session_name)
    
    separator = "-" * 40
    logger.info(separator)
    if details:
        logger.info(f"STEP: {step_name} - {details}")
    else:
        logger.info(f"STEP: {step_name}")
    logger.info(separator)


def log_result(result_name: str, value, details: str = "", session_name: str = "analysis"):
    """
    Log an important result or calculation outcome.
    
    Args:
        result_name: Name of the result
        value: The result value
        details: Additional context
        session_name: Session name for the logger
    """
    logger = setup_session_logger(session_name)
    
    if details:
        logger.info(f"RESULT: {result_name} = {value} ({details})")
    else:
        logger.info(f"RESULT: {result_name} = {value}")


def log_error(error_message: str, exception: Optional[Exception] = None, session_name: str = "analysis"):
    """
    Log an error with full context.
    
    Args:
        error_message: Description of the error
        exception: Optional exception object for stack trace
        session_name: Session name for the logger
    """
    logger = setup_session_logger(session_name)
    
    logger.error(f"ERROR: {error_message}")
    if exception:
        logger.error(f"Exception details: {str(exception)}")


def finalize_session_log(session_name: str = "analysis"):
    """
    Finalize the analysis log session.
    
    Args:
        session_name: Session name for the logger
    
    Returns:
        str: Path to the log file that was created
    """
    global _log_file_path
    logger = setup_session_logger(session_name)
    
    logger.info("=" * 60)
    logger.info(f"{session_name.upper()} SESSION COMPLETED")
    logger.info(f"Log saved to: {_log_file_path}")
    logger.info("=" * 60)    
    return _log_file_path
