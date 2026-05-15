import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

import boto3
from botocore.client import BaseClient
from botocore.exceptions import NoCredentialsError
from dotenv import load_dotenv
load_dotenv()
from fastmcp import FastMCP

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO if os.getenv("DEBUG") else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize FastMCP
mcp = FastMCP("S3 MCP Client")

# Global S3 client
s3_client: Optional[BaseClient] = None

def get_s3_client() -> BaseClient:
    global s3_client
    if s3_client is None:
        logger.info("Initializing S3 client")
        try:
            s3_client = boto3.client("s3", verify=False)
            s3_client.list_buckets()
            logger.info("S3 client initialized successfully.")
        except NoCredentialsError:
            logger.error("AWS credentials not found.")
            raise
        except Exception as e:
            logger.error(f"Error initializing S3 client: {e}")
            raise
    return s3_client

def format_response(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)

# Logic Functions
def _list_buckets_logic() -> Dict[str, Any]:
    client = get_s3_client()
    return client.list_buckets()

def _put_object_logic(bucket: str, key: str, body: Union[str, bytes]) -> Dict[str, Any]:
    client = get_s3_client()
    params = {"Bucket": bucket, "Key": key}
    params["Body"] = body.encode("utf-8") if isinstance(body, str) else body
    return client.put_object(**params)

def _get_object_logic(bucket: str, key: str) -> Dict[str, Any]:
    client = get_s3_client()
    response = client.get_object(Bucket=bucket, Key=key)
    response["Body"] = response["Body"].read().decode("utf-8")
    return response

def _delete_object_logic(bucket: str, key: str) -> Dict[str, Any]:
    client = get_s3_client()
    return client.delete_object(Bucket=bucket, Key=key)

def _list_objects_v2_logic(bucket: str, prefix: Optional[str] = None) -> Dict[str, Any]:
    client = get_s3_client()
    params = {"Bucket": bucket}
    if prefix:
        params["Prefix"] = prefix
    return client.list_objects_v2(**params)

def _head_object_logic(bucket: str, key: str) -> Dict[str, Any]:
    client = get_s3_client()
    return client.head_object(Bucket=bucket, Key=key)

def _upload_file_logic(filename: str, bucket: str, key: str) -> None:
    client = get_s3_client()
    client.upload_file(Filename=filename, Bucket=bucket, Key=key)

def _download_file_logic(bucket: str, key: str, filename: str) -> None:
    client = get_s3_client()
    client.download_file(Bucket=bucket, Key=key, Filename=filename)

def _copy_object_logic(source_bucket: str, source_key: str, destination_bucket: str, destination_key: str) -> Dict[str, Any]:
    client = get_s3_client()
    copy_source = {"Bucket": source_bucket, "Key": source_key}
    return client.copy_object(CopySource=copy_source, Bucket=destination_bucket, Key=destination_key)

def _delete_objects_logic(bucket: str, keys: List[str]) -> Dict[str, Any]:
    client = get_s3_client()
    objects = [{"Key": key} for key in keys]
    return client.delete_objects(Bucket=bucket, Delete={"Objects": objects})

# Tool Wrappers
@mcp.tool()
def list_buckets() -> str:
    result = _list_buckets_logic()
    return format_response(result)

@mcp.tool()
def put_object(bucket: str, key: str, body: str) -> str:
    result = _put_object_logic(bucket, key, body)
    return format_response(result)

@mcp.tool()
def get_object(bucket: str, key: str) -> str:
    result = _get_object_logic(bucket, key)
    return format_response(result)

@mcp.tool()
def delete_object(bucket: str, key: str) -> str:
    result = _delete_object_logic(bucket, key)
    return format_response(result)

@mcp.tool()
def list_objects_v2(bucket: str, prefix: Optional[str] = None) -> str:
    result = _list_objects_v2_logic(bucket, prefix)
    return format_response(result)

@mcp.tool()
def head_object(bucket: str, key: str) -> str:
    result = _head_object_logic(bucket, key)
    return format_response(result)

@mcp.tool()
def upload_file(filename: str, bucket: str, key: str) -> str:
    _upload_file_logic(filename, bucket, key)
    return format_response({"status": "success", "message": f"Uploaded {filename} to {bucket}/{key}"})

@mcp.tool()
def download_file(bucket: str, key: str, filename: str) -> str:
    _download_file_logic(bucket, key, filename)
    return format_response({"status": "success", "message": f"Downloaded {key} from {bucket} to {filename}"})

@mcp.tool()
def copy_object(source_bucket: str, source_key: str, destination_bucket: str, destination_key: str) -> str:
    result = _copy_object_logic(source_bucket, source_key, destination_bucket, destination_key)
    return format_response(result)

@mcp.tool()
def delete_objects(bucket: str, keys: List[str]) -> str:
    result = _delete_objects_logic(bucket, keys)
    return format_response(result)

# Optional: Run server if needed
def main() -> None:
    logger.info("Starting MCP client server")
    try:
        mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, stateless_http=True)
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise

if __name__ == "__main__":
    main()