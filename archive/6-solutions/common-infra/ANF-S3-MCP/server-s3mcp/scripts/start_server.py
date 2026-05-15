#!/usr/bin/env python3
"""
Startup script for S3 MCP Server

This script validates the environment configuration and starts the MCP server
with proper error handling and logging.

"""

import os
import sys
import logging
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def setup_logging() -> None:
    """Setup logging configuration."""
    log_level = logging.DEBUG if os.getenv("DEBUG", "false").lower() in ("true", "1", "yes") else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )


def check_environment() -> bool:
    """Check if required environment variables are set.
    
    Returns:
        bool: True if environment is properly configured
    """
    logger = logging.getLogger(__name__)
    required_vars: List[str] = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    missing_vars: List[str] = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        print("Error: Missing required environment variables:")
        for var in missing_vars:
            print(f"  - {var}")
        print()
        print("Please set these variables in your environment or in a .env file.")
        return False
    
    return True


def show_configuration() -> None:
    """Display current configuration."""
    logger = logging.getLogger(__name__)
    
    print("\n" + "=" * 50)
    print("S3 MCP Server Configuration")
    print("=" * 50)
    
    # AWS Region
    aws_region = os.getenv('AWS_DEFAULT_REGION', 'Not specified (boto3 will use its default)')
    print(f"AWS Region: {aws_region}")
    logger.info(f"AWS Region: {aws_region}")
    
    # Debug mode
    debug_mode = os.getenv('DEBUG', 'false').lower() in ('true', '1', 'yes')
    debug_str = 'Enabled' if debug_mode else 'Disabled'
    print(f"Debug mode: {debug_str}")
    logger.info(f"Debug mode: {debug_str}")
    
    print("=" * 50)
    print()


def main() -> None:
    """Main startup function."""
    # Setup logging first
    setup_logging()
    logger = logging.getLogger(__name__)
    
    print("Starting S3 MCP Server...")
    logger.info("Starting S3 MCP Server")
    
    try:
        # Check environment configuration
        if not check_environment():
            logger.error("Environment validation failed. Aborting startup.")
            sys.exit(1)
        
        # Show configuration
        show_configuration()
        
        # Import and run the server's main function
        logger.info("Importing server module...")
        from s3_mcp import main as server_main
        
        logger.info("Starting MCP server process...")
        print("MCP server is starting. Press Ctrl+C to stop.")
        print()
        
        server_main()
        
    except ImportError as e:
        logger.error(f"Import error: {e}", exc_info=True)
        print(f"Error: Failed to import the server module: {e}")
        print("Please ensure all dependencies are installed by running: uv sync")
        sys.exit(1)
        
    except KeyboardInterrupt:
        logger.info("Server startup script interrupted by user.")
        print("\nServer startup cancelled.")
        
    except Exception as e:
        logger.error(f"An unexpected error occurred during startup: {e}", exc_info=True)
        print(f"Error: An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
