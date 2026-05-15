# S3 MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

A Model Context Protocol (MCP) server for AWS S3 integration using FastMCP and boto3. This server provides access to S3 functionality through MCP-compatible tools.

## Features

### Bucket Management
- `list_buckets` - Lists all S3 buckets in the AWS account.

### Object Management
- `put_object` - Puts an object into an S3 bucket.
- `get_object` - Gets an object from an S3 bucket.
- `delete_object` - Deletes an object from an S3 bucket.
- `list_objects_v2` - Lists objects in an S3 bucket.
- `head_object` - Retrieves metadata from an object without returning the object itself.
- `upload_file` - Uploads a file to an S3 object.
- `download_file` - Downloads an object from an S3 bucket to a file.
- `copy_object` - Copies an object from one S3 location to another.
- `delete_objects` - Deletes multiple objects from an S3 bucket.

## Installation

### Prerequisites

- Python 3.10 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- AWS account with S3 access configured

### Quick Start

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/konstantinasm/s3-mcp.git
    cd s3-mcp
    ```

2.  **Install dependencies:**
    ```bash
    uv sync
    ```

3.  **Configure environment variables:**
    ```bash
    cp config/.env.example .env
    # Edit .env with your AWS credentials and S3 bucket details
    ```

4.  **Test the installation:**
    ```bash
    uv run python scripts/test_server.py
    ```

## Configuration

### Required Environment Variables

- `AWS_ACCESS_KEY_ID` - Your AWS Access Key ID
- `AWS_SECRET_ACCESS_KEY` - Your AWS Secret Access Key

## Usage

### Running the Server

**With startup script (recommended):**
```bash
uv run python scripts/start_server.py
```

**Direct execution:**
```bash
uv run python src/s3_mcp.py
```

### Testing

**Run test suite:**
```bash
uv run python scripts/test_server.py
```

### Example Tool Calls

**List all S3 buckets:**
```python
list_buckets()
```

## MCP Integration

This server is designed to work with MCP-compatible clients. See [MCP_SETUP.md](MCP_SETUP.md) for detailed integration instructions.

## Docker Support

### Using Docker Compose

1.  **Configure environment:**
    ```bash
    cp config/.env.example .env
    # Edit .env with your settings
    ```

2.  **Run with Docker Compose:**
    ```bash
    docker compose up -d
    ```

### Building Docker Image

```bash
docker build -t s3-mcp-server .
```

## Development

### Project Structure

```
s3-mcp/
├── src/
│   └── s3_mcp.py    # Main server implementation
├── scripts/
│   ├── start_server.py         # Startup script with validation
│   └── test_server.py          # Test script
├── config/
│   ├── .env.example           # Environment configuration template
│   └── mcp.json               # MCP client configuration example
├── pyproject.toml             # Python project configuration
├── requirements.txt           # Dependencies
├── Dockerfile                 # Docker configuration
├── docker-compose.yml         # Docker Compose setup
├── README.md                  # This file
├── MCP_SETUP.md              # MCP integration guide
└── LICENSE                   # MIT license
```

### Contributing

Contributions are welcome!
If you have ideas, improvements, or bug fixes — feel free to submit a pull request.

#### How to Contribute:

1. Fork the repository.
2. Create a new branch for your changes.
3. Make your changes with clear, clean commits.
4. Open a pull request with a clear description of what you’ve done.

Please follow existing code style and keep commits focused.
Questions or suggestions? Open an issue.

### Running Tests

```bash
uv run python scripts/test_server.py
```

## Troubleshooting

### Common Issues

**Permission Denied:**
- Verify AWS credentials have sufficient S3 permissions.
- Check if read-only mode is enabled.

**Tool Not Found:**
- Ensure all dependencies are installed: `uv sync`.
- Verify Python version compatibility (3.10+).

### Debug Mode

Set environment variable for detailed logging:
```bash
export DEBUG=1
uv run python scripts/start_server.py
```

## Dependencies

- [FastMCP](https://github.com/jlowin/fastmcp) - MCP server framework
- [boto3](https://aws.amazon.com/sdk-for-python/) - AWS SDK for Python
- [python-dotenv](https://pypi.org/project/python-dotenv/) - Loads environment variables from a .env file

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- AWS S3 for cloud storage
- [Model Context Protocol](https://modelcontextprotocol.io/) for the integration standard
- [FastMCP](https://github.com/jlowin/fastmcp) for the server framework

