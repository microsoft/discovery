# Troubleshooting #

**Q:
Why do I get “Error: Invalid JSON provided for args” when passing agent-created JSON to a tool in Microsoft Discovery?**

This error usually happens because the JSON string for `tool_args` is HTML-encoded, which causes parsing failures. To fix this, make sure to use HTML escaping when passing the arguments. See [HTML Escaping](https://handlebarsjs.com/guide/#html-escaping) for more details.

```
python main.py --server {{server_url}} call-tool {{tool_name}} --args '{{{tool_args}}}'
```

**Q:
Why am I getting “Failed to fetch investigations list for {workspace name} / {project name}. 403 Forbidden”**

You need to be granted with Discovery Contributor role at the subscription level.

**Q:
While creating a new data asset in Microsoft Discovery, I encounter the following error:
"Error uploading or creating data asset. This request is not authorized to perform this operation using this permission."**

1. Locate the storage account for the region
2. In the Storage account, open Security + Networking > Either
- "Enable for all networks" for Public network access
- "Resource settings:" > View > IPv4 > Add your public internet IP address

**Q:
When opening a data asset produced by an investigation, I get “You don't have permission to access this storage blob resource”**

1. draft


**Q:
When trying to open a project, I am getting "Failed to fetch investigations list for {workspace} / {project}.(500) undefined"**

You may have set the NSP Access mode to Enforced. Follow these steps:
1. Go to discovery workspace resource overview page.
1. Click on Managed Resource Group link.
1. Within that Resource Group, there will a Cosmos DB named <workspaceName>-cosmosdb, click on that.
1. From <workspaceName>-cosmosdb, Go to Networking Page> click on "Network Security Perimeter" tab, there will be a property called Access Mode which can be Enforced or Transition.

**Q:
Getting "Error: queue_access_forbidden; No permission to access Azure Function queue <queue_name>" when agent queries Knowledge Base.**

Follow these steps:
1. Navigate in Azure Portal to your bookshelf
1. Open the MRG
1. Identify the Correct Storage Account: Go to the Bookshelf resource group (MRG) containing storage account.
1. Assign Storage Queue Data Contributor Role:
   - In the storage account, navigate to IAM and add a role assignment for "Storage Queue Data Contributor".
   - Select Managed Identity > Select Members
   - Managed identity > Azure AI Foundry project
   - Filter by your project name
   - Select the Correct Managed Identity: When assigning the role, ensure you select the managed identity associated with your AI Foundry project (not your personal UAMI). This is typically the system-assigned identity for the specific AI Foundry project.
1. Confirm Role Assignment: Assign the role and wait a few minutes for permissions to propagate.

**Q:
What are the known issues when creating knowledge bases in Microsoft Discovery?**

These are some known issues:
- Kb's Data asset pointing to a file instead of folder. This use case is not supported yet
- Office files (used for indexing) with confidentiality settings enabled.

**Q:
The response to my investigation query results in "Error: Message ID is malformed or missing."**

This issue is still under investigation. Try the query again.

**Q: When directly submitting jobs to the Supercomputer, jobs remain in 'Running' state without starting execution.**
This issue may happen if there is a mismatch between the tool definition not requiring any GPU and the nodepool selected requiring GPU resources. To resolve this, ensure that the tool definition matches the nodepool requirements. For example, if the nodepool includes GPUs, make sure the tool is defined to utilize GPU resources.

**Q: Error: JSON deserialization for type 'AgentFunctions.Service.Models.ToolInvocationRequestMessage' was missing required properties including: 'MessageId'.**

TBD

**Q: I get "[Error from AIFoundry]: Run failed with status: failed. ErrorDetails: Code=server_error, Message=Server error from AI Foundry" when running an investigation.**

- Agent instructions must be less than 30,000 characters. Check your agent definition and reduce the length of the instructions section if it exceeds this limit.
- Publish the updated agent and project, and try again.

**Q: When asking a question in my investigation, I get "Rate limit is exceeded. Try again in 5 seconds."**

- Increase Quota in AI Foundry
      - Go to Workspace → AI Foundry → Management Center.
      - Raise TPM/RPM for the model (default is often 200K TPM).
      - For hackathon or shared environments, request higher quota or switch to Provisioned Throughput for guaranteed bandwidth. [Agent crea...: ACN/MSFT | Teams], [Agent crea...: ACN/MSFT | Teams]

- Enable Retry in Workflow
      - In Discovery workflows, set maxRateLimitRetries in the agent definition.
      - Default is 3; increase if needed (though some versions may not honor this—check AI Foundry release notes).

**Q: While creating a knowledge base, I encounter "Failed to create knowledge base / Failed to fetch"**

Make sure your knowledge base name follows these rules:

- Permitted Characters: Lowercase letters, digits, and hyphens. 
- Length Requirements: 3 to 12 characters. 
- Pattern: Must start with a letter; dashes can be applied as word separators. 
- Examples: ai-project, adhesives01 

**Q: What are the restrictions on resource names in Microsoft Discovery?**

All resource types in the Microsoft Discovery Platform must adhere to these foundational principles: 
   - Uniqueness: Resource names must be unique within their scope (subscription, or resource group for control plane and parent control plane resource for data plane). 
   - Predictability: Naming patterns should be consistent, facilitating automation and integration. 
   - Character Set: Names must only use alphanumerical characters and shouldn’t start with a number. 
   - Case Sensitivity: Unless otherwise stated, resource names are case-insensitive but must be entered and stored in lower case for consistency. 
   - Length Constraints: Each resource type defines its own minimum and maximum length; exceeding those constraints should show a proper error message when the validation fails. For some discovery resources where we create corresponding resources in the backend in a different RP, we add a unique GUID as suffix so that length must also be taken into consideration while defining the limits. 
   - No Spaces or Special Characters: Resource names cannot include whitespaces and special characters except `-` (hyphen) unless stated otherwise. 
   - No Consecutive Separators: Multiple dashes, underscores, or other separators must not appear consecutively.

**Agent**
  - Permitted Characters: Uppercase or Lowercase letters, digits, and dashes. 
  - Length Requirements: 3 to 24 characters. 
  - Pattern: Must start and end with a letter; dashes can separate words. 
  - Examples: search-agent, crawler-agent 

**Workflow**
  - Permitted Characters: Uppercase or Lowercase letters (a-z), digits (0-9), dashes (-). 
  - Length Requirements: 3 to 24 characters. 
  - Pattern: Must begin with a letter, can include digits, dashes, and end with a letter or digit. 
  - Examples: chemistry-workflow, etlWorkflow

**Project**
  - Permitted Characters: Lowercase letters, digits, and hyphens. 
  - Length Requirements: 3 to 12 characters. 
  - Pattern: Must start with a letter; dashes can be applied as word separators. 
  - Examples: ai-project, adhesives01

**Knowledge Base**
  - Permitted Characters: Lowercase letters, digits, and hyphens.
  - Length Requirements: 3 to 12 characters.
  - Pattern: Must start with a letter; dashes can be applied as word separators.
  - Examples: ai-project, adhesives01

**Q: When creating a project, I am getting "Failed to create project.(403 AuthorizationFailed) "**
 - Make sure you are granted with "Microsoft Discovery Platform Administrator (Preview)"

 **Q: Getting "Issue while attempting to preview the data asset" or "failed to authenticate azstorage credentials with error [BlockBlob::TestPipeline : [AuthorizationFailure]"**
 - Make sure that the subnet selected for the Supercomputer is in the list of subnets allowed in the Azure storage account.

 **Q: When deploying a tool, trying to create a Supercomputer or create a Discovery Storage, I am getting an "AuthorizationFailed" error.**

 Your error may look like this:
 ```
{
    "status": "Failed",
    "error": {
        "code": "AuthorizationFailed",
        "message": "The client '<REDACTED_EMAIL>' with object id '<REDACTED_OBJECT_ID>' does not have authorization to perform action 'Microsoft.Discovery/locations/operationStatuses/read' over scope '/subscriptions/<REDACTED_SUBSCRIPTION_ID>/providers/Microsoft.Discovery/locations/<REDACTED_LOCATION>/operationStatuses/<REDACTED_OPERATION_ID>' or the scope is invalid. If access was recently granted, please refresh your credentials."
    }
}
 ```

 - Make sure you are granted with "Reader" role at the subscription level.