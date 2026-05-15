# Azure NetApp Files MCP services

This example provides both the server and Discovery client solutions to implement an MCP connection to the Azure NetApp Files Object REST interface. The Object REST interface exposes an S3 protocol compliant connection to the volumes available on Azure NetApp Files.

## Structural Elements

This solution consists of three components:

1. **Azure NetApp Files**: This is your Azure high performance NFS fileserver. You must have the Object REST interface enabled. This solution is currently in public preview. If you do not already have it enabled, contact your Azure account team to have your subscription enabled for this preview feature.

2. **S3 MCP Server**: This is an S3 MCP implementation developed by Konstantinas Mamonas. This version has been customized to include the required modifications to work with the ANF S3 interface and to run as a stateless MCP server. The MCP server must be run on a persistent VM. The files for this component are located in the server-s3mcp directory. Copy the contents of the directory to the VM that will serve as your MCP server. Follow the instructions in the README.md in that directory for setup.

3. **Discovery MCP Client**: The Discovery MCP client files are located in the client-anfs3mcp directory. It consists of the docker container definition as well as included Discovery tool, agents, and workflow examples. Refer to the README.md in that directory for details.

## Use Cases

The Azure NetApp Files MCP solution enables powerful automation scenarios by combining high-performance storage with intelligent file management through natural language interfaces. Here are three key use cases:

### 1. Chip Design: Specification-to-RTL Lint Check and Fix Pipeline

**Scenario**: A semiconductor design team needs to automatically validate RTL code against design specifications, identify lint violations, and apply fixes while maintaining design integrity across multiple project variants.

**Workflow**:
- **Design Discovery**: Use `list_buckets` to identify active design projects and `list_objects_v2` to inventory RTL files, specification documents, and lint rule sets across different project branches
- **Specification Retrieval**: Use `get_object` to fetch design specifications, constraint files, and previous lint reports for context analysis
- **RTL Analysis**: Use `download_file` to retrieve RTL source files for lint checking and `head_object` to verify file integrity and version metadata
- **Lint Processing**: Process RTL through automated lint tools, generating violation reports and suggested fixes
- **Result Management**: Use `put_object` to store lint reports, fixed RTL code, and compliance certificates in organized project structures
- **Version Control**: Use `copy_object` to create backup copies of original files before applying fixes and `delete_objects` to clean up temporary lint processing files
- **Cross-Project Sync**: Use `copy_object` to propagate verified fixes and updated lint rules across related design projects

**Natural Language Example**: *"Analyze all RTL files in the cpu-design bucket for lint violations against the latest specification, apply automated fixes where safe, and create a compliance report showing before/after comparisons."*

### 2. Research Data Management and Collaborative Analysis

**Scenario**: A research team needs to manage large scientific datasets, coordinate analysis workflows, and share results across distributed team members while maintaining data lineage and version control.

**Workflow**:
- **Data Discovery**: Use `list_buckets` and `list_objects_v2` to inventory available datasets across multiple research projects and identify data ready for analysis
- **Selective Retrieval**: Use `head_object` to check file metadata and sizes before using `get_object` or `download_file` to fetch specific datasets for analysis
- **Collaborative Processing**: Use `put_object` and `upload_file` to store intermediate results and analysis outputs in shared project spaces
- **Data Lineage**: Use `copy_object` to maintain audit trails and create versioned snapshots of processed data
- **Result Distribution**: Use `copy_object` to replicate final results to team member buckets and presentation folders
- **Cleanup Management**: Use `delete_objects` to remove outdated interim files while preserving final results and audit trails

**Natural Language Example**: *"Find all genomics datasets modified in the last week, run the analysis pipeline on files larger than 1GB, and share results with the European team by copying to their shared bucket."*

### 3. Multi-Environment Software Deployment and Configuration Management

**Scenario**: A development team needs to manage application deployments across multiple environments (development, staging, production) while ensuring configuration consistency and enabling rapid rollbacks.

**Workflow**:
- **Environment Assessment**: Use `list_buckets` to identify deployment environments and `list_objects_v2` to compare current deployments and configurations
- **Configuration Sync**: Use `get_object` to retrieve environment-specific configuration files and `head_object` to validate configuration versions and checksums
- **Deployment Orchestration**: Use `upload_file` to deploy new application versions and `put_object` to update configuration files across environments
- **Backup Management**: Use `copy_object` to create pre-deployment backups and maintain rollback-ready versions in archive buckets
- **Consistency Validation**: Use `get_object` to verify deployed configurations match expected templates and `head_object` to confirm file integrity
- **Cleanup Operations**: Use `delete_object` and `delete_objects` to remove deprecated versions and temporary deployment artifacts

**Natural Language Example**: *"Deploy the latest application build to staging, verify configurations match production settings, create rollback snapshots, and clean up deployment files older than 30 days."*

