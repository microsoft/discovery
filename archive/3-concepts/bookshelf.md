# Microsoft Discovery Bookshelf
Microsoft Discovery includes Bookshelf, a service that enables customers to convert their data, such as text, Word, and PDF documents, into a curated graph known as a Knowledge Base (KB). This KB can then be queried to support various use cases, including answering questions, summarization, reasoning, and logical inference.

Knowledge Bases work best when their contents are thematically coherent and directly relevant to your project workflows. For example, an ASIC design team could create a Knowledge Base with their project's hardware specifications, simulation result reports, and the latest relevant literature from the field. Querying this Knowledge Base during design workflows ensures Discovery's reasoning is grounded with previous engineering content and scientific literature. 

Bookshelf leverages an advanced technique called Graph Retrieval-Augmented Generation (GraphRAG) to transform customer data and generate responses to queries. Unlike traditional RAG methods, GraphRAG-based algorithms not only create an indexed vector database of the source content but also constructs a knowledge graph that captures entity relationships within the data. Research from Microsoft has demonstrated that GraphRAG delivers more accurate grounding information than standard RAG techniques, leading to higher-quality responses. 

## Features
### Indexing
Bookshelf supports indexing of documents stored in Azure Blob Storage. Supported file formats include:

* Text (.txt)
* PDF (.pdf)
* Word (.docx)
* PowerPoint (.pptx)
* Excel (.xlsx)

The artifacts of the indexing, e.g., knowledge graphs, vector databases, collectively known as Knowledge Base (KB), will be stored in an Azure SQL DB in your subscription. 

### Query
Bookshelf provides the query function that can be invoked by any agent running on the Microsoft Discovery platform, including your own agent. 
