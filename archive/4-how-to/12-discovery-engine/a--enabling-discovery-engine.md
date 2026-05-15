# Enabling Discovery Engine

This guide explains how to enable Discover Mode in an investigation and view progress in Tasks view.


## What is Discovery Engine?

Microsoft Discovery Engine is a feature within Discovery that acts and behaves like a colleague you can converse with, delegate to, cooperatively plan with, and hand off tasks to when working on ambitious long-duration work.  The Discovery Engine is organized and driven by the purpose of the work you want to accomplish, using the rest of Discovery as resources to accomplish it. [Concepts - Discovery Engine](../../3-concepts/engine.md)

The two main components of the Engine are Cognition and Tasks.  These two components work in tandem with cognition maintaining awareness and continually managing the work to be done while Tasks organizes and captures our intent and work progress. [Concepts - Cognition](../../3-concepts/cognition.md), [Concepts - Tasks](../../3-concepts/tasks.md)


## Prerequisites

Before using the Discovery Engine in Microsoft Discovery, ensure you have:
 - New Discovery Workspace deployed. Discovery Engine is not enabled for workspaces deployed before 2512.2 release. 
 - Increase TPM quota for the model deployment used by Discovery Engine. [Quota reservations - Azure OpenAI](../2-onboarding-experience/b--quota-reservations.m)
 - Simple agents and workflows definitions. Avoid the use of advanced router logic. [Agent Definitions](../6-tools-models-agents/agents-publishing/a--create-agent-definition.md)

## Working with Discovery Engine

### Step 1: Select Discover Mode in an investigation

1. Create a new investigation or open an existing one. [Investigations](/4-how-to/8-investigations/a--creating-investigation.md)
2. Select Discover Mode from the drop down. 
3. Input a big-picture goal and press Enter
4. Monitor the tasks that Discovery Engine creates under tasks. 


### Step 2: Monitor Task Progress

1. Expand the investigation and select tasks
2. Discover Mode creates a new task with the goal provided. New tasks are set to New status. 
3. The Discovery Engine automatically starts in the background and will begin process outstanding tasks
4. Discovery Engine reasons over the tasks and assigns them to an agent
5. Task execution is then initated by the Discovery Engine and the status for the task changes to Executing
6. Upon completion, the task status will change to ExecutionDone and the system provides the results to Discovery Engine
7. Discovery Engine will set the task to Complete when it completes any validation requirements

### Step 3: View Results
1. Open investigation. Discover Mode should already be selected.
2. Under "Task Completed Successfully", review the high level goal and results provided by the Discovery Engine
3. Expand the investigation and select tasks
4. Select a task to review the notes provided by added by the Discovery Engine, agents, task manager
5. Scroll to the bottom of the task to see associated logs

### Step 4: Stop Discovery Engine
After all tasks are completed in an investigation, the Discovery Engine continues to run and ready to process goals or tasks provided. If the investigation has reached the end of its lifecycle and will remain for reference purposes, make sure to stop the Discovery Engine to avoid unecessary billing.
1. Select Tasks in the Activity Bar. If the Tasks icon is not visible, right click on the Activty Bar and select Tasks.
2. Select the investigation from the drop down
3. Click on the red button next to the drop down to stop the Discovery Engine
4. If a new goal is submitted in the investigation, the Discovery Engine will start again. No need to manually start it. 


## Best Practices

[Tips for effective use]
 - Problems that are multi-faceted, have open-ended solutions, and will take a long time to solve are all ideal uses of the Discovery Engine.
 - Relatively simple queries where a rapid response is desired are less ideal.  
 - Stop cognition once an investigation reaches the end of its lifecycle

## Related Topics

[Links to related documentation]

- [Concept: Discovery Engine](../../3-concepts/engine.md)
- [Concept: Tasks](../../3-concepts/tasks.md)
- [Create and Run an Investigation](../8-investigations/a--creating-investigation.md)