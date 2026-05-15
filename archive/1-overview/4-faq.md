## Microsoft Discovery FAQ

**Q: How does Microsoft Discovery ensure consistent and scientifically reproducible results from agent-driven workflows?**  
A: We are developing a feature to capture the series of computations within a workflow, reducing variability by not interacting directly with LLMs. Human oversight allows scientists to approve or edit plans, validate results, and ensure convergence to a predetermined goal.

**Q: What is the rigorous vetting process for supporting the scientific validity, performance, and ethical considerations of models within the AI Foundry Catalog?**  
A: AI Foundry, the leading marketplace for AI models and agents, subjects each publisher to rigorous vetting, including Responsible AI and security considerations.

**Q: What is the expected effort for tool publishers to provide the "comprehensive documentation" required for consistently accurate dynamic code generation, especially for complex scientific tools?**  
A: Better documentation helps LLMs gain better context. We are building tools to allow users to easily build agents with documentation and sample codes. Our GitHub repository has example agents with full documentation and can serve as a great starting point.

**Q: What level of granular visibility and control is offered to HPC administrators or expert users for fine-tuning job scheduling, resource allocation, and optimizing performance? How can customers achieve detailed cost transparency for different Nodepool types and scaling behaviors?**  
A: As of private preview, customers do not have fine grain control over HPC resources. Debugging, monitoring, and troubleshooting can be done on the Azure portal but not through Microsoft Discovery. We are working on a roadmap for direct access to supercomputing resources.

**Q: How robust is Bookshelf in handling highly ambiguous scientific queries, contradictions, or subtle nuances prevalent in scientific literature?**  
A: Bookshelf uses GraphRAG which outperforms standard RAG by introducing a structured, relationship-aware approach to retrieval, enabling deeper reasoning and richer context. It uses knowledge graphs to maintain explicit entity relationships, making it ideal for reasoning.

**Q: How does the platform support collaborative development, version control, and shared access to complex multi-agent workflows defined through the Copilot for research teams?**  
A: Multiple people can work on one investigation within a project, publishing workflows and agents. We are working on version control for agents. LLMs understand domain specifics well, and agents with access to your Knowledge Base augment the base-trained LLMs.

**Q: Is Microsoft Discovery primarily an offline optimization and prediction platform, or are there capabilities for direct, real-time, closed-loop process control of physical scientific or manufacturing equipment?**  
A: Discovery is an online platform with human oversight. Researchers can change, edit, and kick off runs as needed. We are thinking about extending Microsoft Discovery to digital twins and lab automation using natural language, giving researchers more access to lab processes.

**Q: In what order should Discovery resources be deleted?** 
A: To avoid deletion issues due to backreferences, Discovery resources should always be deleted in the following order:
- Investigations
- Project
- Workspace
- Discovery Storage
- Workflow
- Knowledge Base
- Bookshelf
- Agent
- Tools
- Node Pool
- Supercomputer
- Data Asset
- Data Container
- Storage / VNETs

**Q: Getting AuthorizationFailed errors when creating Discovery Storage and Supercomputer**

A: If you're hitting errors like the one below when creating a Discovery Storage or Supercomputer:

{
    "status": "Failed",
    "error": {
        "code": "AuthorizationFailed",
        "message": "The client '<ANONYMIZED_EMAIL>' with object id '<ANONYMIZED_OBJECT_ID>' does not have authorization to perform action 'Microsoft.Discovery/locations/operationStatuses/read' over scope '/subscriptions/<ANONYMIZED_SUBSCRIPTION_ID>/providers/Microsoft.Discovery/locations/<ANONYMIZED_LOCATION>/operationStatuses/<ANONYMIZED_OPERATION_ID>' or the scope is invalid. If access was recently granted, please refresh your credentials."
    }
}

It's likely because you did not activate your "Eligible time-bound assignments". To resolve this, follow these steps:

- Go to the Azure Portal: https://portal.azure.com/
- Navigate to your Subscription or Resource Group where you're creating the Discovery resources.
- Click on "Access control (IAM)" in the left-hand menu.
- Click on "Eligible assignments" or "Time-bound assignments" (the exact wording may vary).
- Activate any eligible assignments related to your user account.
- Refresh your credentials or sign out and sign back in to the Azure Portal.
- Retry creating the Discovery resources.

**Q: 
What are the distinct roles of Discovery Storages and Azure Blob Storage in Microsoft Discovery?**

A: They have two distinct roles:

- **Discovery Storages**: A workspace-level shared storage resource you provision via Microsoft Discovery Storages in the Azure portal. 
Provides high‑performance, POSIX‑compatible shared storage for computational workloads executed by the Supercomputer and its node pools—i.e., the compute plane attached to the same VNet/subnets.

- **Azure Blob Storage**: An object store that holds input/output data assets for investigations and projects. It’s created/configured as a standard Azure Storage Account (with a container named discoveryoutputs), then added in Discovery Studio as a Data Container of type Azure Storage Blob for your project. Serves as the data lifecycle boundary for projects—organizing inputs to analyses and outputs produced by investigations. Discovery Studio uses this Blob container to persist and publish data assets (ingress/egress, browsing, downloading).