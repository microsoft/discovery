## Overview

The Microsoft Discovery Agent Workbench is a comprehensive development and testing environment designed to assist in the development, testing, and publishing of Microsoft Discovery agents. This tool provides an integrated web-based interface that streamlines the entire agent lifecycle from creation to deployment in the Microsoft Discovery platform.

**Use this notepad to take... notes.**  

All notes are saved under 'notepad.md'.

## Key Features

- **No-Code Agent Creation**: Use your existing documentation and source code to generate Microsoft Discovery agents
- **Discovery Integration**: Seamless integration with Azure services and Microsoft Discovery platform
- **Real-time Testing**: Test agents immediately without leaving the development environment
- **Validation**: Ensure your agents meet all platform requirements before deployment

## Release notes

### Jan 30th 2026
- **Build in Azure**: Add build Docker images in Azure Container Registry instead of locally. Useful for large images or when local resources are limited.

### Jan 26th 2026
- Session manager: Create and manage multiple isolated environments, each preserving its own conversation history and context.
- Bug fixes for better handling of environment variables set for a tool.
- Detection of unsupported characters such as emojis in agent definition. Offers users to auto-fix (remove/replace).

### Jan 8th 2026
- Enable interactive debugging (both local and supercomputer) with step-through execution using VSCode tunnelling capability.
- Loosen restrictions on tool definitions.
- Trajectory extension visualizer.

### Dec 31st 2025
- Intelligent documentation retrieval with hybrid BM25 + semantic search
- Local folder support for offline documentation bundling
- Automatic documentation freshness detection and refresh on startup
- Discovery CLI auto-installation during startup
- Improved modal and button styling
- Better YAML editor layout for tool subpanels

### Dec 23rd 2025
- Add Multi-architecture support for Docker
- Add token-password pair authentication for ACR

### Dec 16th 2025
- Implement nodepool SKU validation to ensure compatibility with recommendations in tool definition (warning only)
- Download logs produced while supercomputer job is running
- Cancel Docker Builds and cancel publishing to ACR
- Entra ID authentication support against LLM end-point (previously only API Key was supported).
- Job execution against local container honors environment variables defined for the agent.
 
### Nov 5th 2025
**- Running against Supercomputer:**
			- Added ability to cancel a job.
      - Fixed issues that could arise from mounting inputs and outputs folders, and improved reporting details.

### Nov 3rd 2025
**- Profile Manager:** You can now easily store and switch between multiple profiles. It makes it easier if you are working with multiple projects / companies.
**- Settings improvements:** No need anymore to copy / paste subscription IDs, Resource Groups, Storage accounts, etc. Drop downs let you easily select.
**- AZ CLI dependency removed:** This enables in particular to support properly all features in Codespaces where authentication through AZ CLI would be blocked.
**- Default port changed:** Changed default port from 5000 to 8050 to prevent conflict with Airplay on MacOS

### Oct. 28th 2025
- Simulate built-in file writer agent. Agents now understand they can write content they generate and the workbench will write files in the output folder when the answer is received.