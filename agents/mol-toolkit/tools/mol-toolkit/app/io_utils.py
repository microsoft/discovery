import os
import json
import glob
import csv
import logging
import sys
from datetime import datetime
from typing import Optional

# Global logger configuration
_session_logger = None
_log_file_path = None


def setup_session_logger(session_name: str = "analysis", output_dir: str = None):
    """
    Set up a global logger for analysis operations with timestamped log files.

    Creates a logger that outputs to both console and a timestamped file.
    The log file follows the format: {session_name}_{timestamp}.log

    Args:
        session_name: Name prefix for the log file (default: "analysis")
        output_dir: Directory to store log files. If not provided, logs to console only.

    Returns:
        logging.Logger: Configured logger instance
    """
    global _session_logger, _log_file_path

    if _session_logger is not None:
        return _session_logger

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

    if output_dir:
        # Create timestamp for log file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        _log_file_path = os.path.join(output_dir, f"{session_name}_{timestamp}.log")

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # File handler (persistent logging)
        file_handler = logging.FileHandler(_log_file_path, mode='w', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        _session_logger.addHandler(file_handler)

    # Log the initialization
    separator = "=" * 60
    start_msg = f"{session_name.upper()} SESSION STARTED"

    # Print to stdout for immediate visibility
    print(separator, flush=True)
    print(start_msg, flush=True)
    if _log_file_path:
        print(f"Log file: {_log_file_path}", flush=True)
    print(separator, flush=True)

    # Also log through the logging system
    _session_logger.info(separator)
    _session_logger.info(start_msg)
    if _log_file_path:
        _session_logger.info(f"Log file: {_log_file_path}")
    _session_logger.info(separator)

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
    
    # Always print to stdout for immediate visibility
    print(f"{level.upper()}: {message}", flush=True)
    
    # Also log through the logging system for file output
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
    
    # Print to stdout for immediate visibility
    print(separator, flush=True)
    if details:
        step_message = f"STEP: {step_name} - {details}"
    else:
        step_message = f"STEP: {step_name}"
    print(step_message, flush=True)
    print(separator, flush=True)
    
    # Also log through the logging system
    logger.info(separator)
    logger.info(step_message)
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
    
    # Format the result message
    if details:
        result_message = f"RESULT: {result_name} = {value} ({details})"
    else:
        result_message = f"RESULT: {result_name} = {value}"
    
    # Print to stdout for immediate visibility
    print(result_message, flush=True)
    
    # Also log through the logging system
    logger.info(result_message)


def log_error(error_message: str, exception: Optional[Exception] = None, session_name: str = "analysis"):
    """
    Log an error with full context.
    
    Args:
        error_message: Description of the error
        exception: Optional exception object for stack trace
        session_name: Session name for the logger
    """
    logger = setup_session_logger(session_name)
    
    error_msg = f"ERROR: {error_message}"
    
    # Print to stdout for immediate visibility
    print(error_msg, flush=True)
    if exception:
        exception_msg = f"Exception details: {str(exception)}"
        print(exception_msg, flush=True)
    
    # Also log through the logging system
    logger.error(error_msg)
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
    
    separator = "=" * 60
    completion_msg = f"{session_name.upper()} SESSION COMPLETED"
    file_msg = f"Log saved to: {_log_file_path}"
    
    # Print to stdout for immediate visibility
    print(separator, flush=True)
    print(completion_msg, flush=True)
    print(file_msg, flush=True)
    print(separator, flush=True)
    
    # Also log through the logging system
    logger.info(separator)
    logger.info(completion_msg)
    logger.info(file_msg)
    logger.info(separator)
    
    return _log_file_path


def read_smiles_from_file(file_path):
    """
    Read SMILES strings from a file
    Parameters:
        file_path (str): Path to the file containing SMILES strings
    Returns:
        list: List of SMILES strings
    """
    log_message(f"Reading SMILES from file: {file_path}")
    # Print out the list of files in the parent directory of the file_path
    parent_dir = os.path.dirname(file_path)
    if parent_dir and os.path.isdir(parent_dir):
        files = os.listdir(parent_dir)
        log_message(f"Files in '{parent_dir}': {files}")

    smiles_list = []
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == '.smi':
            with open(file_path, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    # Check if first line looks like a header
                    if line_num == 1:
                        first_field = line.split()[0].lower()
                        if first_field in ('smiles', 'molecule', 'smi', 'canonical_smiles', 'smiles_string'):
                            print(f"TRACE: Detected header in .smi file, skipping: {line}")
                            continue
                    # Check if this looks like CSV format (contains commas)
                    if ',' in line and line_num == 1 and ('smiles' in line.lower() or 'name' in line.lower()):
                        # Skip header row in CSV-like format
                        print(f"TRACE: Detected CSV header in .smi file, skipping: {line}")
                        continue
                    elif ',' in line:
                        # CSV-like format: take first part before comma
                        smiles = line.split(',')[0].strip()
                        if smiles:
                            smiles_list.append(smiles)
                    else:
                        # Standard SMI format: take first part before space/tab
                        parts = line.split()
                        if parts:
                            smiles_list.append(parts[0])
        elif ext == '.csv':
            with open(file_path, 'r', newline='') as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for row in reader:
                    if row and row[0].strip():
                        smiles_list.append(row[0].strip())
        else:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        smiles_list.append(line)
        log_message(f"Found {len(smiles_list)} SMILES strings")
        return smiles_list
    except Exception as e:
        log_error(f"Failed to read SMILES from {file_path}: {e}")
        return []


def find_smiles_files(input_dir):
    """
    Find all files that potentially contain SMILES strings in the input directory
    Parameters:
        input_dir (str): Path to the input directory
    Returns:
        list: List of paths to files that might contain SMILES
    """
    log_message(f"Searching for SMILES files in {input_dir}")
    extensions = ['.smi', '.csv', '.txt', '.dat']
    files = []
    for ext in extensions:
        pattern = os.path.join(input_dir, f"*{ext}")
        files.extend(glob.glob(pattern))
    log_message(f"Found {len(files)} potential SMILES files: {files}")
    return files


def find_files(input_dir, extensions):
    """
    Find all files with specified extensions in the input directory
    Parameters:
        input_dir (str): Path to the input directory
        extensions (list): List of file extensions to search for
    Returns:
        list: List of paths to files with specified extensions
    """
    log_message(f"Searching for files in {input_dir} with extensions {extensions}")
    files = []
    for ext in extensions:
        pattern = os.path.join(input_dir, f"*{ext}")
        files.extend(glob.glob(pattern))
    log_message(f"Found {len(files)} files: {files}")
    return files


def write_results_to_json(results, output_file):
    """
    Write results to a JSON file
    Parameters:
        results (list): List of dictionaries containing results
        output_file (str): Path to the output JSON file
    """
    log_message(f"Writing results to JSON file: {output_file}")
    try:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        log_message(f"Successfully wrote results to {output_file}")
    except Exception as e:
        log_error(f"Failed to write results to {output_file}: {e}")
