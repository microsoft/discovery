# MCP in Discovery
Using external MCP servers is entirely possible inside of Discovery via Tools. This example shows one potential solution.

The goal of this repo is to demonstrate how to wrap an MCP client in a Docker container. 
Using `docker run`, functions inside this container can be called, so that an MCP server external to Discovery
can be utilized by a Discovery tool. The goal is to make it so that the tool can run on any Discovery server, without needing make changes to the tool template, other than the URL and perhaps additional authentication information.

This current implementation is extremely general. New tools/functions can be added to an MCP server and there is no need for any changes in Discovery. Server side changes can be tested in real time.

For reference, the example MCP server used here is based on this github repository: https://github.com/panz2018/fastapi_mcp_sse

## Example Usage

### To use on Discovery
Running the commands below will build the mcp client docker container. Currently, the tool, agent and workflow files need to be manually added to the Discovery resource group via the portal. Once these files are uploaded, create a project and investigation.

```
az acr login --name {your Azure Container Registry resource name}
cd tool-artifacts/example_client
az acr build -r {your Azure Container Registry resource name} -t mcp_client:latest .
cd ../..
```

### Start server on an azure vm in the same RG as Discovery
```
docker compose build
docker compose run server
```
Note: Inside the `client` container, the url of the `server` container is `http://server:80`.

### Example local commands for testing before running on Discovery
List tools available on MCP server:
`docker compose run client python main.py --server http://server:80 list-tools`  
Result from example server:
```
[
  {
    "name": "add",
    "title": null,
    "description": "Add two numbers",
    "inputSchema": {
      "properties": {
        "a": {
          "title": "A",
          "type": "integer"
        },
        "b": {
          "title": "B",
          "type": "integer"
        }
      },
      "required": [
        "a",
        "b"
      ],
      "title": "addArguments",
      "type": "object"
    },
    "outputSchema": {
      "properties": {
        "result": {
          "title": "Result",
          "type": "integer"
        }
      },
      "required": [
        "result"
      ],
      "title": "addOutput",
      "type": "object"
    },
    "annotations": null,
    "meta": null
  }
]
```

List resources available on MCP server (no `resources` on example server):
`docker compose run client python main.py --server http://server:80 list-resources`   
List resource templates available on MCP server:
`docker compose run client python main.py --server http://server:80 list-resource-templates`
Result from example server:
```
[
  {
    "name": "get_greeting",
    "title": null,
    "uriTemplate": "greeting://{name}",
    "description": "Get a personalized greeting",
    "mimeType": null,
    "annotations": null,
    "meta": null
  }
]
```

List prompts available on MCP server (no prompts available on MCP server):  
`docker compose run client python main.py --server http://server:80 list-prompts`  
Run tool on MCP server:
`docker compose run client python main.py --server http://server:80 call-tool add --args '{"a": 1, "b": 2}'`
Result from example server:
```
{
  "meta": null,
  "content": [
    {
      "type": "text",
      "text": "3",
      "annotations": null,
      "meta": null
    }
  ],
  "structuredContent": {
    "result": 3
  },
  "isError": false
}
```

Run resource template on MCP server:
`docker compose run client python main.py --server http://server:80 read-resource greeting://MCPUser`
Result from example server:
```
{
  "meta": null,
  "contents": [
    {
      "uri": {
        "_url": "greeting://MCPUser"
      },
      "mimeType": "text/plain",
      "meta": null,
      "text": "Hello, MCPUser!"
    }
  ]
}
``` 
