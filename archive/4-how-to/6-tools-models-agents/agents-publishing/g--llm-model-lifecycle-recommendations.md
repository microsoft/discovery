# Discovery Product: LLM Model Lifecycle Management & Recommendations

This document outlines Discovery's model lifecycle management strategy aligned with Azure OpenAI in Microsoft Foundry policies. 

**GPT-4o 2024-11-20 is deprecated** (as of Nov 20, 2025) and will be **retired June 5, 2026**. Agent v2 availability will enable migration to GPT-5.x.

**Key Strategy:**
- **Existing Customers with GPT-4o access:** Continue GPT-4o 2024-11-20 until Agent v2 support (timeline TBD)
- **New Customers without GPT-4o access:** Deploy GPT-4.1 with [documented limitations](https://github.com/microsoft/discovery/blob/main/4-how-to/6-tools-models-agents/agents-publishing/a--create-agent-definition.md#model-selection-guidelines)
- **Target State:** GPT-5.x with Agent v2 (timeline TBD)

---

## 1. Azure OpenAI Model Lifecycle Management (Microsoft Foundry)

### 1.1 Foundry Model Lifecycle Policy

**GA Model Availability:**
- GA models available for **minimum 12 months**
- After deprecation, existing customers get **additional 6 months**
- New customers cannot deploy deprecated models
- **60-day notice** before GA model retirement
- **30-day notice** before preview model upgrades

**Notification Methods:**
- Azure Resource Health alerts (automated)
- Email to subscription owners
- Service Health advisories

**Reference:** [Azure OpenAI Model Retirements](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/model-retirements?view=foundry-classic&tabs=text)

---

## 2. Model Selection Strategy

### 2.1 Decision Matrix

| Scenario | Recommended Model | Rationale |
|----------|------------------|-----------|
| **Existing Production Users** | GPT-4o 2024-11-20 or GPT-5.x | Continue GPT-4o until GPT-5.x is available with Agent v2|
| **New Customers (with GPT-4o access)** | GPT-4o 2024-11-20 | Use GPT-4o if available in subscription until Agent v2 migration |
| **New Customers (no GPT-4o access)** | GPT-4.1 (2025-04-14) | GPT-4o not available for new deployments; use GPT-4.1 with [documented limitations](https://github.com/microsoft/discovery/blob/main/4-how-to/6-tools-models-agents/agents-publishing/a--create-agent-definition.md#model-selection-guidelines) |
| **Post-Agent v2 Migration** | GPT-5.x (2025-11-13) | Cost savings, performance improvements|
| **Bookshelf** | GPT-4.1 → GPT-5.x | Migrate to GPT-4.1 first, then GPT-5.x later |
| **Cogloop Backend** | GPT-4.1 → GPT-5.x | Start with GPT-4.1, migrate to GPT-5.x later |

### 2.2 Model Comparison

#### GPT-4o 2024-11-20 (Current Production)
- **Pros:**
  - Battle-tested in Discovery production
  - Agent v1 tool execution fully supported
  - Stable until Agent v2 is ready in public preview 

### 2.3 Key Dates

| Model | Version | Deprecation | Retirement | Replacement | Status |
|-------|---------|-------------|------------|-------------|--------|
| **GPT-4o** | 2024-11-20 | Nov 20, 2025 | **Jun 5, 2026** | GPT-5.x | ⚠️ DEPRECATED |
| **GPT-4.1** | 2025-04-14 | Apr 14, 2026 | Oct 14, 2026 | GPT-5.x | ✅ Available |
| **GPT-5.x** | 2025-11-13 | Nov 13, 2026 | May 15, 2027 | - | ✅ Available |

### 2.4 Discovery Timeline (Proposed)

```
January 2026:    Current state - GPT-4o deprecated
TBD:             Agent v2 is available in production
TBD:             Agent v1 support is stopped
```
- 🔄 Establish testing environment for GPT-5.x
- 🔄 Prepare sample agents for Agent v2 migration
- 🔄 Begin Agent v2 preview testing immediately upon release


## 3. Low-Level Guidance on Model Migration

### 3.1 Existing Customers (Production)

**Current Configuration:**
- **Model:** GPT-4o (2024-11-20) - DEPRECATED
- **Agent Framework:** Agent v1
- **Status:** Production stable, functional until TBD

**Migration Option:**

- **Timeline:** Once Agent v2 becomes available
- **Action:** Migrate to Agent v2 + GPT-5.x
- **Benefits:** Earlier access to cost savings, extended runway before GPT-4o retirement

**Hard Deadline:**
- **TBD:** Agent v1 support is stopped 

### 3.2 New Customer Onboarding

**Scenario 1: New Customer WITH GPT-4o Access (Recommended)**

**Configuration:**
- **Model:** GPT-4o (2024-11-20)
- **Agent Framework:** Agent v1
- **Status:** Use if GPT-4o is accessible through customer's Azure subscription
- **Benefits:** Battle-tested, reliable tool execution, stable until Agent v1 support is stopped

**Migration Path:**
- Same as existing customers - migrate to Agent v2 + GPT-5.x before Agent v1 support is stopped

**Scenario 2: New Customer WITHOUT GPT-4o Access**

**Configuration:**
- **Model:** GPT-4.1 (2025-04-14)
- **Agent Framework:** Agent v1
- **Status:** Temporary configuration if GPT-4o not available for new deployments

**Known Limitations:**
- Tool execution reliability concerns with GPT-4.1 on Agent v1
- See [Model Selection Guidelines](https://github.com/microsoft/discovery/blob/main/4-how-to/6-tools-models-agents/agents-publishing/a--create-agent-definition.md#model-selection-guidelines) for detailed restrictions and workarounds

**Migration Path:**
- New customers will be prioritized for Agent v2 + GPT-5.x upgrade (timeline TBD)

### 3.3 Post-Agent v2

**Target Configuration:**
- **Model:** GPT-5.x (2025-11-13)
- **Agent Framework:** Agent v2
- **Available:** Once Agent v2 is released
- **Benefits:**
  - 30-50% cost reduction vs GPT-4o
  - Enhanced performance and capabilities
  - Extended lifecycle (retires May 2027)
  - Full tool execution support



