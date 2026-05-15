# Microsoft Discovery overview

Microsoft Discovery is an enterprise-grade research and development (R&D) platform that combines artificial intelligence (AI), high-performance computing (HPC), and advanced knowledge management to accelerate innovation across scientific and engineering domains. The platform empowers organizations to automate complex workflows, integrate proprietary data, and leverage multi-agent systems to drive breakthrough discoveries.

> [!NOTE]
> Microsoft Discovery is currently in **private preview**. Features and capabilities are subject to change. For access, contact your Microsoft representative.

## What is Microsoft Discovery?

Microsoft Discovery provides an integrated environment where researchers and engineers can:

- **Accelerate research workflows** through autonomous AI agents that handle literature review, hypothesis generation, simulation, and analysis
- **Connect distributed knowledge** using Graph Retrieval-Augmented Generation (GraphRAG) to index proprietary data alongside public scientific resources
- **Execute computational tasks** on scalable HPC infrastructure designed for scientific and engineering workloads
- **Collaborate seamlessly** within secure, enterprise-grade workspaces with role-based access control

The platform supports the entire R&D lifecycle—from initial knowledge exploration through experimental design, execution, and validation—in domains including chemistry, materials science, biology, pharmaceuticals, semiconductor design, and engineering simulation.

## Key capabilities

### 🤖 Intelligent multi-agent orchestration

Microsoft Discovery uses specialized AI agents that work together to solve complex research challenges. These [agents](../3-concepts/agents.md) can:

- Operate domain-specific tools and models (GROMACS, SPICE, LAMMPS, and more)
- Coordinate multi-step workflows across different scientific domains
- Adapt reasoning strategies from quick heuristics to deep analysis
- Learn from execution outcomes to improve decision-making

> [!TIP]
> Start with pre-built agents for common scientific tasks, then customize or create your own agents for domain-specific needs. See [how to deploy agents](../4-how-to/6-tools-models-agents/c--agent-deployment.md) to get started.

### 🧠 Discovery Engine with cognitive layer

The [Discovery Engine](../3-concepts/engine.md) provides an ongoing reasoning process that works collaboratively with you on ambitious, long-duration research:

- **Adaptive cognition**: Selects between fast and slow reasoning patterns based on task complexity
- **Task decomposition**: Breaks down complex objectives into manageable subtasks
- **Continuous learning**: Improves decision-making by analyzing agent and tool outputs
- **Autonomous execution**: Works in the background on multi-day research initiatives

The cognitive layer enables intelligent routing of research challenges, determining which agents, tools, and data sources to use at each step.

### 📚 Bookshelf knowledge management

[Bookshelf](../3-concepts/bookshelf.md) transforms your documents—including text, PDFs, Word files, PowerPoint presentations, and Excel spreadsheets—into queryable knowledge graphs using advanced GraphRAG technology:

- **Graph-based retrieval**: Creates knowledge graphs that capture entity relationships, providing more accurate context and nuanced insights than traditional RAG
- **Agent integration**: Any agent can query your knowledge bases for grounded, traceable insights
- **Reasoning in context**: Create curated knowledge graphs for the data that matters most to you -  hardware specifications, simulation reports, design documents, technical literature - to leverage your knowledge in Discovery workflows 

> [!IMPORTANT]
> Unlike traditional vector-only approaches, Bookshelf's GraphRAG implementation captures semantic relationships between entities, leading to higher-quality responses for complex queries.

### 💬 Natural language interaction

Interact with the platform through [Microsoft Discovery Copilot](../3-concepts/copilot.md), a conversational interface that:

- Understands research intent expressed in natural language
- Orchestrates multi-agent workflows transparently
- Maintains context across multi-turn conversations
- Provides real-time visibility into agent execution

Access Copilot through **Microsoft Discovery Studio**, a web-based interface for managing projects, investigations, and data.

### ⚡ High-performance compute infrastructure

Execute computationally intensive workloads on Azure-hosted [supercomputers](../3-concepts/supercomputer.md):

- Scalable node pools with GPU and CPU options
- Secure virtual network integration
- Managed identity-based access control
- Integrated storage for input/output data

### 🔧 Extensible architecture

Microsoft Discovery's open architecture supports:

- **Bring your own models** (BYOM): Integrate custom AI models alongside Azure OpenAI
- **Custom tools**: Package domain-specific scientific software as containerized tools
- **Third-party integrations**: Connect to public databases (PubChem, PubMed, ChEMBL, BindingDB, Clinical Trials)
- **Flexible workflows**: Define sophisticated multi-agent orchestrations for your specific R&D processes

## Platform architecture

Microsoft Discovery is built on several core components:

| Component | Description | Learn more |
|-----------|-------------|------------|
| **Workspaces** | Collaborative environments for organizing projects and resources | [Resource types](./2-resource-types.md) |
| **Projects** | Containers for investigations with defined agents, tools, and data | [Creating projects](../4-how-to/7-projects/a--creating-project.md) |
| **Investigations** | Research studies where you interact with Copilot and analyze results | [Creating investigations](../4-how-to/8-investigations/a--creating-investigation.md) |
| **Agents** | AI assistants that execute tasks using tools and models | [Agents concept](../3-concepts/agents.md) |
| **Tools** | Containerized scientific software and utilities | [Tools concept](../3-concepts/tools.md) |
| **Models** | AI models for reasoning and specialized tasks | [Models concept](../3-concepts/models.md) |
| **Bookshelf** | Knowledge base creation and query service | [Bookshelf concept](../3-concepts/bookshelf.md) |
| **Supercomputers** | HPC resources for executing computational workloads | [Supercomputer concept](../3-concepts/supercomputer.md) |

## Industry applications

Microsoft Discovery accelerates innovation across multiple domains:

### Chemistry and materials science
- Molecular property prediction and optimization
- Retrosynthesis planning
- Materials discovery and characterization
- Reaction pathway analysis

**Learn more**: [Chemistry use cases](../6-solutions/use-cases/chemistry.md) | [Chemistry scenarios](../6-solutions/domain-scenarios/chemistry/)

### Biology and pharmaceuticals
- Drug target identification
- Protein structure analysis
- Binding affinity prediction
- Literature-based hypothesis generation

**Learn more**: [Biopharma use cases](../6-solutions/use-cases/biopharma.md)

### Silicon and semiconductors
- Circuit simulation and verification
- Design rule checking
- Performance optimization
- Process variation analysis

**Learn more**: [Silicon use cases](../6-solutions/use-cases/silicon.md) | [Silicon scenarios](../6-solutions/domain-scenarios/silicon/)

### General engineering
- Simulation workflow automation
- Design space exploration
- Technical documentation analysis
- Multi-physics optimization

## Security and compliance

Microsoft Discovery runs on Azure's trusted cloud platform with:

- **Enterprise security**: Virtual network isolation, managed identities, role-based access control (RBAC)
- **Data sovereignty**: Resources deployed in your Azure subscription with full control over data location
- **Compliance**: Built-in support for regulatory requirements in highly regulated industries
- **Transparency**: Detailed logging and auditing of all agent actions and data access

> [!IMPORTANT]
> Review the [security best practices](../7-security-and-governance/microsoft-discovery-security-best-practices.md) and [Microsoft Discovery FAQ](../7-security-and-governance/Microsoft_Discovery_FAQ.md) before deploying to production environments.

## Getting started

Ready to explore Microsoft Discovery? Follow these steps:

1. **Review prerequisites**: Ensure you have an enabled Azure subscription and necessary permissions
2. **Complete the quickstart**: Deploy your first workspace, agents, and investigation
3. **Explore sample tools**: Try pre-built scientific tools and agents
4. **Build custom solutions**: Create domain-specific agents and workflows

> ➡️ **Next Step**
> [Start with the quickstart guide](../2-getting-started/quickstart.md)

## Additional resources

### Documentation
- [Concepts](../3-concepts/resource-types.md) - Understand core platform components
- [How-to guides](../4-how-to/README.md) - Step-by-step tutorials for common tasks
- [Sample tools and models](../6-solutions/tools-and-models/) - Pre-built components you can use immediately

### Deployment and utilities
- [Infrastructure deployment scripts](../utils/validate-and-deploy-infra-scripts/) - Automate resource provisioning
- [Agent Workbench](../utils/agent-workbench/) - Test and debug agents locally, and facilitate their deployment to Microsoft Discovery
- [Validation tools](../utils/validation-script/) - Verify your deployment configuration

Note that the VS Code Extension has been retired (not to be confused with new https://vscode.dev/discovery experience) and is no longer supported at this point.

### Community and support
- [FAQ](4-faq.md) - Frequently asked questions
- [Troubleshooting guide](5-troubleshooting.md) - Common issues and solutions
- **Private preview support**: Contact your Microsoft representative for assistance

---

## What makes Microsoft Discovery unique?

Unlike traditional scientific computing platforms or standalone AI tools, Microsoft Discovery provides:

✅ **Unified environment**: No context switching between knowledge management, computation, and AI interaction  
✅ **Transparent AI**: Full visibility into agent reasoning, tool execution, and data provenance  
✅ **Enterprise-ready**: Built on Azure with compliance, security, and governance from day one  
✅ **Domain-agnostic**: Applicable across scientific and engineering disciplines with extensible architecture  
✅ **Collaborative**: Shared workspaces enable team-based research with appropriate access controls

> [!TIP]
> Microsoft Discovery is designed for complex, multi-faceted research challenges that benefit from autonomous AI assistance over hours or days, not simple one-off queries. Use the Discovery Engine for ambitious goals like "identify novel drug candidates with optimized binding affinity and reduced toxicity" rather than "what is the molecular weight of aspirin?"

## Next steps

Explore the platform by diving into these key topics:

- [Understand Discovery concepts](../3-concepts)
- [Deploy your first workspace](../2-getting-started/quickstart.md)
- [Learn about agents and workflows](../3-concepts/agents.md)
- [Create a knowledge base](../4-how-to/9-bookshelves-knowledgebases)
- [Review security best practices](../7-security-and-governance/microsoft-discovery-security-best-practices.md)
