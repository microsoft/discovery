#!/usr/bin/env python3
"""
ARM Template Generator for Microsoft Discovery Tools and Agents

This script generates ARM templates for tools and agents based on their definition files
found in the tools-and-models directory structure.
"""

import os
import sys
import json
import subprocess
import yaml
import time
import platform
from pathlib import Path
from typing import Dict, Any, List, Optional


class ARMTemplateGenerator:
    """Generate ARM templates for Discovery Tools and Agents"""
    
    def __init__(self, repo_root: str, subscription_id: str, resource_group: str, 
                 location: str, acr_name: str):
        self.repo_root = Path(repo_root)
        self.subscription_id = subscription_id
        self.resource_group = resource_group
        self.location = location
        self.acr_name = acr_name
        self.tools_dir = self.repo_root / "6-solutions" / "tools-and-models"
        self.is_windows = platform.system() == "Windows"
    
    def _run_command(self, cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
        """
        Run a command with proper Windows/Unix compatibility.
        On Windows with shell=True, commands need to be strings.
        """
        if self.is_windows and kwargs.get('shell', False):
            # On Windows with shell=True, convert list to string
            import shlex
            cmd_str = ' '.join(shlex.quote(arg) for arg in cmd)
            return subprocess.run(cmd_str, **kwargs)
        else:
            return subprocess.run(cmd, **kwargs)
        
    def _load_yaml_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Load and parse a YAML file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"Warning: Could not load {file_path}: {e}")
            return None
    
    def _find_definition_file(self, tool_path: Path, pattern: str) -> Optional[Path]:
        """Find a definition file matching the pattern in the tool directory (case-insensitive)"""
        # For case-insensitive matching, we need to iterate through files manually
        if not tool_path.exists():
            return None
        
        # Convert pattern to lowercase for comparison
        import fnmatch
        pattern_lower = pattern.lower()
        
        for file_path in tool_path.iterdir():
            if file_path.is_file() and fnmatch.fnmatch(file_path.name.lower(), pattern_lower):
                return file_path
        return None
    
    def _find_tool_definition_file(self, tool_path: Path) -> Optional[Path]:
        """Find tool definition file with flexible naming patterns (case-insensitive)"""
        # Try multiple naming patterns in order of preference
        patterns = [
            "*tool-definition.yaml",
            "*tool_definition.yaml",
            "*tools.yaml",
            "*tool.yaml"
        ]
        for pattern in patterns:
            result = self._find_definition_file(tool_path, pattern)
            if result:
                return result
        return None
    
    def _find_agent_definition_file(self, tool_path: Path) -> Optional[Path]:
        """Find agent definition file with flexible naming patterns (case-insensitive)"""
        # Try multiple naming patterns
        patterns = [
            "*agent-definition.yaml",
            "*agent_definition.yaml",
            "*agents.yaml",
            "*agent.yaml"
        ]
        for pattern in patterns:
            result = self._find_definition_file(tool_path, pattern)
            if result:
                return result
        return None
    
    def _convert_tool_definition_to_arm_properties(self, tool_def: Dict[str, Any], 
                                                   tool_name: str, image_name: str) -> Dict[str, Any]:
        """Convert tool definition YAML to ARM template properties"""
        # Extract key information from tool definition
        version = tool_def.get('version', '1.0.0')
        
        # Update ACR image reference in the definition
        if 'infra' in tool_def and isinstance(tool_def['infra'], list):
            for infra_item in tool_def['infra']:
                if 'image' in infra_item and 'acr' in infra_item['image']:
                    # Update with actual ACR and image name
                    infra_item['image']['acr'] = f"{self.acr_name}.azurecr.io/{image_name}"
        
        # Build the properties structure matching the API spec
        properties = {
            "version": version,
            "environmentVariables": {},
            "definitionContent": tool_def
        }
        
        return properties
    
    def _convert_agent_definition_to_arm_properties(self, agent_def: Dict[str, Any],
                                                    tool_resource_ids: List[str]) -> Dict[str, Any]:
        """Convert agent definition YAML to ARM template properties"""
        agent_config = agent_def.get('agent', {})
        
        # Extract core agent properties
        model_name = agent_config.get('model', 'gpt-4o')
        version = agent_def.get('version', '1.0.0')
        
        # Build tools array with resource IDs
        tools = []
        for tool_id in tool_resource_ids:
            tool_name = tool_id.split('/')[-1]
            tools.append({
                "toolId": tool_id,
                "name": tool_name
            })
        
        # Get extension from agent_def root (not from agent config)
        extension = agent_def.get('extension', {})
        
        # Build definition content with agent property (required by API)
        # The agent property must contain all agent-specific fields
        definition_content = {
            "agent": {
                "name": agent_config.get('name', ''),
                "description": agent_config.get('description', ''),
                "model": model_name,
                "instructions": agent_config.get('instructions', ''),
                "top_p": agent_config.get('top_p', 0),
                "temperature": agent_config.get('temperature', 0),
                "response_format": agent_config.get('response_format', 'auto')
            },
            "extension": extension
        }
        
        # Build the properties structure matching the API spec
        properties = {
            "modelName": model_name,
            "version": version,
            "agents": [],  # Can be populated with dependent agents if needed
            "tools": tools,
            "knowledgeBases": [],  # Can be populated with knowledge bases if needed
            "definitionContent": definition_content
        }
        
        return properties
    
    def generate_tool_arm_template(self, tool_name: str, image_name: str) -> Optional[Dict[str, Any]]:
        """Generate ARM template for a tool"""
        tool_path = self.tools_dir / tool_name
        
        # Find tool definition file with flexible naming patterns
        tool_def_file = self._find_tool_definition_file(tool_path)
        if not tool_def_file:
            print(f"Warning: No tool definition file found for {tool_name}")
            return None
        
        # Load tool definition
        tool_def = self._load_yaml_file(tool_def_file)
        if not tool_def:
            return None
        
        # Generate tool resource name (lowercase for ARM)
        tool_resource_name = tool_name.lower().replace('_', '-')
        
        # Convert definition to ARM properties
        properties = self._convert_tool_definition_to_arm_properties(tool_def, tool_name, image_name)
        
        # Build ARM template
        arm_template = {
            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
            "contentVersion": "1.0.0.0",
            "parameters": {
                "location": {
                    "type": "string",
                    "defaultValue": self.location,
                    "metadata": {
                        "description": "Location for the Discovery tool resource"
                    }
                },
                "toolName": {
                    "type": "string",
                    "defaultValue": tool_resource_name,
                    "metadata": {
                        "description": "Name of the Discovery tool resource"
                    }
                }
            },
            "variables": {},
            "resources": [
                {
                    "type": "Microsoft.Discovery/tools",
                    "apiVersion": "2025-07-01-preview",
                    "name": "[parameters('toolName')]",
                    "location": "[parameters('location')]",
                    "tags": {
                        "source": "tool-image-builder",
                        "toolName": tool_name
                    },
                    "properties": properties
                }
            ],
            "outputs": {
                "toolId": {
                    "type": "string",
                    "value": "[resourceId('Microsoft.Discovery/tools', parameters('toolName'))]"
                },
                "toolName": {
                    "type": "string",
                    "value": "[parameters('toolName')]"
                }
            }
        }
        
        return arm_template
    
    def generate_agent_arm_template(self, tool_name: str, tool_resource_id: str) -> Optional[Dict[str, Any]]:
        """Generate ARM template for an agent"""
        tool_path = self.tools_dir / tool_name
        
        # Find agent definition file (e.g., PubMed-agent-definition.yaml)
        agent_def_file = self._find_agent_definition_file(tool_path)
        if not agent_def_file:
            print(f"Info: No agent definition file found for {tool_name}")
            return None
        
        # Load agent definition
        agent_def = self._load_yaml_file(agent_def_file)
        if not agent_def:
            return None
        
        # Generate agent resource name (lowercase for ARM)
        agent_resource_name = f"{tool_name.lower().replace('_', '-')}-agent"
        
        # Convert definition to ARM properties
        properties = self._convert_agent_definition_to_arm_properties(agent_def, tool_resource_id)
        
        # Build ARM template
        arm_template = {
            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
            "contentVersion": "1.0.0.0",
            "parameters": {
                "location": {
                    "type": "string",
                    "defaultValue": self.location,
                    "metadata": {
                        "description": "Location for the Discovery agent resource"
                    }
                },
                "agentName": {
                    "type": "string",
                    "defaultValue": agent_resource_name,
                    "metadata": {
                        "description": "Name of the Discovery agent resource"
                    }
                },
                "toolResourceId": {
                    "type": "string",
                    "defaultValue": tool_resource_id,
                    "metadata": {
                        "description": "Resource ID of the associated tool"
                    }
                }
            },
            "variables": {},
            "resources": [
                {
                    "type": "Microsoft.Discovery/agents",
                    "apiVersion": "2025-07-01-preview",
                    "name": "[parameters('agentName')]",
                    "location": "[parameters('location')]",
                    "tags": {
                        "source": "tool-image-builder",
                        "agentName": tool_name
                    },
                    "properties": properties
                }
            ],
            "outputs": {
                "agentId": {
                    "type": "string",
                    "value": "[resourceId('Microsoft.Discovery/agents', parameters('agentName'))]"
                },
                "agentName": {
                    "type": "string",
                    "value": "[parameters('agentName')]"
                }
            }
        }
        
        return arm_template
    
    def generate_combined_template(self, tool_name: str, image_name: str) -> Optional[Dict[str, Any]]:
        """
        Generate a combined ARM template with both tool and agent resources
        
        Args:
            tool_name: Name of the tool
            image_name: Full ACR image name
            
        Returns:
            Combined ARM template dictionary or None if tool generation fails
        """
        # Generate tool resource name
        tool_resource_name = tool_name.lower().replace('_', '-')
        agent_resource_name = f"{tool_resource_name}-agent"
        
        # Get tool definition
        tool_path = self.tools_dir / tool_name
        tool_def_file = self._find_tool_definition_file(tool_path)
        if not tool_def_file:
            print(f"Error: No tool definition file found for {tool_name}")
            return None
        
        tool_def = self._load_yaml_file(tool_def_file)
        if not tool_def:
            return None
        
        # Convert tool definition to properties
        tool_properties = self._convert_tool_definition_to_arm_properties(tool_def, tool_name, image_name)
        
        # Check if agent definition exists
        agent_def_file = self._find_agent_definition_file(tool_path)
        has_agent = agent_def_file is not None
        
        # Build combined ARM template
        resources = []
        parameters = {
            "location": {
                "type": "string",
                "defaultValue": self.location,
                "metadata": {
                    "description": "Location for the Discovery resources"
                }
            },
            "toolName": {
                "type": "string",
                "defaultValue": tool_resource_name,
                "metadata": {
                    "description": "Name of the Discovery tool resource"
                }
            }
        }
        
        outputs = {
            "toolId": {
                "type": "string",
                "value": "[resourceId('Microsoft.Discovery/tools', parameters('toolName'))]"
            },
            "toolName": {
                "type": "string",
                "value": "[parameters('toolName')]"
            }
        }
        
        # Add tool resource
        resources.append({
            "type": "Microsoft.Discovery/tools",
            "apiVersion": "2025-07-01-preview",
            "name": "[parameters('toolName')]",
            "location": "[parameters('location')]",
            "tags": {
                "source": "tool-image-builder",
                "toolName": tool_name
            },
            "properties": tool_properties
        })
        
        # Add agent resource if definition exists
        if has_agent:
            agent_def = self._load_yaml_file(agent_def_file)
            if agent_def:
                tool_resource_id = (
                    f"/subscriptions/{self.subscription_id}"
                    f"/resourceGroups/{self.resource_group}"
                    f"/providers/Microsoft.Discovery/tools/{tool_resource_name}"
                )
                # Pass tool_resource_id as a list (method expects List[str])
                agent_properties = self._convert_agent_definition_to_arm_properties(agent_def, [tool_resource_id])
                
                # Add agent parameter
                parameters["agentName"] = {
                    "type": "string",
                    "defaultValue": agent_resource_name,
                    "metadata": {
                        "description": "Name of the Discovery agent resource"
                    }
                }
                
                # Add agent resource with dependency on tool
                resources.append({
                    "type": "Microsoft.Discovery/agents",
                    "apiVersion": "2025-07-01-preview",
                    "name": "[parameters('agentName')]",
                    "location": "[parameters('location')]",
                    "dependsOn": [
                        "[resourceId('Microsoft.Discovery/tools', parameters('toolName'))]"
                    ],
                    "tags": {
                        "source": "tool-image-builder",
                        "agentName": tool_name
                    },
                    "properties": agent_properties
                })
                
                # Add agent outputs
                outputs["agentId"] = {
                    "type": "string",
                    "value": "[resourceId('Microsoft.Discovery/agents', parameters('agentName'))]"
                }
                outputs["agentName"] = {
                    "type": "string",
                    "value": "[parameters('agentName')]"
                }
        
        arm_template = {
            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
            "contentVersion": "1.0.0.0",
            "parameters": parameters,
            "variables": {},
            "resources": resources,
            "outputs": outputs
        }
        
        return arm_template
    
    def generate_templates_for_tools(self, successful_tools: List[Dict[str, str]], 
                                    output_dir: str) -> Dict[str, Any]:
        """
        Generate combined ARM templates for successfully built tools
        
        Args:
            successful_tools: List of dicts with 'name' and 'image_name' keys
            output_dir: Directory to save generated templates
            
        Returns:
            Dictionary with generation results
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        results = {
            "total_tools": len(successful_tools),
            "templates_generated": 0,
            "tools_with_agents": 0,
            "tools_without_agents": 0,
            "failed": [],
            "templates": []
        }
        
        for tool_info in successful_tools:
            tool_name = tool_info['name']
            image_name = tool_info['image_name']
            
            print(f"\nGenerating template for {tool_name}...")
            
            # Generate combined template
            combined_template = self.generate_combined_template(tool_name, image_name)
            if combined_template:
                template_file = output_path / f"{tool_name.lower()}-template.json"
                with open(template_file, 'w', encoding='utf-8') as f:
                    json.dump(combined_template, f, indent=2)
                
                # Check if agent is included
                has_agent = len(combined_template["resources"]) > 1
                if has_agent:
                    print(f"  ✓ Combined template (tool + agent) saved: {template_file}")
                    results["tools_with_agents"] += 1
                else:
                    print(f"  ✓ Tool template saved: {template_file}")
                    results["tools_without_agents"] += 1
                
                results["templates_generated"] += 1
                results["templates"].append(str(template_file))
            else:
                results["failed"].append(tool_name)
                print(f"  ✗ Failed to generate template for {tool_name}")
        
        return results
    
    def deploy_templates(self, templates: List[str], resource_group: str) -> Dict[str, Any]:
        """
        Deploy ARM templates to Azure
        
        Args:
            templates: List of template file paths to deploy
            resource_group: Azure resource group name
            
        Returns:
            Dictionary with deployment results
        """
        results = {
            "total_templates": len(templates),
            "successful_deployments": 0,
            "failed_deployments": 0,
            "deployment_details": [],
            "deletion_failures": []
        }
        
        for template_path in templates:
            template_file = Path(template_path)
            deployment_name = template_file.stem  # e.g., "chembl-template"
            
            print(f"\nDeploying {template_file.name}...")
            
            try:
                # Load template to extract resource names
                with open(template_file, 'r') as f:
                    template_data = json.load(f)
                
                # Extract default resource names from parameters
                tool_name = template_data.get('parameters', {}).get('toolName', {}).get('defaultValue')
                agent_name = template_data.get('parameters', {}).get('agentName', {}).get('defaultValue')
                
                # For combined templates with both tool and agent, we need to deploy them separately
                # to avoid validation errors since agent depends on tool existing
                has_both = tool_name and agent_name
                
                if has_both:
                    print(f"  → Detected combined template with tool and agent")
                
                # Check if resources exist and delete them if they do
                # Delete agent first (if exists) since it depends on tool
                if agent_name:
                    print(f"  → Checking for existing agent: {agent_name}")
                    check_agent_cmd = [
                        "az", "resource", "show",
                        "--resource-group", resource_group,
                        "--name", agent_name,
                        "--resource-type", "Microsoft.Discovery/agents",
                        "--query", "id",
                        "-o", "tsv"
                    ]
                    
                    check_result = self._run_command(
                        check_agent_cmd,
                        capture_output=True,
                        text=True,
                        check=False,
                        shell=self.is_windows
                    )
                    
                    if check_result.returncode == 0 and check_result.stdout.strip():
                        print(f"  → Agent exists, deleting: {agent_name}")
                        delete_agent_cmd = [
                            "az", "resource", "delete",
                            "--resource-group", resource_group,
                            "--name", agent_name,
                            "--resource-type", "Microsoft.Discovery/agents"
                        ]
                        
                        delete_result = self._run_command(
                            delete_agent_cmd,
                            capture_output=True,
                            text=True,
                            check=False,
                            shell=self.is_windows
                        )
                        
                        if delete_result.returncode == 0:
                            print(f"  ✓ Agent deleted successfully")
                            time.sleep(3)  # Wait for deletion to complete
                        else:
                            error_msg = delete_result.stderr[:200] if delete_result.stderr else "Unknown error"
                            print(f"  ⚠ Failed to delete agent: {error_msg}")
                            results["deletion_failures"].append({
                                "resource_type": "agent",
                                "resource_name": agent_name,
                                "error": error_msg
                            })
                            print(f"  → Continuing with deployment despite deletion failure...")
                
                # Now delete tool if it exists
                if tool_name:
                    print(f"  → Checking for existing tool: {tool_name}")
                    check_tool_cmd = [
                        "az", "resource", "show",
                        "--resource-group", resource_group,
                        "--name", tool_name,
                        "--resource-type", "Microsoft.Discovery/tools",
                        "--query", "id",
                        "-o", "tsv"
                    ]
                    
                    check_result = self._run_command(
                        check_tool_cmd,
                        capture_output=True,
                        text=True,
                        check=False,
                        shell=self.is_windows
                    )
                    
                    if check_result.returncode == 0 and check_result.stdout.strip():
                        print(f"  → Tool exists, deleting: {tool_name}")
                        delete_tool_cmd = [
                            "az", "resource", "delete",
                            "--resource-group", resource_group,
                            "--name", tool_name,
                            "--resource-type", "Microsoft.Discovery/tools"
                        ]
                        
                        delete_result = self._run_command(
                            delete_tool_cmd,
                            capture_output=True,
                            text=True,
                            check=False,
                            shell=self.is_windows
                        )
                        
                        if delete_result.returncode == 0:
                            print(f"  ✓ Tool deleted successfully")
                            time.sleep(5)  # Wait for deletion to complete
                        else:
                            error_msg = delete_result.stderr[:200] if delete_result.stderr else "Unknown error"
                            print(f"  ⚠ Failed to delete tool: {error_msg}")
                            results["deletion_failures"].append({
                                "resource_type": "tool",
                                "resource_name": tool_name,
                                "error": error_msg
                            })
                            print(f"  → Continuing with deployment despite deletion failure...")
                
                # For combined templates, deploy tool first, then agent
                if has_both:
                    print(f"  → Deploying tool resource first...")
                    # Create a temporary template with just the tool
                    tool_only_template = {
                        "$schema": template_data["$schema"],
                        "contentVersion": template_data["contentVersion"],
                        "parameters": {
                            "location": template_data["parameters"]["location"],
                            "toolName": template_data["parameters"]["toolName"]
                        },
                        "variables": {},
                        "resources": [template_data["resources"][0]],  # First resource is tool
                        "outputs": {
                            "toolId": template_data["outputs"]["toolId"],
                            "toolName": template_data["outputs"]["toolName"]
                        }
                    }
                    
                    # Write temporary tool-only template
                    tool_temp_file = template_file.parent / f"{template_file.stem}_tool_only.json"
                    with open(tool_temp_file, 'w') as f:
                        json.dump(tool_only_template, f, indent=2)
                    
                    # Deploy tool only
                    deploy_tool_cmd = [
                        "az", "deployment", "group", "create",
                        "--resource-group", resource_group,
                        "--template-file", str(tool_temp_file),
                        "--parameters", f"location={self.location}",
                        "--name", f"{deployment_name}-tool"
                    ]
                    
                    deploy_result = self._run_command(deploy_tool_cmd, check=False, shell=self.is_windows)
                    
                    if deploy_result.returncode != 0:
                        print(f"  ✗ Tool deployment failed")
                        tool_temp_file.unlink()  # Clean up temp file
                        results["failed_deployments"] += 1
                        results["deployment_details"].append({
                            "template": str(template_file),
                            "deployment_name": deployment_name,
                            "status": "failed"
                        })
                        continue
                    
                    print(f"  ✓ Tool deployed successfully")
                    time.sleep(5)  # Wait for tool to be fully available
                    tool_temp_file.unlink()  # Clean up temp file
                    
                    # Now deploy agent
                    print(f"  → Deploying agent resource...")
                    # Create agent template without dependsOn since tool already exists
                    agent_resource = template_data["resources"][1].copy()
                    # Remove dependsOn field for separate deployment
                    if "dependsOn" in agent_resource:
                        del agent_resource["dependsOn"]
                    
                    agent_only_template = {
                        "$schema": template_data["$schema"],
                        "contentVersion": template_data["contentVersion"],
                        "parameters": {
                            "location": template_data["parameters"]["location"],
                            "agentName": template_data["parameters"]["agentName"]
                        },
                        "variables": {},
                        "resources": [agent_resource],
                        "outputs": {
                            "agentId": template_data["outputs"]["agentId"],
                            "agentName": template_data["outputs"]["agentName"]
                        }
                    }
                    
                    # Write temporary agent-only template
                    agent_temp_file = template_file.parent / f"{template_file.stem}_agent_only.json"
                    with open(agent_temp_file, 'w') as f:
                        json.dump(agent_only_template, f, indent=2)
                    
                    # Extract agent name from definition for deployment
                    agent_def_name = agent_resource["properties"]["definitionContent"]["agent"]["name"]
                    
                    # Deploy agent directly with Azure CLI
                    print(f"  → Deploying agent resource...")
                    agent_deploy_cmd = [
                        "az", "deployment", "group", "create",
                        "--resource-group", resource_group,
                        "--template-file", str(agent_temp_file),
                        "--parameters", f"location={self.location}", f"agentName={agent_def_name}",
                        "--name", f"{deployment_name}-agent"
                    ]
                    
                    deploy_result = self._run_command(
                        agent_deploy_cmd,
                        capture_output=True,
                        text=True,
                        check=False,
                        shell=self.is_windows
                    )
                    
                    agent_temp_file.unlink()  # Clean up temp file
                    
                    if deploy_result.returncode != 0:
                        print(f"  ✗ Agent deployment failed")
                        print(f"     Error: {deploy_result.stderr.strip()}")
                        results["failed_deployments"] += 1
                        results["deployment_details"].append({
                            "template": str(template_file),
                            "deployment_name": deployment_name,
                            "status": "partial_success_tool_only",
                            "error": f"Agent deployment failed: {deploy_result.stderr.strip()}"
                        })
                        continue
                    
                    # Agent deployment succeeded
                    print(f"  ✓ Agent deployed successfully")
                    print(f"  ✓ Combined deployment successful: {deployment_name}")
                    results["successful_deployments"] += 1
                    results["deployment_details"].append({
                        "template": str(template_file),
                        "deployment_name": deployment_name,
                        "status": "success"
                    })
                    continue
                
                # For tool-only or agent-only templates, deploy directly
                print(f"  → Deploying resources...")
                
                # Build deployment command
                deploy_cmd = [
                    "az", "deployment", "group", "create",
                    "--resource-group", resource_group,
                    "--template-file", str(template_file),
                    "--parameters", f"location={self.location}",
                    "--name", deployment_name
                ]
                
                # Execute deployment - don't capture output to avoid "content consumed" error
                deploy_result = self._run_command(
                    deploy_cmd,
                    check=False,
                    shell=self.is_windows
                )
                
                if deploy_result.returncode == 0:
                    print(f"  ✓ Deployment successful: {deployment_name}")
                    results["successful_deployments"] += 1
                    results["deployment_details"].append({
                        "template": str(template_file),
                        "deployment_name": deployment_name,
                        "status": "success"
                    })
                else:
                    print(f"  ✗ Deployment failed: {deployment_name}")
                    results["failed_deployments"] += 1
                    results["deployment_details"].append({
                        "template": str(template_file),
                        "deployment_name": deployment_name,
                        "status": "failed"
                    })
                        
            except Exception as e:
                print(f"  ✗ Deployment error: {str(e)}")
                results["failed_deployments"] += 1
                results["deployment_details"].append({
                    "template": str(template_file),
                    "deployment_name": deployment_name,
                    "status": "error",
                    "error": str(e)
                })
        
        return results


def main():
    """Main entry point when called from build_tools.py"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate ARM templates for Discovery tools and agents"
    )
    parser.add_argument(
        "--repo-root",
        required=True,
        help="Path to repository root"
    )
    parser.add_argument(
        "--subscription-id",
        required=True,
        help="Azure subscription ID"
    )
    parser.add_argument(
        "--resource-group",
        required=True,
        help="Azure resource group name"
    )
    parser.add_argument(
        "--location",
        default="eastus",
        help="Azure location for resources (default: eastus)"
    )
    parser.add_argument(
        "--acr-name",
        required=True,
        help="Azure Container Registry name"
    )
    parser.add_argument(
        "--tools",
        required=True,
        help="JSON string with list of successful tools (name, image_name)"
    )
    parser.add_argument(
        "--output-dir",
        default="./arm-templates",
        help="Output directory for ARM templates (default: ./arm-templates)"
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Deploy generated templates to Azure"
    )
    
    args = parser.parse_args()
    
    # Parse tools JSON
    try:
        successful_tools = json.loads(args.tools)
    except json.JSONDecodeError as e:
        print(f"Error: Could not parse tools JSON: {e}")
        sys.exit(1)
    
    # Create generator
    generator = ARMTemplateGenerator(
        repo_root=args.repo_root,
        subscription_id=args.subscription_id,
        resource_group=args.resource_group,
        location=args.location,
        acr_name=args.acr_name
    )
    
    # Generate templates
    print(f"\n{'='*60}")
    print("ARM Template Generation")
    print(f"{'='*60}")
    
    results = generator.generate_templates_for_tools(successful_tools, args.output_dir)
    
    # Display summary
    print(f"\n{'='*60}")
    print("ARM Template Generation Summary")
    print(f"{'='*60}")
    print(f"Total tools processed: {results['total_tools']}")
    print(f"Templates generated: {results['templates_generated']}")
    print(f"  - Tools with agents: {results['tools_with_agents']}")
    print(f"  - Tools without agents: {results['tools_without_agents']}")
    
    if results['failed']:
        print(f"\nFailed to generate templates for: {', '.join(results['failed'])}")
    
    print(f"\nTemplates saved to: {args.output_dir}")
    print(f"{'='*60}\n")
    
    # Deploy templates if requested
    if args.deploy and results['templates_generated'] > 0:
        print(f"\n{'='*60}")
        print("Deploying ARM Templates to Azure")
        print(f"{'='*60}")
        
        deployment_results = generator.deploy_templates(
            results['templates'],
            args.resource_group
        )
        
        # Display deployment summary
        print(f"\n{'='*60}")
        print("Deployment Summary")
        print(f"{'='*60}")
        print(f"Total templates: {deployment_results['total_templates']}")
        print(f"Successful deployments: {deployment_results['successful_deployments']}")
        print(f"Failed deployments: {deployment_results['failed_deployments']}")
        
        # Show deletion failures if any
        if deployment_results['deletion_failures']:
            print(f"\n⚠ Resource Deletion Failures:")
            for failure in deployment_results['deletion_failures']:
                print(f"  - {failure['resource_type'].upper()}: {failure['resource_name']}")
                print(f"    Reason: {failure['error']}")
            print(f"\nNote: Deployments proceeded despite deletion failures.")
            print(f"Existing resources may have been updated instead of replaced.")
        
        print(f"{'='*60}\n")
        
        # Exit with appropriate code
        sys.exit(0 if deployment_results['failed_deployments'] == 0 else 1)
    
    # Exit with success if at least some templates were generated
    sys.exit(0 if results['templates_generated'] > 0 else 1)


if __name__ == "__main__":
    main()
