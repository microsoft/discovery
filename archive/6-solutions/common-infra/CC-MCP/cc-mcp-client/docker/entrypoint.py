import os
import sys
import json
import requests

MCP_URL = os.getenv("MCP_URL", "http://10.16.16.16:8080/mcp")

def initialize_session():
    payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "python-client", "version": "1.0"}
        },
        "id": 1
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    response = requests.post(MCP_URL, headers=headers, json=payload)
    session_id = response.headers.get("mcp-session-id")
    if not session_id:
        raise RuntimeError("Failed to initialize MCP session.")
    return session_id

def send_initialized(session_id):
    payload = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "mcp-session-id": session_id}
    requests.post(MCP_URL, headers=headers, json=payload)

def call_mcp_tool(session_id, tool_name, arguments):
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
        "id": 2
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "mcp-session-id": session_id}
    print("[DEBUG] Payload:", json.dumps(payload, indent=2))
    response = requests.post(MCP_URL, headers=headers, json=payload)
    print(response.text)

# Explicit functions for each action
def submit_job(params):
    args = []
    if params.get("partition"):
        args.append(f"--partition={params['partition']}")
    if params.get("script"):
        args.append(params["script"])
    return {"args": args}

def check_queue(params):
    return {"args": [f"--format={params.get('format', '%t,%j,%u,%T,%M,%N')}"]}

def cluster_info(params):
    return {"args": [f"--Format={params.get('format', 'NodeList,CPUs,Memory,State')}"]}

def job_accounting(params):
    return {
        "args": [
            f"--start={params.get('start', 'now-1day')}",
            f"--end={params.get('end', 'now')}",
            f"--format={params.get('format', 'JobID,User,State,Elapsed,TotalCPU,NodeList')}"
        ]
    }

def systemctl_status(params):
    return {
        "hosts": params.get("hosts", "").split(",") if params.get("hosts") else [],
        "args": ["status", params.get("service", "")]
    }

def journalctl_logs(params):
    return {
        "hosts": params.get("hosts", "").split(",") if params.get("hosts") else [],
        "args": [arg for arg in ["-u", params.get("unit", ""), "-n", str(params.get("lines", 10))] if arg.strip()]
    }

def file_head(params):
    return {"path": params.get("path", ""), "length": params.get("length", 10)}

def file_tail(params):
    return {"path": params.get("path", ""), "length": params.get("length", 10)}

def file_search(params):
    return {"path": params.get("path", ""), "pattern": params.get("pattern", "")}

def create_file(params):
    return {"path": params.get("path", ""), "content": params.get("content", "")}

def get_infiniband_pkeys(params):
    return {"hosts": params.get("hosts", "").split(",") if params.get("hosts") else []}

def get_physical_hostnames(params):
    return {"hosts": params.get("hosts", "").split(",") if params.get("hosts") else []}

# Dispatcher
ACTION_MAP = {
    "submit-job": ("sbatch", submit_job),
    "check-queue": ("squeue", check_queue),
    "cluster-info": ("sinfo", cluster_info),
    "job-accounting": ("sacct", job_accounting),
    "systemctl-status": ("systemctl", systemctl_status),
    "journalctl-logs": ("journalctl", journalctl_logs),
    "file-head": ("head_file", file_head),
    "file-tail": ("tail_file", file_tail),
    "file-search": ("search_file", file_search),
    "create-file": ("create_file", create_file),
    "get-infiniband-pkeys": ("get_infiniband_pkeys", get_infiniband_pkeys),
    "get-physical-hostnames": ("get_physical_hostnames", get_physical_hostnames)
}

if __name__ == "__main__":
    for arg in sys.argv:
        print(arg)
    if len(sys.argv) < 2:
        print("Usage: python entrypoint.py <action> [<params_json>]")
        sys.exit(1)

    action = sys.argv[1]
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    if action not in ACTION_MAP:
        print(f"Unsupported action: {action}")
        sys.exit(1)

    tool_name, func = ACTION_MAP[action]
    arguments = func(params)

    session_id = initialize_session()
    send_initialized(session_id)
    call_mcp_tool(session_id, tool_name, arguments)