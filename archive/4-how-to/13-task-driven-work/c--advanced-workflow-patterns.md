# Advanced Workflow Patterns

This guide covers sophisticated workflow patterns for complex scenarios, including conditional flows, iterative loops, cross-group dependencies, dynamic workflows, and large-scale orchestration.

## Prerequisites

Before diving into advanced patterns, you should be familiar with:
- Basic parent-child relationships
- Simple depends-on relationships  
- How cognition executes tasks based on dependencies

See [Task Relationships and Basic Workflows](./b--task-relationships-and-workflows.md) for fundamentals.

## Advanced Dependency Patterns

### Pattern 1: Diamond Dependencies (Fan-Out, Fan-In)

A single task feeds multiple parallel tasks, which then converge into a final task.

```
              📋 Task A: Prepare dataset
                    ↙  ↓  ↘
    📋 Task B:    📋 Task C:    📋 Task D:
    Feature eng.  Exploratory    Data quality
                  analysis       validation
                    ↘  ↓  ↙
              📋 Task E: Synthesize insights
```

**Structure:**
```
🎯 Parent: Data analysis project

Task A: Prepare and clean raw dataset

Task B: Feature engineering and transformation
(Depends on: Task A)

Task C: Exploratory data analysis
(Depends on: Task A)

Task D: Data quality validation
(Depends on: Task A)

Task E: Synthesize findings and recommendations
(Depends on: Task B, Task C, Task D)
```

**When to use:**
- One input needs multiple types of analysis
- Different perspectives on the same data
- Parallel tracks that reconverge
- Maximizing parallelism with shared prerequisites

**Benefits:**
- Efficient: B, C, D run simultaneously
- Clear convergence point at E
- Easy to add/remove parallel tracks

### Pattern 2: Waterfall with Feedback Loops

Sequential phases with ability to return to earlier phases based on results.

```
📋 Phase 1: Design
      ↓
📋 Phase 2: Implement
      ↓
📋 Phase 3: Test
      ↓
📋 Phase 4: Review results
      ↓ (if issues found)
    [Create new tasks that depend on Phase 1]
```

**Implementation:**
```
🎯 Parent: Iterative development cycle

📋 Iteration 1
├─ Task 1.1: Design approach V1
├─ Task 1.2: Implement V1
│   (Depends on: Task 1.1)
├─ Task 1.3: Test V1
│   (Depends on: Task 1.2)
└─ Task 1.4: Evaluate results
    (Depends on: Task 1.3)

📋 Iteration 2 (created if needed based on 1.4 results)
├─ Task 2.1: Refine design based on V1 feedback
│   (Depends on: Task 1.4)
├─ Task 2.2: Implement V2
│   (Depends on: Task 2.1)
├─ Task 2.3: Test V2
│   (Depends on: Task 2.2)
└─ Task 2.4: Evaluate results
    (Depends on: Task 2.3)
```

**When to use:**
- Experimental or exploratory work
- Unknown number of iterations needed
- Results determine next steps
- Continuous improvement cycles

**Key technique:**
- Don't create all iterations upfront
- Create next iteration based on results
- Use comments/feedback to signal need for iteration

### Pattern 3: Conditional Branching

Different paths based on results of earlier tasks.

```
📋 Task A: Assess feasibility
      ↓
   Decision
   ↙    ↘
📋 Path 1:    📋 Path 2:
If feasible   If not feasible
Full impl.    Alternative
              approach
```

**Implementation:**
```
🎯 Parent: Evaluate and implement solution

Task A: Feasibility assessment of quantum approach

Task B: Full quantum implementation
(Depends on: Task A)
Description: "Only proceed if Task A shows >70% confidence 
in feasibility"

Task C: Classical alternative implementation  
(Depends on: Task A)
Description: "Proceed if Task A shows quantum approach is 
infeasible or too risky"

Task D: Hybrid approach evaluation
(Depends on: Task A)
Description: "Proceed if Task A shows mixed results"
```

**When to use:**
- Path forward depends on findings
- Multiple possible approaches
- Risk mitigation strategies
- Exploratory research with fallback options

**Implementation notes:**
- Create all potential paths upfront
- Use task descriptions and comments to indicate conditions
- Mark irrelevant paths as "Cancelled" after decision
- Cognition will see results and comments to guide execution

### Pattern 4: Cascade Dependencies (Chain of Chains)

Multiple sequential chains that start at different times.

```
📋 Chain A1 → A2 → A3 → A4
                ↘
📋 Chain B1 → B2 → B3 → B4
      ↓           ↘
📋 Chain C1 → C2 → C3 → C4
```

**Structure:**
```
🎯 Parent: Multi-phase research program

# Chain A: Literature foundation
Task A1: Systematic literature review
Task A2: Extract key findings (Depends on: A1)
Task A3: Identify research gaps (Depends on: A2)
Task A4: Document literature foundation (Depends on: A3)

# Chain B: Experimental design (starts after A2)
Task B1: Design initial experiments (Depends on: A2)
Task B2: Pilot experiments (Depends on: B1)
Task B3: Refine experimental protocol (Depends on: B2)
Task B4: Run full experiment suite (Depends on: B3)

# Chain C: Theoretical modeling (starts after A3 and uses B3)
Task C1: Develop theoretical model (Depends on: A3)
Task C2: Implement computational model (Depends on: C1)
Task C3: Validate against experimental data (Depends on: C2, B3)
Task C4: Refine model based on validation (Depends on: C3)
```

**When to use:**
- Complex projects with multiple workstreams
- Staggered start times based on prerequisites
- Dependencies both within and across chains
- Long-running programs with multiple phases

**Benefits:**
- Clear sequential logic within each chain
- Explicit cross-chain dependencies
- Parallelism where possible
- Realistic modeling of complex workflows

## Group-Level Patterns

### Pattern 5: Sequential Group Dependencies

Entire groups must complete before the next group starts.

```
🎯 Parent: Drug discovery pipeline

📋 Group 1: Target identification
├─ Task 1.1: Literature review of disease pathways
├─ Task 1.2: Protein target identification  
├─ Task 1.3: Target validation studies
└─ Task 1.4: Select lead targets for screening

📋 Group 2: Compound screening
├─ Task 2.1: Design screening assay
├─ Task 2.2: Screen compound library
├─ Task 2.3: Hit identification and validation
└─ Task 2.4: Select lead compounds
(Depends on: All tasks in Group 1)

📋 Group 3: Lead optimization
├─ Task 3.1: Structure-activity relationship studies
├─ Task 3.2: Medicinal chemistry optimization
├─ Task 3.3: ADMET profiling
└─ Task 3.4: Select development candidates
(Depends on: All tasks in Group 2)

📋 Group 4: Preclinical development
├─ Task 4.1: Toxicology studies
├─ Task 4.2: Pharmacokinetic studies
├─ Task 4.3: Efficacy studies in animal models
└─ Task 4.4: IND preparation
(Depends on: All tasks in Group 3)
```

**Implementation technique:**
- Use parent tasks to represent groups
- Add dependencies between parent tasks
- Or make tasks in Group N depend on a key final task from Group N-1

**When to use:**
- Stage-gate processes
- Pipeline workflows where stages must complete fully
- Compliance-driven workflows
- When later stages need comprehensive results from earlier stages

### Pattern 6: Parallel Groups with Shared Dependencies

Multiple independent workstreams that share some dependencies.

```
🎯 Parent: Multi-modal analysis

📋 Common: Data collection and prep
├─ Task 0.1: Collect raw data
└─ Task 0.2: Standardize formats
    (Depends on: Task 0.1)

📋 Track A: Genomic analysis
├─ Task A1: Sequence alignment (Depends on: Task 0.2)
├─ Task A2: Variant calling (Depends on: A1)
└─ Task A3: Functional annotation (Depends on: A2)

📋 Track B: Transcriptomic analysis
├─ Task B1: Expression quantification (Depends on: Task 0.2)
├─ Task B2: Differential expression (Depends on: B1)
└─ Task B3: Pathway enrichment (Depends on: B2)

📋 Track C: Proteomic analysis
├─ Task C1: Protein identification (Depends on: Task 0.2)
├─ Task C2: Quantification (Depends on: C1)
└─ Task C3: Post-translational modifications (Depends on: C2)

📋 Integration: Multi-omics integration
├─ Task I1: Cross-modal correlation (Depends on: A3, B3, C3)
├─ Task I2: Network analysis (Depends on: I1)
└─ Task I3: Biological interpretation (Depends on: I2)
```

**When to use:**
- Multiple analysis types on same data
- Different teams/experts working in parallel
- Modular workflows with final integration
- Maximizing parallelism while sharing setup

**Benefits:**
- Avoids duplicating shared prerequisites
- Clear separation of concerns
- Natural integration point at the end
- Easy to add/remove tracks

### Pattern 7: Inter-Group Dependencies (Cross-Talk)

Groups aren't fully sequential but have specific inter-dependencies.

```
🎯 Parent: Software system development

📋 Group A: Backend API
├─ Task A1: Design API schema
├─ Task A2: Implement core endpoints
├─ Task A3: Add authentication
└─ Task A4: Performance optimization

📋 Group B: Frontend UI
├─ Task B1: Design UI mockups
├─ Task B2: Implement basic components
│   (Depends on: A1)  ← Needs API schema
├─ Task B3: Add API integration
│   (Depends on: A2)  ← Needs endpoints to exist
└─ Task B4: Polish and responsive design

📋 Group C: Database layer
├─ Task C1: Design database schema
├─ Task C2: Set up database infrastructure
│   (Depends on: C1)
├─ Task C3: Implement ORM models
│   (Depends on: A1)  ← Needs API schema
└─ Task C4: Add indexing and optimization

📋 Group D: Testing and deployment
├─ Task D1: Unit tests
│   (Depends on: A2, B2, C2)
├─ Task D2: Integration tests
│   (Depends on: A3, B3, C3)
├─ Task D3: End-to-end tests
│   (Depends on: A4, B4, C4)
└─ Task D4: Deploy to production
    (Depends on: D3)
```

**When to use:**
- Complex projects with interdependent components
- Multiple teams that need to coordinate
- Workflows where some aspects can proceed in parallel while others have specific ordering
- Realistic software/engineering projects

**Key principle:**
- Dependencies should reflect actual technical requirements
- Allows maximum parallelism while ensuring prerequisites
- Makes coordination points explicit

## Dynamic Workflow Patterns

### Pattern 8: Progressive Elaboration

Start with high-level tasks; cognition or user adds detail as work progresses.

**Initial state:**
```
🎯 Parent: Investigate anomaly in production system

📋 Task 1: Gather diagnostic information

📋 Task 2: Identify root cause
(Depends on: Task 1)

📋 Task 3: Implement fix
(Depends on: Task 2)
```

**After Task 1 completes, cognition or user adds:**
```
🎯 Parent: Investigate anomaly in production system

📋 Task 1: Gather diagnostic information [COMPLETED]
├─ Task 1.1: Log analysis [COMPLETED]
├─ Task 1.2: Metrics review [COMPLETED]
└─ Task 1.3: User report analysis [COMPLETED]

📋 Task 2: Identify root cause [IN PROGRESS]
├─ Task 2.1: Reproduce issue in staging
├─ Task 2.2: Analyze database query performance
└─ Task 2.3: Review recent code changes

📋 Task 3: Implement fix
(Depends on: Task 2)
```

**When to use:**
- Exploratory work where path isn't clear upfront
- Investigations where findings guide next steps
- Agile workflows that adapt based on results
- When you want cognition to propose decomposition

**Benefits:**
- Don't over-plan too early
- Adapt based on actual findings
- Balance structure with flexibility
- Cognition can suggest decomposition

### Pattern 9: Incremental Expansion

Add new branches based on discoveries during execution.

```
🎯 Parent: Optimize chemical synthesis

📋 Core tasks (defined initially)
├─ Task 1: Literature review
├─ Task 2: Baseline synthesis
└─ Task 3: Measure yield and purity

📋 Optimization A (added after Task 3 shows low yield)
├─ Task A1: Investigate solvent alternatives
├─ Task A2: Test temperature variations
└─ Task A3: Evaluate catalyst loading
    (All depend on: Task 3)

📋 Optimization B (added after Task 3 shows purity issues)
├─ Task B1: Add purification step
├─ Task B2: Optimize recrystallization
└─ Task B3: Consider chromatography
    (All depend on: Task 3)

📋 Final evaluation (added after optimizations)
Task 4: Compare optimized routes and select best
(Depends on: Optimization A, Optimization B)
```

**When to use:**
- Open-ended research
- Troubleshooting and debugging
- Optimization problems
- When specific issues emerge during execution

**Technique:**
- Start with core/essential tasks
- Add new tasks/groups as you discover issues or opportunities
- New tasks depend on completed tasks that revealed the need
- Use comments to document why new tasks were added

### Pattern 10: Matrix/Grid Workflows

Test combinations of variables systematically.

```
🎯 Parent: Hyperparameter optimization for ML model

📋 Setup
Task S1: Prepare training dataset
Task S2: Define evaluation metrics
Task S3: Set up training infrastructure

📋 Grid experiments (all depend on Setup)

# Learning rate variations
Task E1.1: LR=0.001, Batch=32, Layers=2 (Depends on: S3)
Task E1.2: LR=0.001, Batch=32, Layers=4 (Depends on: S3)
Task E1.3: LR=0.001, Batch=64, Layers=2 (Depends on: S3)
Task E1.4: LR=0.001, Batch=64, Layers=4 (Depends on: S3)

Task E2.1: LR=0.01, Batch=32, Layers=2 (Depends on: S3)
Task E2.2: LR=0.01, Batch=32, Layers=4 (Depends on: S3)
Task E2.3: LR=0.01, Batch=64, Layers=2 (Depends on: S3)
Task E2.4: LR=0.01, Batch=64, Layers=4 (Depends on: S3)

# (more combinations...)

📋 Analysis
Task A1: Compare all results (Depends on: All E tasks)
Task A2: Identify best configuration (Depends on: A1)
Task A3: Statistical significance testing (Depends on: A1)
```

**When to use:**
- Systematic exploration of parameter space
- A/B or multivariate testing
- Experimental design with controlled variables
- Reproducible benchmarking

**Optimization:**
- All grid experiments can run in parallel
- Single convergence point for analysis
- Easy to add/remove combinations
- Consider grouping related experiments

## Large-Scale Orchestration

### Pattern 11: Multi-Project Coordination

Coordinate multiple related projects that share resources or dependencies.

```
🎯 Super-Parent: Launch new product line

  🎯 Project A: Product development
  ├─ Group A1: Requirements and design
  ├─ Group A2: Engineering and testing
  └─ Group A3: Quality assurance
  
  🎯 Project B: Manufacturing setup
  ├─ Group B1: Facility preparation
  ├─ Group B2: Equipment procurement
  │   (Depends on: Group A1)  ← Needs specs
  └─ Group B3: Production trial runs
      (Depends on: Group A2)  ← Needs product
  
  🎯 Project C: Marketing and sales
  ├─ Group C1: Market research
  ├─ Group C2: Campaign development
  │   (Depends on: Group A1)  ← Needs product details
  ├─ Group C3: Sales training
  │   (Depends on: Group A2)  ← Needs working product
  └─ Group C4: Launch event
      (Depends on: Group B3, Group C3)
  
  🎯 Project D: Distribution and logistics
  ├─ Group D1: Distribution channel setup
  ├─ Group D2: Inventory system
  │   (Depends on: Group A1)
  └─ Group D3: Fulfillment preparation
      (Depends on: Group B3)
```

**When to use:**
- Enterprise-scale initiatives
- Multiple teams/departments
- Complex programs with many workstreams
- Strategic initiatives

**Key practices:**
- Use hierarchy (super-parent → projects → groups → tasks)
- Dependencies across projects only at group level
- Clear ownership (assign projects to different leads)
- Regular synchronization points

### Pattern 12: Phased Rollout with Validation Gates

Progress to next phase only after validation succeeds.

```
🎯 Parent: New system deployment

📋 Phase 1: Internal testing
├─ Task 1.1: Deploy to dev environment
├─ Task 1.2: Internal team testing
│   (Depends on: 1.1)
├─ Task 1.3: Bug fixes and iteration
│   (Depends on: 1.2)
└─ Task 1.4: Internal validation gate
    (Depends on: 1.3)
    Validation: "All critical bugs resolved, team sign-off"

📋 Phase 2: Limited beta
├─ Task 2.1: Deploy to staging
│   (Depends on: 1.4)
├─ Task 2.2: Beta user onboarding
│   (Depends on: 2.1)
├─ Task 2.3: Monitor metrics and gather feedback
│   (Depends on: 2.2)
└─ Task 2.4: Beta validation gate
    (Depends on: 2.3)
    Validation: "Success metrics met, positive feedback"

📋 Phase 3: Gradual production rollout
├─ Task 3.1: Deploy to 10% of users
│   (Depends on: 2.4)
├─ Task 3.2: Monitor for issues (24h)
│   (Depends on: 3.1)
├─ Task 3.3: Deploy to 50% of users
│   (Depends on: 3.2)
├─ Task 3.4: Monitor for issues (24h)
│   (Depends on: 3.3)
├─ Task 3.5: Deploy to 100% of users
│   (Depends on: 3.4)
└─ Task 3.6: Post-deployment validation
    (Depends on: 3.5)

📋 Phase 4: Post-launch
├─ Task 4.1: Performance optimization
│   (Depends on: 3.6)
└─ Task 4.2: Documentation and training
    (Depends on: 3.6)
```

**When to use:**
- Risk mitigation for deployments
- Compliance requirements
- Gradual rollouts
- When failure at one stage should prevent progression

**Key elements:**
- Explicit validation tasks as gates
- Clear validation requirements
- Dependencies ensure gates are respected
- Rollback plans (additional tasks if validation fails)

## Advanced Techniques

### Technique 1: Checkpoint Tasks

Create explicit checkpoint tasks for synchronization and validation.

```
🎯 Parent: Complex analysis pipeline

📋 Multiple parallel analyses...
Task A1, A2, A3, A4, A5 (all running in parallel)

📋 CHECKPOINT: Validate all analyses complete and consistent
(Depends on: A1, A2, A3, A4, A5)
Validation Requirements:
- All analyses completed successfully
- Results are consistent with each other
- No data quality issues detected
- Ready to proceed to synthesis

📋 Synthesis and reporting...
Task B1, B2, B3 (all depend on: CHECKPOINT)
```

**Purpose:**
- Explicit validation point
- Ensures quality before proceeding
- Clear synchronization for parallel work
- Opportunity for human review

### Technique 2: Priority-Based Execution

Use task priorities to guide cognition's attention.

```
🎯 Parent: Research project

# High priority: Critical path
Task A1 [Priority: High]: Core experiments
Task A2 [Priority: High]: Data analysis (Depends on: A1)

# Medium priority: Supporting work
Task B1 [Priority: Medium]: Literature review
Task B2 [Priority: Medium]: Method development

# Low priority: Nice to have
Task C1 [Priority: Low]: Additional validation
Task C2 [Priority: Low]: Supplementary figures
```

**When combined with dependencies:**
- Cognition prioritizes high-priority tasks when multiple tasks are ready
- Can work on lower-priority tasks when higher-priority tasks are blocked
- Helps focus resources on critical path

### Technique 3: Optional Dependencies

Use task descriptions to indicate "soft" dependencies.

```
Task A: Main analysis

Task B: Supplementary analysis
Description: "Can run independently, but results may inform Task A. 
Consider running in parallel and incorporating insights if Task A 
is still in progress."

Task C: Extended analysis
(Depends on: Task A)
Description: "Optional: only proceed if Task A shows interesting 
results worth deeper investigation"
```

**Purpose:**
- Flexibility in execution
- Optional paths that may be skipped
- Guidance without hard constraints

### Technique 4: Batch Dependencies

Group tasks that share common dependencies to simplify structure.

```
🎯 Parent: Multi-target drug screening

📋 Preparation (shared by all)
Task P1: Prepare compound library
Task P2: Standardize assay conditions

📋 Batch 1: Targets A-E
├─ Task 1A: Screen target A (Depends on: P1, P2)
├─ Task 1B: Screen target B (Depends on: P1, P2)
├─ Task 1C: Screen target C (Depends on: P1, P2)
├─ Task 1D: Screen target D (Depends on: P1, P2)
└─ Task 1E: Screen target E (Depends on: P1, P2)

📋 Batch 2: Targets F-J
├─ Task 2F: Screen target F (Depends on: P1, P2)
├─ Task 2G: Screen target G (Depends on: P1, P2)
├─ Task 2H: Screen target H (Depends on: P1, P2)
├─ Task 2I: Screen target I (Depends on: P1, P2)
└─ Task 2J: Screen target J (Depends on: P1, P2)
```

**Benefits:**
- Cleaner than individual dependencies from P1, P2 to every task
- Easy to see what's shared vs. batch-specific
- Scales well with many similar tasks

## Real-World Complex Example

Let's put it all together with a realistic complex workflow:

### Scenario: Novel Protein Engineering Project

```
🎯 SUPER-PARENT: Engineer novel enzyme with enhanced stability

  🎯 PROJECT 1: Computational design [Priority: High]
  
    📋 Phase 1.1: Target analysis
    ├─ Task 1.1.1: Structural analysis of wild-type enzyme
    ├─ Task 1.1.2: Identify stability-limiting regions
    │   (Depends on: 1.1.1)
    └─ Task 1.1.3: Literature review of stabilization strategies
    
    📋 Phase 1.2: Variant design
    ├─ Task 1.2.1: Generate initial variant library
    │   (Depends on: 1.1.2, 1.1.3)
    ├─ Task 1.2.2: Computational stability prediction
    │   (Depends on: 1.2.1)
    └─ Task 1.2.3: Select top 20 variants for synthesis
        (Depends on: 1.2.2)
        Validation: "Predicted ΔΔG > 5 kcal/mol"
    
    📋 CHECKPOINT 1: Design review and approval
    (Depends on: Phase 1.2)
    
  🎯 PROJECT 2: Experimental validation [Priority: High]
  
    📋 Phase 2.1: Gene synthesis and expression
    ├─ Task 2.1.1: Order gene synthesis for top 20 variants
    │   (Depends on: CHECKPOINT 1)
    ├─ Task 2.1.2: Clone into expression vectors
    │   (Depends on: 2.1.1)
    ├─ Task 2.1.3: Transform and express in E. coli
    │   (Depends on: 2.1.2)
    └─ Task 2.1.4: Purify protein variants
        (Depends on: 2.1.3)
    
    📋 Phase 2.2: Initial characterization (parallel tracks)
    
    Track A: Activity assays
    ├─ Task 2.2.A1: Establish assay conditions
    │   (Depends on: 2.1.4)
    ├─ Task 2.2.A2: Measure activity of all variants
    │   (Depends on: 2.2.A1)
    └─ Task 2.2.A3: Compare to wild-type
        (Depends on: 2.2.A2)
    
    Track B: Stability assays
    ├─ Task 2.2.B1: Thermal stability (DSF)
    │   (Depends on: 2.1.4)
    ├─ Task 2.2.B2: Chemical stability
    │   (Depends on: 2.1.4)
    └─ Task 2.2.B3: Long-term storage stability
        (Depends on: 2.1.4)
    
    Track C: Structural characterization
    ├─ Task 2.2.C1: Crystallization trials
    │   (Depends on: 2.1.4)
    ├─ Task 2.2.C2: X-ray data collection
    │   (Depends on: 2.2.C1)
    └─ Task 2.2.C3: Structure determination
        (Depends on: 2.2.C2)
    
    📋 CHECKPOINT 2: Select lead variants
    (Depends on: Track A, Track B, Track C)
    Task: "Down-select to top 3 variants based on activity 
    and stability"
    Validation: "At least 2 variants show >2x improvement"
    
  🎯 PROJECT 3: Optimization [Priority: Medium]
  (Only proceeds if CHECKPOINT 2 passes)
  
    📋 Phase 3.1: Further improvements
    ├─ Task 3.1.1: Design second-generation variants
    │   (Depends on: CHECKPOINT 2, Task 2.2.C3)
    ├─ Task 3.1.2: Combine beneficial mutations
    │   (Depends on: 3.1.1)
    └─ Task 3.1.3: Test combinatorial variants
        (Depends on: 3.1.2)
    
    📋 Phase 3.2: Optimization iterations
    [Progressive elaboration: Add tasks based on 3.1.3 results]
    
  🎯 PROJECT 4: Production and formulation [Priority: Medium]
  (Starts after CHECKPOINT 2)
  
    📋 Phase 4.1: Scale-up
    ├─ Task 4.1.1: Optimize expression in lead variants
    │   (Depends on: CHECKPOINT 2)
    ├─ Task 4.1.2: Scale to fermentor
    │   (Depends on: 4.1.1)
    └─ Task 4.1.3: Optimize purification protocol
        (Depends on: 4.1.2)
    
    📋 Phase 4.2: Formulation
    ├─ Task 4.2.1: Test stabilizers and excipients
    │   (Depends on: 4.1.3)
    ├─ Task 4.2.2: Optimize buffer conditions
    │   (Depends on: 4.1.3)
    └─ Task 4.2.3: Long-term stability studies
        (Depends on: 4.2.1, 4.2.2)
    
  🎯 PROJECT 5: Documentation and IP [Priority: Low]
  (Can start early but finalize at end)
  
    📋 Phase 5.1: Documentation (parallel with experiments)
    ├─ Task 5.1.1: Maintain lab notebook
    │   (Ongoing, no dependencies)
    ├─ Task 5.1.2: Document protocols
    │   (Ongoing, updated as protocols are finalized)
    
    📋 Phase 5.2: Intellectual property
    ├─ Task 5.2.1: Prior art search
    │   (Depends on: CHECKPOINT 1)
    ├─ Task 5.2.2: Draft patent application
    │   (Depends on: CHECKPOINT 2, Task 5.2.1)
    └─ Task 5.2.3: File provisional patent
        (Depends on: 5.2.2)
    
    📋 Phase 5.3: Publication
    ├─ Task 5.3.1: Draft manuscript
    │   (Depends on: PROJECT 3)
    ├─ Task 5.3.2: Prepare figures and supplementary info
    │   (Depends on: 5.3.1)
    └─ Task 5.3.3: Submit to journal
        (Depends on: 5.3.2, Task 5.2.3)
```

**Analysis of this workflow:**

- **5 major projects** with different priorities
- **15+ phases/groups** organizing related work
- **50+ individual tasks** (many more would be added via progressive elaboration)
- **Multiple dependency types**:
  - Sequential (within phases)
  - Parallel (characterization tracks)
  - Cross-project (CHECKPOINT 2 → Projects 3 & 4)
  - Conditional (Project 3 only if checkpoint passes)
- **Validation gates** at key decision points
- **Different timeframes** (some ongoing, some sequential)
- **Mix of computational and experimental** work
- **IP and documentation** running in parallel with science

## Best Practices for Advanced Workflows

### 1. Start Simple, Add Complexity Gradually
- Begin with major phases
- Add detail progressively as work starts
- Don't over-plan too early

### 2. Use Consistent Naming Conventions
- Clear task titles that indicate what/where in workflow
- Number/label groups logically (Phase 1.1, Phase 1.2, etc.)
- Use prefixes to show relationships

### 3. Document the Logic
- Use task descriptions to explain dependencies
- Add comments explaining workflow decisions
- Note conditions for conditional branches

### 4. Balance Structure and Flexibility
- Provide enough structure to guide cognition
- Leave room for adaptation based on results
- Don't over-constrain

### 5. Regular Review and Pruning
- Mark completed tasks as done
- Cancel tasks that become irrelevant
- Adjust priorities based on new information

### 6. Use Checkpoints and Validation Gates
- Explicit validation tasks at key points
- Clear validation requirements
- Opportunity for human review before major commitments

### 7. Visualize the Flow
- Draw it out (at least mentally)
- Ensure the logic makes sense
- Check for bottlenecks or over-constraints

### 8. Test the Critical Path
- Identify longest sequence of dependent tasks
- Focus validation requirements on critical path
- Consider parallel alternatives for bottlenecks

## Common Advanced Anti-Patterns

### ❌ The Mega-Hierarchy
Don't create 7+ levels of nesting. Keep hierarchies shallow (2-3 levels).

### ❌ The Dependency Web
Don't create dependencies between every pair of tasks. Only dependencies that reflect real prerequisites.

### ❌ The Over-Planner
Don't try to plan every detail upfront for long projects. Use progressive elaboration.

### ❌ The Under-Constrainer
Don't forget dependencies that actually exist. Missing dependencies can cause wasted work.

### ❌ The False Checkpoint
Don't create validation gates without clear criteria. Vague checkpoints don't help.

### ❌ The Orphaned Branch
Don't create entire branches that don't feed back to main workflow. Every task should contribute to overall objective.

## Tools and Techniques for Managing Complexity

### Technique: Swim Lanes
Organize parallel workstreams by assigning to different groups/people:
- Track A: Computational team
- Track B: Experimental team
- Track C: Analysis team

### Technique: Milestone Tracking
Create milestone tasks that aggregate progress:
```
📋 MILESTONE: First quarter objectives
(Virtual task that depends on: T1, T5, T9, T15)
```

### Technique: Resource Tagging
Use task descriptions to tag resource requirements:
```
Description: "Requires: GPU cluster, ~24h compute time, 
budget: $500"
```

### Technique: Risk Mitigation
Add fallback tasks for high-risk activities:
```
Task A: Primary approach [Priority: High]
Task B: Backup approach [Priority: Low]
Description: "Only pursue if Task A fails"
```

## Next Steps

- Review [basic workflow patterns](./b--task-relationships-and-workflows.md) if any concepts are unclear
- See [Working with Tasks and Engine](./a--working-with-tasks-and-engine.md) for general principles
- See [Tasks concept](../../3-concepts/tasks.md) for complete field reference
- Start with simple patterns and gradually incorporate advanced techniques as needed

## Summary

Advanced workflow patterns enable sophisticated orchestration of complex, multi-faceted work:

- **Diamond dependencies** maximize parallelism with fan-out/fan-in
- **Conditional branching** adapts paths based on results
- **Group-level patterns** organize work at scale
- **Progressive elaboration** adds detail as you learn
- **Validation gates** ensure quality and manage risk
- **Cross-project dependencies** coordinate large initiatives

The key is finding the right balance: enough structure to guide cognition effectively, but enough flexibility to adapt based on what you discover. Start with simple patterns, add complexity only where it provides value, and let cognition help you navigate the execution.
