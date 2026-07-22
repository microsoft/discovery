[← Microsoft Discovery services FAQ](README.md)

# Microsoft Discovery agents, models, and Foundry FAQ

This article answers common questions about how Microsoft Discovery agents work, which models are required, how agents integrate with Azure AI Foundry and MCP tools, and how to enable GitHub Copilot and the unified workbench.

## Agents and Foundry integration

### How are agents implemented?

Discovery agents are created as data plane resources, with corresponding agents created in Azure AI Foundry. Foundry executes the workflows triggered by user prompts.

### Are hosted agents used?

Not currently. Hosted agents are a potential future capability.

## Models

### Which models are required?

Microsoft Discovery requires specific chat completion and text embedding model deployments. Based on the [Microsoft Learn quota reservation guidance](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-quota-reservation#per-service-model-tpm-breakdown), the required models are:

| Model | Service | Scope |
| --- | --- | --- |
| GPT-5.4 | Discovery Engine and Agents (Copilot Service) | Per workspace |
| GPT-5.2 | Bookshelf | Per Bookshelf instance |
| GPT-5 Mini | Bookshelf | Per Bookshelf instance |
| Text Embedding 3 (Small) | Bookshelf | Per Bookshelf instance |

The Discovery Engine uses two GPT-5.4 deployments: one auto-provisioned during workspace creation for cognition (reasoning and task planning), and one created manually (named `gpt-5-4`) for task validation. Review the documentation for the minimum and recommended TPM (tokens-per-minute) quota per service, and multiply the Bookshelf values by the number of Bookshelf instances.

### Can customers choose the models their agents use?

Yes. Customers can select different models for Discovery agents, subject to the minimum required models and any quota reservations described in the documentation.

### Where should models run—Azure ML or the Supercomputer (SC)?

Both are options. An existing Azure ML workspace can be reused to host models. Alternatively, if a model is containerized, it can run on the Supercomputer. Choose based on whether you already have ML assets or prefer container-based execution.

## GitHub Copilot and the unified workbench

### What's needed to enable GitHub Copilot features?

The unified Workbench is in preview. To enable it, ensure your workspace is deployed with the tags `discovery.workbench.enableGhcpAiFeatures : true` and `discovery.workbench.enableExtensions : true`. Additionally, you need an appropriate GitHub Copilot account.

## Related content

- [Microsoft Discovery knowledge retrieval FAQ (Bookshelf, GraphRAG, and Azure AI Search)](bookshelf-and-knowledge-retrieval-faq.md)
- [Microsoft Discovery infrastructure and deployment FAQ](infrastructure-and-deployment-faq.md)
