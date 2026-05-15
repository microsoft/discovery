# MCP Client Setup

## Configuration for MCP Clients

### Claude Desktop

Add this to your Claude Desktop `mcp.json` configuration file:

```json
{
  "mcpServers": {
    "s3": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/s3-mcp",
        "python",
        "src/s3_mcp.py"
      ],
      "env": {
        "AWS_ACCESS_KEY_ID": "<your_aws_access_key_id>",
        "AWS_SECRET_ACCESS_KEY": "<your_aws_secret_access_key>",
        "AWS_SESSION_TOKEN": "<your_aws_session_token>",
        "AWS_DEFAULT_REGION": "<your_aws_default_region>"
      }
    }
  }
}
```

### Environment Variables

Replace these values in the `env` section:

- `AWS_ACCESS_KEY_ID`: Your AWS Access Key ID
- `AWS_SECRET_ACCESS_KEY`: Your AWS Secret Access Key
- `AWS_SESSION_TOKEN`: Your AWS Session Token (optional, if using temporary credentials)
- `AWS_DEFAULT_REGION`: Your default AWS region (optional)

### Path Configuration

Update the `--directory` path to match your installation:

```json
"args": [
  "run",
  "--directory",
  "/home/user/s3-mcp",
  "python",
  "src/s3_mcp.py"
]
```

### Using Configuration Template

You can copy the provided configuration template:

```bash
cp config/mcp.json ~/.config/claude-desktop/mcp.json
# Edit the file with your specific paths and credentials
```

## Alternative Startup Methods

### Using Startup Script

For better error handling and logging, you can use the startup script:

```json
{
  "mcpServers": {
    "s3": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/s3-mcp",
        "python",
        "scripts/start_server.py"
      ],
      "env": {
        "AWS_ACCESS_KEY_ID": "<your_aws_access_key_id>",
        "AWS_SECRET_ACCESS_KEY": "<your_aws_secret_access_key>",
        "AWS_SESSION_TOKEN": "<your_aws_session_token>",
        "AWS_DEFAULT_REGION": "<your_aws_default_region>"
      }
    }
  }
}
```

### Using Environment File

Instead of setting environment variables in the MCP config, you can create a `.env` file in the project root:

```bash
# Copy the example configuration
cp config/.env.example .env

# Edit .env with your settings
AWS_ACCESS_KEY_ID="YOUR_AWS_ACCESS_KEY_ID"
AWS_SECRET_ACCESS_KEY="YOUR_AWS_SECRET_ACCESS_KEY"
# AWS_SESSION_TOKEN="YOUR_AWS_SESSION_TOKEN"
# AWS_DEFAULT_REGION="us-east-1"
DEBUG="false"
```

Then use a simpler MCP configuration:

```json
{
  "mcpServers": {
    "s3": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/s3-mcp",
        "python",
        "scripts/start_server.py"
      ]
    }
  }
}
```

## Testing

After configuration, restart your MCP client and test with:

`Show me all the S3 buckets I have access to.`

The server should respond with your S3 bucket data.

## Troubleshooting

### Common Issues

**Server not starting:**
- Check that the path in `--directory` is correct
- Verify that `uv` is installed and accessible
- Run the test script: `uv run python scripts/test_server.py`

**Authentication errors:**
- Verify your AWS credentials are correct and have the necessary permissions
- Check that your default region is correctly configured

**Permission denied:**
- Verify your AWS user has sufficient permissions for the S3 operations

### Debug Mode

Enable debug logging by adding to your environment:

```json
"env": {
  "AWS_ACCESS_KEY_ID": "<your_aws_access_key_id>",
  "AWS_SECRET_ACCESS_KEY": "<your_aws_secret_access_key>",
  "DEBUG": "true"
}
```

### Manual Testing

You can test the server manually before configuring your MCP client:

```bash
# Navigate to the project directory
cd /path/to/s3-mcp

# Run the test suite
uv run python scripts/test_server.py

# Start the server manually
uv run python scripts/start_server.py
```
