# Connecting the Scigantic MCP tool

`SciganticCatalog` reaches the Scigantic catalog through an **MCP tool**: a connection to the remote
Scigantic Model Context Protocol server, registered in the Microsoft Foundry project that backs your
Discovery workspace.

Discovery Studio does not yet expose MCP tool registration, so this is done in Foundry. You register
the tool **once per project**, then attach it to each agent that needs it. The steps mirror the
[Wiley Nexus walkthrough](../../wiley-nexus/mcp/README.md), which has a screenshot of each dialog;
only the connection values differ.

**Before you start:** create the agent in Discovery Studio from `agent.yaml` and **save** it. The
*Open in Foundry* button appears only on a saved agent. There is no API key to obtain.

## 1. Open the agent in Foundry

In Discovery Studio, open the agent under **Resources, then Agents**, and select **Open in Foundry**.

## 2. Go to Tools and start a new connection

In Foundry's left nav, select **Tools**, open the **Tools** tab, and select **Connect a tool**. If
`scigantic` is already registered in this project, skip to step 5.

## 3. Choose a custom MCP tool

In the **Select a tool** dialog, switch to the **Custom** tab, choose **Model Context Protocol
(MCP)**, and select **Create**.

## 4. Enter the Scigantic connection details

| Field | Value |
| --- | --- |
| **Name** | `scigantic` |
| **Remote MCP Server endpoint** | `https://api.scigantic.com/mcp` |
| **Authentication** | None. The server is anonymous and read-only. |

If the dialog requires a credential before it will connect, choose **Key-based** and enter a
header such as `X-Scigantic-Client` with any value. The server ignores request headers it does not
use, including `Authorization`.

Select **Connect**.

## 5. Attach the tool to your agent

Open the `scigantic` tool, select **Use in an agent**, and pick `SciganticCatalog` (use **View all
agents** if it is not under **Recent agents**).

## 6. Configure the tool and set approval to auto-approve

In the agent, find `scigantic` in the **Tools** list and open its configuration:

| Setting | What to enter |
| --- | --- |
| **Allowed scigantic tools** | Leave empty, or allow only the catalog tools listed below. |
| **Approval setting for tools in this MCP server for this agent** | **`Always auto-approve all tools`** |

Approval must be set to auto-approve. The default asks for confirmation before every tool call,
and in an autonomous task run there is nobody to confirm, so the agent stalls.

Select **Apply**.

## 7. Save the agent

Select **Save** (or **Publish**). Back in Discovery Studio the agent lists `scigantic` among its
tools, alongside the resource-handling tools Discovery injects into every agent.

## The Scigantic tools

| Tool | What it does |
| --- | --- |
| `search_archives` | Natural-language search over the catalog; returns ranked archives with trust signals |
| `get_archive` | Full metadata for one archive |
| `get_schema_card` | The archive's schema card: format, columns, sample rows, sidecar docs, caveats, starter cell |
| `get_data_access` | Storage location and loader snippets for the user's own environment |
| `list_archive_files` | A sample of the archive's files or objects |
| `get_sample_notebook` | Source of a worked starter notebook, when one exists |
| `lookup_paper` | An arXiv paper and the catalog archives linked to it |
| `surechembl_compound`, `surechembl_patents_for_compound`, `surechembl_patent`, `surechembl_patent_chemistry`, `surechembl_search_patents`, `surechembl_structure_search` | SureChEMBL patent chemistry |
| `search`, `fetch` | Reduced aliases kept for ChatGPT connectors; the agent ignores them |
| `list_compute_tiers` | Scigantic's own hosted notebook tiers; not applicable in Discovery, the agent ignores it |

Every tool is read-only and declares `readOnlyHint`. For the server's source, a stdio variant for
clients that cannot use HTTP, and the response shapes, see
<https://github.com/Scigantic/scigantic-mcp>.

## Notes

- **Register once, attach many.** The tool is a project-level resource. Adding it to a second
  agent is just steps 5 and 6.
- **Verify the connection** by asking the agent for a dataset on any topic. A working connection
  answers with archive ids and `https://scigantic.com/archive/<id>` links; a broken one says the
  catalog returned nothing.
