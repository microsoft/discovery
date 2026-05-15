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