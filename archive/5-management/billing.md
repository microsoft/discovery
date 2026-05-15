# Microsoft Discovery — How Billing Works

Microsoft Discovery uses pricing model and billing patterns similar to other Azure services:

- **Usage-based** billing for compute (nodes, functions, etc.) and storage resources associated to your workspace and projects.
- **Message-based** billing for agent-based discussions with Microsoft Discovery.

This model helps you to:

- Pay only for what you use.
- Track usage and costs with precision.


## 1) What is a “User Message”?

A **User Message** is incremented for each billable operation in Discovery. It represents an action that changes or runs something—such as **create, update, delete, run, submit, or cancel**. Discovery totals these by the hour.

You’re **not** charged for **read-only** calls such as **GET/list/status/logs**.

Billing covers **runtime (dataplane) usage** only; not resource management (controlplane).

## 2) What you pay for

You’re charged for each **User Message**. Each message is billed $0.20 (adjusted to your local currency).

Note: For billing calculations, treat each message as equivalent to 10 backend operations. Use this conversion when estimating usage or reconciling message-based charges with operation-based meters.

**Example:**

- 1 message = 10 backend operations
- 100 messages = 1,000 operations
- At $0.20 per message, 100 messages = $20.00

| You do this… | Billable? |
|--------------|-----------|
| Creating/updating/deleting investigations<br>PUT / PATCH / DELETE /projects/{projectName}/investigations/{investigationName} | Yes |
| Create a conversation (POST /conversations) | Yes |
| Update a conversation (PATCH /conversations/{name}) | Yes |
| Send a message (POST /conversations/{name}/messages) | Yes |
| Submit user input (.../messages/{name}:submitUserInput) | Yes |
| Cancel an operation (...:cancel) | Yes |
| Submitting a job (POST /tools/projects/{projectName}:run) | Yes |
| Cancelling a job (POST /tools/projects/{projectName}/operations/{operationId}:cancel) | Yes |
| List conversations/messages (GET ...) | **No** |
| Check operation status or logs (GET .../operations/{id}, GET .../logs) | **No** |

The same pattern applies across features like **Knowledge Bases**: **create/update/delete/run** = billable; **get/list/status** = not billable.

For jobs running on Microsoft Discovery Supercomputer, you’re billed for the act of running the job, not for the duration or compute consumed (which is billed separately for the standard compute and storage usage).

### Example of conversation flow, and its billing events

| Prompt | Backend API(s) (typical) | Billable | Msg |
|--------|--------------------------|----------|-----|
| “Create a new investigation ‘tumorclassifierv2’ in project ‘genomicspilot’.” | PUT /projects/{projectName}/investigations/{investigationName} | Yes | 0.1 |
| “Start a conversation for this investigation called ‘featuresearch’.” | POST /conversations | Yes | 0.1 |
| “Run feature selection on Cohort A for the top 50 genes.” | POST /conversations/{conversationName}/messages **and** POST /tools/projects/{projectName}:run | Yes | 0.2 |
| “What’s the status?” | GET /tools/projects/{projectName}/operations/{operationId} | No | 0 |
| “Cancel that run.” | POST /tools/projects/{projectName}/operations/{operationId}:cancel | Yes | 0.1 |
| “Use LASSO with alpha 0.1 instead; go ahead.” | POST /conversations/{conversationName}/messages/{messageName}:submitUserInput | Yes | 0.1 |
| “Show me the logs for the latest message.” | GET /conversations/{conversationName}/messages/{messageName}/logs | No | 0 |
| “Update the investigation description to ‘CohortA FS with LASSO alpha 0.1’.” | PATCH /projects/{projectName}/investigations/{investigationName} | Yes | 0.1 |
| “List my investigations.” | GET /projects/{projectName}/investigations | No | 0 |
| “Delete the ‘tumorclassifierv2’ investigation.” | DELETE /projects/{projectName}/investigations/{investigationName} | Yes | 0.1 |

**Totals:**
- **8 billable events** (0.8 User Messages: steps 1, 2, 3×2, 5, 6, 8, 10)
- **3 nonbillable reads events** (steps 4, 7, 9)

## 3) How charges show up on your bill

Each billable action is tied to the **Azure resource** you’re working with (for example, your Discovery project or Bookshelf). That resource’s **subscription** sees the charge.

The unit is **“Microsoft Discovery — User Messages”**. Pricing is set per **region**.

**Back of napkin estimate:**  
Estimated cost ≈ (number of billable actions) × (price per User Message in your region).

To see your actual spend, an Azure subscription owner can open **Cost Management + Billing** in the Azure portal and filter to your Discovery resource.

## 4) Common questions

- **Do GET requests ever incur charges?**  
  No. Reads/lists/status/logs are not billed.

- **Do failed actions get billed?**  
  The goal is to bill **succeeded** actions. Services check resource state before sending usage.

- **Are platform resources in my tenant billed separately?**  
  Yes, your underlying Azure resources (like compute/storage you deploy) are billed by Azure as usual. Discovery billing only covers **API usage** (“User Messages”).

## 5) Tips to manage usage

- Automate thoughtfully: only **submit or run** when you intend to change or execute something.
- Combine steps where possible; fewer **create/update/run** calls = fewer billable messages.
- Use readonly calls (GET) to browse or check status; they’re not billed.

## 6) Glossary

- **Billable action:** Any call that **creates, updates, deletes, runs, submits, or cancels** work. Counts as **0.1 User Message**.
- **Readonly call:** A **GET** that lists, fetches, or checks status/logs. **Not billed.**
- **Resource:** The Discovery item you operate on (project, knowledge base, etc.). It decides **where** the charge appears.
- **Region:** The Azure geography where your resource runs; pricing is region based.

<br>

---

## Compute and storage-based pricing (references to Azure pricing info)

| Service | Pricing Page |
|--------|--------------|
| **Azure Storage** | [Azure Blob Storage Pricing](https://azure.microsoft.com/en-us/pricing/details/storage/blobs/) |
| **Azure Compute** | [Azure Virtual Machines Pricing](https://azure.microsoft.com/en-us/pricing/details/virtual-machines/windows/) |
| **Azure AI Foundry** | [Azure AI Foundry Pricing](https://azure.microsoft.com/en-us/pricing/details/ai-foundry/)|
