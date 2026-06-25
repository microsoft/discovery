[← Microsoft Discovery services FAQ](README.md)

# Microsoft Discovery knowledge retrieval FAQ: Bookshelf, GraphRAG, and Azure AI Search

This article answers common questions about selecting and combining the knowledge retrieval options in Microsoft Discovery—Bookshelf (GraphRAG), Azure AI Search (vector and agentic retrieval), and Foundry IQ—and how to curate data and route queries for the best results.

## Choosing between Bookshelf and Azure AI Search

### What is the difference between Bookshelf (GraphRAG) and Azure AI Search?

**Bookshelf (GraphRAG)** runs an OCR → normalization → embeddings → graph-community pipeline. A query first does a broad vector (cosine similarity) search, then expands through graph communities and produces thematic summarization. Its strength is deep, multi-hop, thematic insight that surfaces hidden relationships. Its limitations are that it needs a curated, connected dataset and is memory-intensive (about a 1 GB limit).

**Azure AI Search** runs an index → embeddings → agentic retrieval pipeline. Its strength is precise, local queries that work at large scale (100+ GB), and it supports multi-hop reasoning through its agentic retrieval stack—without graph community navigation. Its limitation is that it has no graph or community reasoning.

### Which tool should I use for which query?

| Use case | Best tool |
| --- | --- |
| Specific lookup / factual queries | Azure AI Search |
| Broad, thematic, discovery insights | Bookshelf (GraphRAG) |

A useful framing is a *query spectrum* from local to global. GraphRAG only adds value at the upper (global) end of that spectrum.

### When should I use Bookshelf versus Foundry IQ or vector search?

Before adopting Bookshelf, evaluate whether Foundry IQ or Azure AI Search (vector search) already meets the need. Use Bookshelf only when the data is unstructured, curated, and complex (for example, scientific datasets). Vector search is recommended for larger or less-curated datasets.

### Do I actually need Bookshelf for my scenario?

It depends on your data. Bookshelf adds value for curated, connected unstructured corpora where thematic, multi-hop insight matters; for simpler retrieval, Azure AI Search may suffice.

### Are Azure Machine Learning and Azure AI Search provisioned by Discovery?

No. Azure ML and Azure AI Search are separate resources that are not auto-provisioned with a Discovery workspace. You must create them in the customer resource group.

## Data size and curation

### Can the system handle a 100+ GB corpus?

Not directly in Bookshelf. A realistic Bookshelf input is about 1 GB of normalized text after extraction. The recommended pattern is to keep the full corpus (100+ GB) in Azure AI Search and curate a small, high-quality subset (in the low-GB range) for Bookshelf. Do not ingest the entire corpus into Bookshelf.

### Why is Bookshelf limited to about 1 GB?

GraphRAG requires in-memory graph construction and community detection, which is memory-bound even on large compute nodes. The limit is not arbitrary—it aligns with both system constraints and scientific usability. For context, 6,000 research papers normalize to roughly 180 MB of text, which already represents a large scientific dataset.

### How do I select the right subset of data for Bookshelf?

Use an evaluation-driven curation process:

1. Start with the large dataset (for example, 6,000 papers).
2. Run an eval pipeline to detect weak topical relevance.
3. Use LLM (GPT-based) scoring to identify thematic alignment and rank documents.
4. Reduce to a connected corpus (for example, ~3,000 papers).

The goal is semantic connectivity and avoiding disconnected clusters. GraphRAG works well only when the data is thematically coherent.

### What data types are supported?

Common document types include Word, PowerPoint, Excel, and PDF, covering content such as scientific reports, patents, and research articles.

## Query types

### What kinds of queries work best where?

- **Local queries** (for example, "Where did protein X appear?") need precision → use **Azure AI Search**.
- **Global queries** (for example, "What patterns exist across protein behaviors?") need relationship synthesis → use **Bookshelf (GraphRAG)**.

## Recommended hybrid architecture

### How should I design the system for production use?

Use a hybrid pattern:

- **Azure AI Search** indexes the full corpus (100+ GB).
- **Bookshelf / GraphRAG** indexes a curated subset (1–5 GB, logically split into multiple subgraphs).
- A **Discovery agent** uses both as MCP tools and routes by instruction: local queries → Azure AI Search, global queries → GraphRAG.

The key mechanism is the agent instructions that decide when to call which tool. A possible improvement is sample-based query classification (local versus global).

### How do I scale to larger curated datasets?

Split the curated data into multiple Bookshelves (subgraphs)—for example, 5 GB across five separate Bookshelves—and combine them through agent grounding tools. The future direction is GraphRAG Zero, a unified vector + graph stack that collapses the vector store into Azure AI Search for unified local and global querying with dynamic routing.

## Structured data integration

### How do I handle structured data (SQL / Fabric)?

GraphRAG is not suited to structured data today. Use Azure AI Search knowledge sources instead. Azure AI Search now supports agentic retrieval over Azure SQL Database (vector-embedding search on structured data) without building graph communities. Structured data in Microsoft Fabric Lakehouse can be brought into Foundry IQ and Discovery agents. There's currently no unified graph solution spanning structured and unstructured data.

### How do agents work with structured data?

Agent instructions should account for different query types over structured data—typical search, multi-hop queries, and SQL-style queries—potentially combining techniques for full coverage. Azure AI Search supports agentic retrieval over Azure SQL Database, and structured data in Microsoft Fabric Lakehouse can be brought into Foundry IQ and Discovery agents. Existing data-science models are trained on pre-curated tables and don't cover the full dataset, so broader agentic retrieval is needed for open-ended scientific discovery.

## Agents and retrieval behavior

### How do agents route queries across tools?

A Discovery agent can be configured with multiple MCP tools—for example, Azure AI Search and Bookshelf/GraphRAG—and the agent instructions decide which tool handles a query: local, factual questions go to Azure AI Search, while global, thematic questions go to GraphRAG. Routing is driven by sample question types and agent guidance.

### Can agents automatically choose the right retrieval path?

Not fully automatically today. Agents need explicit instructions and example-driven guidance. A known issue is that agents may skip the knowledge base and answer from model memory instead, producing responses without citations. Enforce strict tool-usage rules through skills and instructions (for example, GitHub Copilot skills that require querying the knowledge base) to ensure source-of-truth responses.

### Do scientists always need an agent to query a Bookshelf?

No. Scientists can query a Bookshelf directly in natural language. Agents become relevant when a Bookshelf is used as grounding data in multi-step investigations. A good practice is to align specific Bookshelves and graphs to specific agents or domains for targeted retrieval, scaling out as new agents are introduced.

## Risks and mitigation

### What are the main risks when adopting GraphRAG?

- **Misuse of GraphRAG** by dumping the full corpus, which produces poor results.
- **Overpromising** "global discovery" and setting unrealistic customer expectations.
- **Poor data curation**, which yields weak graph insights.

The mitigation is to start with Azure AI Search for quick wins, then introduce GraphRAG on a curated subset. Success depends primarily on data curation, not tooling.

## Related content

- [Microsoft Discovery infrastructure and deployment FAQ](infrastructure-and-deployment-faq.md)
- [Microsoft Discovery agents, models, and Foundry FAQ](agents-models-and-foundry-faq.md)
