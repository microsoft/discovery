#!/usr/bin/env python3
"""
Test script for S3 MCP Server

This script validates the server configuration and tests basic functionality
to ensure everything is working correctly.

"""

import os
import sys
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def setup_logging() -> None:
    """Setup logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )


def test_import() -> bool:
    """Test if the server module can be imported.
    
    Returns:
        bool: True if import successful
    """
    try:
        print(" Testing module import...")
        from s3_mcp import get_s3_client
        print("✅ Module import successful")
        return True
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        print("Please install dependencies: uv sync")
        return False
    except Exception as e:
        print(f"❌ Unexpected import error: {e}")
        return False


def test_environment() -> bool:
    """Test environment configuration.
    
    Returns:
        bool: True if environment is properly configured
    """
    print("\n Testing environment configuration...")
    
    # Check required variables
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    
    if not access_key:
        print("❌ AWS_ACCESS_KEY_ID not configured")
        return False
    print(f"✅ AWS_ACCESS_KEY_ID is configured")

    if not secret_key:
        print("❌ AWS_SECRET_ACCESS_KEY not configured")
        return False
    print(f"✅ AWS_SECRET_ACCESS_KEY is configured")
    
    return True


def test_connection() -> bool:
    """Test basic connection to AWS S3.
    
    Returns:
        bool: True if connection successful
    """
    print("\n Testing AWS S3 connection...")
    
    try:
        from s3_mcp import get_s3_client
        
        # Test getting client. The function itself performs a check.
        client = get_s3_client()
        
        print(f"✅ Connected to AWS S3 successfully")
        return True
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False


def test_basic_operations() -> bool:
    """Test basic read operations.
    
    Returns:
        bool: True if operations successful
    """
    print("\n Testing basic operations...")
    
    try:
        from s3_mcp import _list_buckets_logic
        
        # Test bucket listing
        print("  - Testing bucket retrieval...")
        buckets_data = _list_buckets_logic()

        if 'Buckets' in buckets_data:
            print(f"    ✅ Retrieved {len(buckets_data['Buckets'])} bucket(s)")
        else:
            print("    ❌ Failed to retrieve buckets or response format is incorrect")
            return False
        
        print("✅ Basic operations successful")
        return True
        
    except Exception as e:
        print(f"❌ Basic operations failed: {e}")
        return False


def show_summary(tests_passed: int, total_tests: int) -> None:
    """Show test summary.
    
    Args:
        tests_passed: Number of tests that passed
        total_tests: Total number of tests
    """
    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)
    
    if tests_passed == total_tests:
        print(f" All {total_tests} tests passed!")
        print("✅ The S3 MCP Server is ready to use")
        
        print("\nNext steps:")
        print("1. Configure your MCP client (see MCP_SETUP.md)")
        print("2. Start the server: s3-mcp")
        print("3. Test with your MCP client")
        
    else:
        print(f"❌ {tests_passed}/{total_tests} tests passed")
        print("Please fix the issues above before using the server")
    
    print("=" * 50)


def main() -> None:
    """Main test function."""
    setup_logging()
    
    print(" S3 MCP Server Test Suite")
    print("=" * 50)
    
    tests = [
        ("Module Import", test_import),
        ("Environment Configuration", test_environment),
        ("AWS S3 Connection", test_connection),
        ("Basic Operations", test_basic_operations),
    ]
    
    tests_passed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                tests_passed += 1
        except KeyboardInterrupt:
            print("\n\n⏹️  Tests interrupted by user")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Unexpected error in {test_name}: {e}")
    
    show_summary(tests_passed, len(tests))
    
    # Exit with appropriate code
    if tests_passed == len(tests):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
