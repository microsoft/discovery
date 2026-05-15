import argparse
import logging
from client import (
    _list_buckets_logic,
    _put_object_logic,
    _get_object_logic,
    _delete_object_logic,
    _list_objects_v2_logic,
    _head_object_logic,
    _upload_file_logic,
    _download_file_logic,
    _copy_object_logic,
    _delete_objects_logic,
    format_response
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_action(args):
    if args.action == "list_buckets":
        result = _list_buckets_logic()
        print(format_response(result))
    elif args.action == "put_object":
        result = _put_object_logic(bucket=args.bucket, key=args.key, body=args.body)
        print(format_response(result))
    elif args.action == "get_object":
        result = _get_object_logic(bucket=args.bucket, key=args.key)
        print(format_response(result))
    elif args.action == "delete_object":
        result = _delete_object_logic(bucket=args.bucket, key=args.key)
        print(format_response(result))
    elif args.action == "list_objects_v2":
        result = _list_objects_v2_logic(bucket=args.bucket, prefix=args.prefix)
        print(format_response(result))
    elif args.action == "head_object":
        result = _head_object_logic(bucket=args.bucket, key=args.key)
        print(format_response(result))
    elif args.action == "upload_file":
        _upload_file_logic(filename=args.filename, bucket=args.bucket, key=args.key)
        print(format_response({"status": "success", "message": f"File '{args.filename}' uploaded to '{args.bucket}/{args.key}'."}))
    elif args.action == "download_file":
        _download_file_logic(bucket=args.bucket, key=args.key, filename=args.filename)
        print(format_response({"status": "success", "message": f"File '{args.key}' from bucket '{args.bucket}' downloaded to '{args.filename}'."}))
    elif args.action == "copy_object":
        result = _copy_object_logic(
            source_bucket=args.source_bucket,
            source_key=args.source_key,
            destination_bucket=args.destination_bucket,
            destination_key=args.destination_key
        )
        print(format_response(result))
    elif args.action == "delete_objects":
        keys = args.keys.split(',') if args.keys else []
        result = _delete_objects_logic(bucket=args.bucket, keys=keys)
        print(format_response(result))
    else:
        logger.error(f"Unknown action: {args.action}")

# Argument parser
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MCP Client Entrypoint")
    parser.add_argument("--action", required=True, help="Action to perform")
    parser.add_argument("--bucket", help="S3 bucket name")
    parser.add_argument("--key", help="S3 object key")
    parser.add_argument("--body", help="Object content")
    parser.add_argument("--prefix", help="Prefix for listing objects")
    parser.add_argument("--filename", help="Local file path")
    parser.add_argument("--source_bucket", help="Source bucket for copy")
    parser.add_argument("--source_key", help="Source key for copy")
    parser.add_argument("--destination_bucket", help="Destination bucket for copy")
    parser.add_argument("--destination_key", help="Destination key for copy")
    parser.add_argument("--keys", help="Comma-separated list of keys to delete")

    args = parser.parse_args()
    run_action(args)