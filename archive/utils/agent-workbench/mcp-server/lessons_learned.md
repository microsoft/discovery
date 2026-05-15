# Lessons Learned

This file tracks important information, best practices, and mistakes to avoid across sessions.
It helps prevent repeated errors and improves efficiency over time.

## Format
Each entry should include:
- **Date**: When the lesson was learned
- **Category**: Topic area (e.g., ChEMBL API, Job Submission, Configuration)
- **Lesson**: What was learned
- **Context**: Relevant details or examples

---

## 2025-11-08 - ChEMBL API Design

**Lesson**: Convert Python APIs to keyword-only arguments to prevent positional argument confusion

**Context**:
- Multiple ChEMBL job failures occurred due to confusion between positional and keyword arguments
- Root cause: Methods accepted both positional and keyword arguments, leading to incorrect usage
- Solution: Added `*` separator after `self` in all public methods: `def method(self, *, arg1: str, arg2: int = 10):`
- Effect: All arguments after `*` must be passed as keywords

**Implementation**:
- Updated 11 methods in chembl_utils.py with keyword-only signature
- Pattern: `def search_targets(self, *, query: str, limit: int = 500)`
- Fixed internal calls to use keyword syntax

**Impact**: 
- Prevents TypeError from positional argument usage
- Makes API calls self-documenting and more maintainable
- Reduces debugging time for API misuse

---

## 2025-11-08 - ChEMBL Bioactivity Data Structure

**Lesson**: Always verify API return types and document tuple unpacking

**Context**:
- `get_bioactivities_for_target()` returns a tuple: `(activities_list, total_count)`
- Initial test code only unpacked one value: `activities = utils.get_bioactivities_for_target(...)`
- This caused activities to be a tuple instead of a list
- Field access failed because tuple structure wasn't unpacked properly

**Correct Usage**:
```python
# ✅ Correct - unpack tuple
activities, total_count = utils.get_bioactivities_for_target(
    target_chembl_id=target_id,
    limit=100
)

# ❌ Wrong - missing unpacking
activities = utils.get_bioactivities_for_target(
    target_chembl_id=target_id,
    limit=100
)
```

**Impact**: 
- Prevents confusion about data structure
- Makes total count available for reporting
- Enables proper data validation

---

## 2025-11-08 - Job Status Monitoring

**Lesson**: Head and tail logs provide better context than tail-only logs for long-running jobs

**Context**:
- Long-running ChEMBL job (processing 3257 ligands) took 30+ minutes
- With only last 20 lines of logs, couldn't see job initialization or overall progress
- Solution: Modified `get_job_status` to return first N + last N lines

**Implementation**:
- Added `log_lines` parameter (default: 20)
- Fetches full logs, extracts head and tail
- Inserts truncation marker: `... [N lines truncated] ...`

**Benefits**:
- HEAD shows: Job parameters, initialization, total items to process
- TAIL shows: Current progress, recent activity, latest status
- Together: Complete picture of job health and progress

**Example Output**:
```
Log line 1: Target: CHEMBL203 (human EGFR)
Log line 2: Found 3,257 unique ligands to process
...
Log line 20: Step 2: Fetching compounds...

... [2030 lines truncated] ...

Log line 2051: Progress: 2070/3257 ligands (63.5%)
...
Log line 2070: ✓ Retrieved compound information
```

**Impact**: 
- Immediate visibility into job progress
- Can determine if job is healthy or stuck
- Reduces unnecessary job cancellations

---

## 2025-11-08 - Local Testing vs Remote Execution

**Lesson**: Always test API changes locally before submitting to Azure Discovery platform

**Context**:
- Azure Discovery jobs can take significant time (30+ minutes for large datasets)
- Authentication tokens may expire during long-running jobs
- Local testing is immediate and doesn't consume Azure resources

**Best Practice**:
- Create local test scripts using ChEMBL utils directly
- Test with small datasets (limit=100) for quick validation
- Only submit to Azure after local validation passes
- Use `python test_script.py` for instant feedback

**Example**:
```python
# Local test - runs in seconds
from chembl_utils import ChEMBLUtils
utils = ChEMBLUtils()
activities, total = utils.get_bioactivities_for_target(
    target_chembl_id="CHEMBL203",
    limit=100
)
print(f"✅ Retrieved {len(activities)} activities")
```

**Impact**:
- Faster iteration during development
- Reduced cloud costs
- No authentication issues
- Easier debugging

---

## 2025-11-08 - Emoji Characters in Trace Output

**Lesson**: Emoji characters appear as Unicode escape sequences in JSON/terminal output

**Context**:
- MCP agent workbench uses emojis in trace messages (🚀, ✓, ❌, 📊)
- When displayed in JSON or some terminals, appear as: `\ud83d\ude80`
- This is normal Unicode encoding, not an error

**Appearance**:
```
"\ud83d\ude80 Starting job submission"  # 🚀
"\u2705 Authenticated to Discovery API"  # ✅
"\u274c Failed to cancel job"            # ❌
```

**Options**:
1. Accept as-is (emojis render correctly in most contexts)
2. Replace with ASCII in trace generation code
3. Decode Unicode sequences on display

**Impact**: Cosmetic only - doesn't affect functionality

---

## 2025-11-09 06:49:53 UTC - Agent Workflow Orchestration

## 2025-11-09 - Multi-Agent EGFR Inhibitor Discovery Workflow

**Lesson**: Successfully orchestrated complex multi-step drug discovery workflow using 4 different published agents with automatic job chaining

**Context**:
- Built complete EGFR inhibitor discovery pipeline using ChEMBL, molToolkit, PDBSearch, and ligprepAgent
- Workflow identified congeneric series, analyzed molecular properties, retrieved protein structures, and prepared ligands for docking
- Used automatic job dependencies with `depends_on_job_id` to chain outputs as inputs

**Workflow Steps**:
1. **ChEMBL Agent**: Query human EGFR inhibitors, identify congeneric series (10,000 bioactivities)
2. **molToolkit Agent**: Calculate molecular properties, drug-likeness (Lipinski, QED), rank top 50 compounds
3. **PDBSearch Agent**: Retrieve high-quality EGFR structure (resolution ≤2.5Å, R-free ≤0.25)
4. **ligprepAgent**: Prepare ligands with LigPrep (3D coords, ionization, tautomers, stereoisomers)

**Key Success Factors**:
- Job chaining: Step 2 depends on Step 1 output (automatic input mounting)
- Parallel execution: PDB search ran independently while ChEMBL processed
- Script size optimization: Reduced verbose scripts to fit 12KB limit
- Correct agent names: Use published catalog names (e.g., "molToolkit" not "moltoolkitAgent")

**Agent Name Resolution**:
```python
# ✅ Correct - from agent catalog
agent_name="ChEMBL"        # Published agent
agent_name="molToolkit"    # Published agent  
agent_name="PDBSearch"     # Published agent
agent_name="Schrodinger-LigPrep"  # Schrodinger suite agent

# ❌ Wrong - internal/display names
agent_name="moltoolkitAgent"
agent_name="ligprepAgent"
```

**Script Size Management**:
- Limit: 12,000 characters when base64 encoded
- Solution: Remove verbose comments, docstrings, excessive print statements
- Focus on essential logic and minimal logging
- Break very complex workflows into multiple scripts if needed

**Job Dependency Pattern**:
```python
# Step 1: Independent job
job1 = submit_job(agent_name="ChEMBL", script_path="step1.py")

# Step 2: Depends on Step 1 output
job2 = submit_job(
    agent_name="molToolkit",
    script_path="step2.py",
    depends_on_job_id=job1['discovery_job_id'],
    wait_for_parent=False  # Submit now, will auto-wait for parent
)

# Step 3: Parallel to Steps 1-2
job3 = submit_job(agent_name="PDBSearch", script_path="step3.py")
```

**Critical API Issues Encountered**:
1. ChEMBL utils use keyword-only arguments: `search_targets(query="EGFR", limit=20)`
2. Methods return tuples: `(results, total_count)` - always unpack both values
3. Agent names must match published catalog exactly

**Outputs Produced**:
- Congeneric series of EGFR inhibitors with SAR data
- Top 50 drug-like compounds (Lipinski-compliant, high QED scores)
- High-quality EGFR protein structure (PDB format)
- Prepared ligands ready for molecular docking (Maestro format)

**Impact**:
- Demonstrates end-to-end drug discovery workflow automation
- Reduces manual data transfer between steps (automatic input/output mounting)
- Enables reproducible, scalable compound screening pipelines
- Shows best practices for multi-agent orchestration in Azure Discovery

**Next Applications**:
- Similar multi-step workflows for other targets
- Add grid generation and docking steps (Glide)
- Extend to virtual screening of large compound libraries
- Integrate with downstream MD simulations (Gromacs)


---


## 2025-11-09 07:02:24 UTC - Hybrid Script Submission

## Hybrid Inline/Upload Script Submission Implementation (2025-11-08)

### Problem
Scripts larger than 12KB (base64 encoded) could not be submitted via inline mode due to payload size limits.

### Solution Implemented
Created hybrid submission system in `server.py` that automatically:
- **Scripts ≤12KB encoded:** Use inline mode (base64 in `inlineFiles`, mount at `/inputs/`)
- **Scripts >12KB encoded:** Upload to Azure Blob Storage (mount at `/mnt/scripts/` via `inputData`)

### Implementation Details

**Key Changes in `server.py` (lines 3595-3920):**
1. Size check: `use_script_upload = len(base64_encoded) > 12000`
2. Upload logic:
   - Get storage config from workspace
   - Authenticate with OAuth token
   - Upload to `{run_prefix}/scripts/{script_name}`
   - Build Discovery URI
   - Add inputData mount: `{"mountPath": "/mnt/scripts/", "uri": script_discovery_uri}`
3. Request body construction:
   - Upload mode: `inputData` includes script mount, NO `inlineFiles`
   - Inline mode: `inlineFiles` with base64, `inputData` only for input files
4. Command path adjustment:
   - Upload mode: Replace `/inputs/{script}` with `/mnt/scripts/{script}`
   - Inline mode: Keep original `/inputs/{script}` path
5. Fallback: If upload fails, fall back to inline mode with warning

### Test Scripts Created
```
tests/01_script_size_tests/small_test.py  - 3,544 bytes encoded  → INLINE mode
tests/02_script_size_tests/large_test.py  - 22,672 bytes encoded → UPLOAD mode
```

Both scripts:
- Execute quickly (<1 second)
- Write JSON results to `/output/`
- Include extensive comments for size/documentation
- Detect their submission mode from script location

### Testing Checklist
When MCP tool is enabled, test:
- [ ] Submit small_test.py → verify inline mode, `/inputs/` path
- [ ] Submit large_test.py → verify upload mode, `/mnt/scripts/` path
- [ ] Check server logs for mode selection
- [ ] Verify both jobs complete successfully
- [ ] Check output files contain correct mode detection

### Benefits
- **Automatic**: Threshold-based decision, no user intervention
- **Efficient**: Small scripts avoid storage overhead
- **Scalable**: Large scripts avoid payload limits
- **Resilient**: Falls back to inline if upload fails
- **Fast**: Upload adds ~1-2s, but execution time identical

### Future Enhancements
- Configurable threshold (currently hardcoded at 12000)
- Script caching to avoid re-uploading identical scripts
- Compression for very large scripts


---


## 2025-11-09 07:15:10 UTC - Script Upload Implementation

## Script Upload Command Path Handling (2025-11-09)

### Critical Discovery
Command templates vary across tool definitions:
- web_server.py default: `python "/{{scriptName}}"` (just `/{{scriptName}}`)
- Tool definitions: `python /inputs/{{scriptName}}` (includes `/inputs/`)

### Solution
Smart path replacement that handles both formats:
```python
# Initial format with script name
formatted_command = command_template.replace("{{scriptName}}", script_name)

# If upload mode, update path to /mnt/scripts/
if use_script_upload:
    if f"/inputs/{script_name}" in formatted_command:
        # Tool def format: python /inputs/script.py → python /mnt/scripts/script.py
        formatted_command = formatted_command.replace(f"/inputs/{script_name}", f"/mnt/scripts/{script_name}")
    elif f"/{script_name}" in formatted_command:
        # Web server format: python /script.py → python /mnt/scripts/script.py  
        formatted_command = formatted_command.replace(f"/{script_name}", f"/mnt/scripts/{script_name}")
```

### Key Insights
1. **Template variations**: Different command templates require flexible replacement logic
2. **Mount path**: Scripts folder mounted at `/mnt/scripts/`, not `/mnt/scripts/{filename}`
3. **Discovery URI**: Points to directory (`.../scripts`), not specific file
4. **Order matters**: Check specific pattern (`/inputs/`) before generic pattern (`/`)


---

