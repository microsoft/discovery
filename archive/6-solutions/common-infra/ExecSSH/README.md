# SSH Execution tool

This prototype enables Microsoft Discovery to launch jobs on a remote Linux VM. This prototype works in conjunction with the ANFMCP prototype to enable Discovery to run jobs that are difficult to containerize.

To implement this solution, modify the execssh.py file in the docker/app folder to include the IP address of the VM that will be running the job and include the userid and password for the user that the job will run as.

Within Microsoft Discovery, have the agents help craft the execution script for your HPC tool. Then use the ANFMCP tool to write the execution script to <execution path>/runtool.csh.  The script must be named runtool.csh and contents must start with:  
    *#!/bin/csh*  
    *cd \<working path\>*  

Make sure the VM running the job has <execution path> mounted so both the ANFMCP tool and execssh can refer to the same location.

## Usage Examples

### Example 1: Single Script Execution

Use this prompt to execute a single script on the remote Linux VM:

```
Run runtool.csh on the remote machine. Please check the exit status and report any errors from the execution.
```

This will:
1. Connect to the configured remote Linux VM via SSH
2. Execute the specified script (`<execution path>/runtool.csh`)
3. Capture and return the output and exit status
4. Report any errors encountered during execution

Note: the runtool.csh script must start with:  
    *#!/bin/csh*  
    *cd \<working path\>*  

### Example 2 : Multiple Run Scripts

In order to execute two scripts users can do one of the following:

#### Method 1: Existing Dockerfile and Tool definitions
1. Execute the existing runtool.csh script
2. Use the ANF-S3-MCP Discovery Tool to update runtool.csh with new script contents
3. Execute runtool.csh script again
This can typically be done in one user prompt:
```
First run runtool.csh on the remote machine then update runtool.csh object with "pwd". Finally, run runtol.csh on the remote machine.
```
#### Method 2: Revise the Dockerfile and Tool definitions
Add additional actions to the Tool definition YAML file as well as adding additional python scripts similar to execssh.py. Then an example prompt would be:
```
First run runtool1.csh on the remote machine and then run runtool2.csh.
```
Note: the runtool.csh script must start with:  
    *#!/bin/csh*  
    *cd \<working path\>*  

## Workflow Integration

The execSSHAgent is designed to work seamlessly with other Discovery tools:
- Use **ANFMCP tools** to create and manage script files on shared storage
- Use **execSSHAgent** to execute those scripts on remote compute resources
- Combine both for end-to-end job orchestration and file management

