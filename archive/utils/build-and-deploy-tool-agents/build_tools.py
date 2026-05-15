#!/usr/bin/env python3
"""
Microsoft Discovery Tool Image Builder

This script discovers sample tools with Dockerfiles and builds them either:
1. Locally using Docker (requires Docker Desktop/Engine installed)
2. Remotely using Azure Container Registry Tasks (no local Docker needed)

Usage:
    python build_tools.py [--deploy]

Options:
    --deploy    Generate ARM templates for successfully built tools

Requirements:
    - For --deploy: PyYAML package (pip install pyyaml)

    - Python 3.7 or higher
    - For remote builds: Azure CLI installed and authenticated (az login)
    - For local builds: Docker Desktop or Docker Engine installed
"""

import os
import sys
import subprocess
import json
import platform
import argparse
from pathlib import Path
from typing import List, Dict, Tuple, Optional


class ToolImageBuilder:
    """Orchestrates Docker image builds locally or remotely using ACR Tasks"""
    
    def __init__(self, generate_arm_templates: bool = False):
        self.repo_root = self._find_repo_root()
        self.tools_dir = self.repo_root / "6-solutions" / "tools-and-models"
        self.platform = platform.system()  # 'Darwin' (macOS), 'Windows', 'Linux'
        self.is_windows = self.platform == "Windows"
        self.generate_arm_templates = generate_arm_templates
        self.acr_name = None
        self.resource_group = None
        self.subscription_id = None
        self._load_env_file()
    
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
        
    def _load_env_file(self) -> None:
        """Load environment variables from .env file if it exists"""
        env_file = Path(__file__).resolve().parent / ".env"
        if env_file.exists():
            print(f"📝 Loading configuration from {env_file.name}")
            try:
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        # Skip comments and empty lines
                        if line and not line.startswith('#'):
                            # Parse KEY=VALUE
                            if '=' in line:
                                key, value = line.split('=', 1)
                                key = key.strip()
                                value = value.strip()
                                # Only set if not already in environment and value is not empty
                                if value and key not in os.environ:
                                    os.environ[key] = value
            except Exception as e:
                print(f"⚠️  Warning: Could not load .env file: {e}")
        
    def _find_repo_root(self) -> Path:
        """Find the repository root directory"""
        current = Path(__file__).resolve().parent
        while current != current.parent:
            if (current / "6-solutions").exists():
                return current
            current = current.parent
        raise RuntimeError("Could not find repository root. Please run this script from within the discovery repository.")
    
    def check_docker_available(self) -> bool:
        """Check if Docker is installed and running"""
        print("🔍 Checking Docker availability...")
        
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                print("❌ Docker not found")
                return False
            
            # Check if Docker daemon is running
            result = subprocess.run(
                ["docker", "ps"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                print("❌ Docker is installed but not running")
                print("   Please start Docker Desktop or Docker Engine")
                return False
            
            print(f"✅ Docker is available and running")
            print(f"   Platform: {self.platform}")
            return True
            
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print("❌ Docker not found")
            return False
    
    def discover_tools(self) -> List[Dict[str, str]]:
        """Discover all tools with Dockerfiles in the tools-and-models directory"""
        tools = []
        
        if not self.tools_dir.exists():
            print(f"❌ Tools directory not found: {self.tools_dir}")
            return tools
        
        for tool_dir in sorted(self.tools_dir.iterdir()):
            if not tool_dir.is_dir() or tool_dir.name.startswith('.'):
                continue
            
            dockerfile = tool_dir / "Dockerfile"
            if dockerfile.exists():
                tools.append({
                    "name": tool_dir.name,
                    "path": str(tool_dir.relative_to(self.repo_root)),
                    "dockerfile": str(dockerfile.relative_to(self.repo_root))
                })
        
        return tools
    
    def display_tools(self, tools: List[Dict[str, str]]) -> None:
        """Display discovered tools to user"""
        print("\n" + "="*80)
        print("📦 Discovered Tools with Dockerfiles")
        print("="*80)
        
        for idx, tool in enumerate(tools, 1):
            print(f"\n{idx}. {tool['name']}")
            print(f"   Path: {tool['path']}")
            print(f"   Dockerfile: {tool['dockerfile']}")
        
        print("\n" + "="*80 + "\n")
    
    def choose_build_mode(self, docker_available: bool) -> str:
        """Let user choose between local and remote build"""
        print("\n" + "="*80)
        print("🔧 Build Mode Selection")
        print("="*80 + "\n")
        
        if docker_available:
            print("Choose build mode:")
            print("  1. Local build (using Docker on this machine)")
            print("  2. Remote build (using Azure Container Registry Tasks)")
            print("  q. Quit\n")
            
            while True:
                choice = input("Your choice (1/2/q): ").strip().lower()
                
                if choice == 'q':
                    print("👋 Exiting...")
                    sys.exit(0)
                elif choice == '1':
                    print("✅ Selected: Local build\n")
                    return 'local'
                elif choice == '2':
                    print("✅ Selected: Remote build\n")
                    return 'remote'
                else:
                    print("❌ Invalid choice. Please enter 1, 2, or q\n")
        else:
            print("⚠️  Docker is not available on this machine.")
            print("✅ Will use remote build mode (Azure Container Registry Tasks)\n")
            return 'remote'
    
    def select_tools(self, tools: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Allow user to select which tools to build"""
        print("Select tools to build:")
        print("  - Enter tool numbers separated by commas (e.g., 1,3,5)")
        print("  - Enter 'all' to build all tools")
        print("  - Enter 'q' to quit\n")
        
        while True:
            selection = input("Your selection: ").strip().lower()
            
            if selection == 'q':
                print("👋 Exiting...")
                sys.exit(0)
            
            if selection == 'all':
                print(f"✅ Selected all {len(tools)} tools\n")
                return tools
            
            try:
                indices = [int(idx.strip()) for idx in selection.split(',')]
                selected_tools = []
                
                for idx in indices:
                    if 1 <= idx <= len(tools):
                        selected_tools.append(tools[idx - 1])
                    else:
                        print(f"⚠️  Invalid tool number: {idx}")
                        break
                else:
                    if selected_tools:
                        print(f"✅ Selected {len(selected_tools)} tool(s)\n")
                        return selected_tools
            
            except ValueError:
                print("❌ Invalid input. Please enter numbers separated by commas, 'all', or 'q'\n")
    
    def get_acr_details(self) -> Tuple[str, str, str]:
        """Get ACR details from environment or user input"""
        acr_name = os.getenv('ACR_NAME')
        resource_group = os.getenv('AZURE_RESOURCE_GROUP')
        subscription_id = os.getenv('AZURE_SUBSCRIPTION_ID')
        
        print("\n" + "="*80)
        print("🔧 Azure Container Registry Configuration")
        print("="*80 + "\n")
        
        if not acr_name:
            acr_name = input("Enter ACR name: ").strip()
        else:
            print(f"ACR Name: {acr_name} (from environment)")
        
        if not resource_group:
            resource_group = input("Enter Resource Group: ").strip()
        else:
            print(f"Resource Group: {resource_group} (from environment)")
        
        if not subscription_id:
            subscription_id = input("Enter Subscription ID (optional, press Enter to use default): ").strip()
        else:
            print(f"Subscription ID: {subscription_id} (from environment)")
        
        print()
        
        # Store for later use in ARM template generation
        self.acr_name = acr_name
        self.resource_group = resource_group
        self.subscription_id = subscription_id
        
        return acr_name, resource_group, subscription_id
    
    def verify_azure_cli(self) -> bool:
        """Verify Azure CLI is installed and user is authenticated"""
        print("🔍 Verifying Azure CLI...")
        
        # Check if Azure CLI is installed
        # On Windows, we need shell=True to find az.cmd/az.bat
        try:
            result = self._run_command(
                ["az", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                shell=self.is_windows
            )
            if result.returncode != 0:
                print("❌ Azure CLI not found. Please install: https://docs.microsoft.com/cli/azure/install-azure-cli")
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print("❌ Azure CLI not found. Please install: https://docs.microsoft.com/cli/azure/install-azure-cli")
            return False
        
        # Check if user is authenticated
        try:
            result = self._run_command(
                ["az", "account", "show"],
                capture_output=True,
                text=True,
                timeout=10,
                shell=self.is_windows
            )
            if result.returncode != 0:
                print("❌ Not authenticated with Azure. Please run: az login")
                return False
            
            account_info = json.loads(result.stdout)
            print(f"✅ Authenticated as: {account_info.get('user', {}).get('name', 'Unknown')}")
            print(f"✅ Subscription: {account_info.get('name', 'Unknown')}\n")
            
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
            print(f"❌ Error checking Azure authentication: {e}")
            return False
        
        return True
    
    def verify_acr_access(self, acr_name: str, resource_group: str, subscription_id: str = None) -> bool:
        """Verify user has access to the ACR"""
        print(f"🔍 Verifying access to ACR: {acr_name}...")
        
        cmd = ["az", "acr", "show", "--name", acr_name, "--resource-group", resource_group]
        if subscription_id:
            cmd.extend(["--subscription", subscription_id])
        
        try:
            result = self._run_command(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                shell=self.is_windows
            )
            
            if result.returncode != 0:
                print(f"❌ Cannot access ACR '{acr_name}' in resource group '{resource_group}'")
                print(f"   Error: {result.stderr.strip()}")
                return False
            
            acr_info = json.loads(result.stdout)
            print(f"✅ ACR found: {acr_info.get('loginServer', 'Unknown')}")
            print(f"✅ Location: {acr_info.get('location', 'Unknown')}\n")
            
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
            print(f"❌ Error verifying ACR access: {e}")
            return False
        
        return True
    
    def build_tool_locally(
        self,
        tool: Dict[str, str],
        acr_name: Optional[str] = None,
        push_to_acr: bool = False
    ) -> Tuple[bool, str]:
        """Build a single tool using local Docker"""
        tool_name = tool['name']
        context_path = tool['path']
        dockerfile_path = tool['dockerfile']
        
        # Image name and tag (convert to lowercase for Docker naming compliance)
        image_name = f"{tool_name.lower()}:latest"
        
        # Full image name with registry if pushing to ACR
        if push_to_acr and acr_name:
            full_image_name = f"{acr_name}.azurecr.io/{image_name}"
        else:
            full_image_name = image_name
        
        print(f"\n{'='*80}")
        print(f"🏗️  Building: {tool_name}")
        print(f"{'='*80}")
        print(f"Context: {context_path}")
        print(f"Dockerfile: {dockerfile_path}")
        print(f"Image: {full_image_name}")
        print(f"Build mode: Local Docker")
        print()
        
        # Build the Docker build command
        build_cmd = [
            "docker", "build",
            "-t", full_image_name,
            "-f", str(self.repo_root / dockerfile_path),
            str(self.repo_root / context_path)
        ]
        
        print(f"🚀 Starting local build...\n")
        
        try:
            # Run the build with real-time output
            result = subprocess.run(
                build_cmd,
                cwd=str(self.repo_root),
                text=True,
                shell=self.is_windows
            )
            
            if result.returncode != 0:
                print(f"\n❌ Build failed for: {tool_name}")
                return False, ""
            
            print(f"\n✅ Successfully built: {full_image_name}")
            
            # Push to ACR if requested
            if push_to_acr and acr_name:
                print(f"\n📤 Pushing image to ACR...")
                
                # Login to ACR
                login_cmd = ["az", "acr", "login", "--name", acr_name]
                login_result = self._run_command(
                    login_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    shell=self.is_windows
                )
                
                if login_result.returncode != 0:
                    print(f"❌ Failed to login to ACR: {login_result.stderr}")
                    return False, ""
                
                # Push the image
                push_cmd = ["docker", "push", full_image_name]
                push_result = self._run_command(
                    push_cmd,
                    text=True,
                    shell=self.is_windows
                )
                
                if push_result.returncode == 0:
                    print(f"✅ Successfully pushed: {full_image_name}")
                    return True, image_name
                else:
                    print(f"❌ Failed to push image to ACR")
                    return False, ""
            
            # Local build without push
            return True, image_name
                
        except subprocess.TimeoutExpired:
            print(f"\n❌ Build timed out for: {tool_name}")
            return False, ""
        except Exception as e:
            print(f"\n❌ Error building {tool_name}: {e}")
            return False, ""
    
    def build_tool_with_acr_tasks(
        self, 
        tool: Dict[str, str], 
        acr_name: str, 
        resource_group: str,
        subscription_id: str = None
    ) -> Tuple[bool, str]:
        """Build a single tool using ACR Tasks (remote build)"""
        tool_name = tool['name']
        context_path = tool['path']
        dockerfile_path = tool['dockerfile']
        
        # Image name and tag (convert to lowercase for Docker naming compliance)
        image_name = f"{tool_name.lower()}:latest"
        
        print(f"\n{'='*80}")
        print(f"🏗️  Building: {tool_name}")
        print(f"{'='*80}")
        print(f"Context: {context_path}")
        print(f"Dockerfile: {dockerfile_path}")
        print(f"Image: {image_name}")
        print(f"Registry: {acr_name}")
        print()
        
        # Build the ACR task command
        # ACR Tasks can build from a local directory or Git repository
        # We'll use the local directory approach with file upload
        cmd = [
            "az", "acr", "build",
            "--registry", acr_name,
            "--resource-group", resource_group,
            "--image", image_name,
            "--file", dockerfile_path,
            str(self.repo_root / context_path)
        ]
        
        if subscription_id:
            cmd.extend(["--subscription", subscription_id])
        
        print(f"🚀 Starting remote build (this may take several minutes)...\n")
        
        try:
            # Run the build with real-time output
            result = subprocess.run(
                cmd,
                cwd=str(self.repo_root),
                text=True,
                shell=self.is_windows
            )
            
            if result.returncode == 0:
                print(f"\n✅ Successfully built and pushed: {acr_name}.azurecr.io/{image_name}")
                return True, image_name
            else:
                print(f"\n❌ Build failed for: {tool_name}")
                return False, ""
                
        except subprocess.TimeoutExpired:
            print(f"\n❌ Build timed out for: {tool_name}")
            return False, ""
        except Exception as e:
            print(f"\n❌ Error building {tool_name}: {e}")
            return False, ""
    
    def _generate_arm_templates(self, successful_tools: List[Dict[str, str]]) -> None:
        """Generate ARM templates for successfully built tools"""
        print("\n" + "="*80)
        print("📄 Generating ARM Templates")
        print("="*80 + "\n")
        
        # Check if PyYAML is available
        try:
            import yaml
        except ImportError:
            print("❌ PyYAML not installed. ARM template generation requires PyYAML.")
            print("   Install with: pip install pyyaml\n")
            return
        
        # Get Azure location
        location = input("Enter Azure location for resources (default: eastus): ").strip() or "eastus"
        
        # Ask if user wants to deploy
        deploy_response = input("Deploy templates to Azure? (y/N): ").strip().lower()
        should_deploy = deploy_response in ['y', 'yes']
        
        # Prepare command for generate_arm_templates.py
        tools_json = json.dumps(successful_tools)
        
        script_path = Path(__file__).resolve().parent / "generate_arm_templates.py"
        output_dir = Path(__file__).resolve().parent / "arm-templates"
        
        cmd = [
            sys.executable,
            str(script_path),
            "--repo-root", str(self.repo_root),
            "--subscription-id", self.subscription_id or "",
            "--resource-group", self.resource_group,
            "--location", location,
            "--acr-name", self.acr_name,
            "--tools", tools_json,
            "--output-dir", str(output_dir)
        ]
        
        # Add --deploy flag if user confirmed
        if should_deploy:
            cmd.append("--deploy")
            print("\n🚀 Templates will be deployed to Azure after generation\n")
        else:
            print("\n📝 Templates will be generated only (no deployment)\n")
        
        try:
            result = subprocess.run(
                cmd,
                text=True,
                shell=self.is_windows
            )
            
            if result.returncode == 0:
                if should_deploy:
                    print("\n✅ ARM templates generated and deployed successfully!")
                else:
                    print("\n✅ ARM templates generated successfully!")
            else:
                print("\n⚠️  ARM template generation/deployment completed with warnings")
                
        except Exception as e:
            print(f"\n❌ Error generating ARM templates: {e}")
    
    def run(self):
        """Main execution flow"""
        print("\n" + "="*80)
        print("🚀 Microsoft Discovery - Tool Image Builder")
        print("="*80)
        print(f"\nPlatform: {self.platform}")
        print("This script can build Docker images locally or remotely using Azure.\n")
        
        # Step 1: Check Docker availability
        docker_available = self.check_docker_available()
        
        # Step 2: Choose build mode
        build_mode = self.choose_build_mode(docker_available)
        
        # Step 3: Verify prerequisites based on mode
        if build_mode == 'remote':
            if not self.verify_azure_cli():
                sys.exit(1)
        
        # Step 4: Discover tools
        tools = self.discover_tools()
        if not tools:
            print("❌ No tools with Dockerfiles found!")
            sys.exit(1)
        
        self.display_tools(tools)
        
        # Step 5: Select tools
        selected_tools = self.select_tools(tools)
        
        # Step 6: Get configuration based on mode
        acr_name = None
        resource_group = None
        subscription_id = None
        push_to_acr = False
        
        if build_mode == 'remote':
            acr_name, resource_group, subscription_id = self.get_acr_details()
            if not self.verify_acr_access(acr_name, resource_group, subscription_id):
                sys.exit(1)
        else:
            # Local build - ask if they want to push to ACR
            print("\n" + "="*80)
            print("📤 Push to Azure Container Registry?")
            print("="*80 + "\n")
            push_choice = input("Push images to ACR after building? (yes/no): ").strip().lower()
            
            if push_choice in ['yes', 'y']:
                push_to_acr = True
                # Need Azure CLI for pushing
                if not self.verify_azure_cli():
                    print("⚠️  Azure CLI required for pushing to ACR")
                    sys.exit(1)
                
                acr_name, resource_group, subscription_id = self.get_acr_details()
                if not self.verify_acr_access(acr_name, resource_group, subscription_id):
                    sys.exit(1)
        
        # Step 7: Confirm before building
        print("\n" + "="*80)
        print(f"📋 Build Summary:")
        print(f"   Tools to build: {len(selected_tools)}")
        print(f"   Build mode: {'Remote (ACR Tasks)' if build_mode == 'remote' else 'Local (Docker)'}")
        if acr_name:
            print(f"   Target ACR: {acr_name}")
        if build_mode == 'local' and not push_to_acr:
            print(f"   Images will be stored locally only")
        print("="*80 + "\n")
        
        confirm = input("Proceed with builds? (yes/no): ").strip().lower()
        if confirm not in ['yes', 'y']:
            print("👋 Build cancelled.")
            sys.exit(0)
        
        # Step 8: Build each tool
        results = []
        successful_tools_for_arm = []
        
        for idx, tool in enumerate(selected_tools, 1):
            print(f"\n[{idx}/{len(selected_tools)}]")
            
            if build_mode == 'remote':
                success, image_name = self.build_tool_with_acr_tasks(
                    tool, acr_name, resource_group, subscription_id
                )
            else:
                success, image_name = self.build_tool_locally(
                    tool, acr_name, push_to_acr
                )
            
            results.append((tool['name'], success))
            
            # Track successful tools that were pushed to ACR for ARM template generation
            if success and image_name and (build_mode == 'remote' or push_to_acr):
                successful_tools_for_arm.append({
                    'name': tool['name'],
                    'image_name': image_name
                })
        
        # Step 9: Display final summary
        print("\n" + "="*80)
        print("📊 Build Summary")
        print("="*80 + "\n")
        
        successful = [name for name, success in results if success]
        failed = [name for name, success in results if not success]
        
        if successful:
            print(f"✅ Successfully built ({len(successful)}):")
            for name in successful:
                print(f"   - {name}")
        
        if failed:
            print(f"\n❌ Failed ({len(failed)}):")
            for name in failed:
                print(f"   - {name}")
        
        print("\n" + "="*80)
        print(f"Total: {len(successful)}/{len(results)} successful")
        print("="*80 + "\n")
        
        # Step 10: Generate ARM templates if requested and there are successful builds with ACR
        if self.generate_arm_templates and successful_tools_for_arm:
            self._generate_arm_templates(successful_tools_for_arm)
        elif self.generate_arm_templates and not successful_tools_for_arm:
            print("⚠️  ARM template generation requested but no tools were successfully pushed to ACR")
            print("   ARM templates require images to be in ACR. Use remote build or local build with ACR push.\n")
        
        if failed:
            sys.exit(1)


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Build Docker images for Microsoft Discovery tools"
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Generate ARM templates for successfully built tools"
    )
    
    args = parser.parse_args()
    
    try:
        builder = ToolImageBuilder(generate_arm_templates=args.deploy)
        builder.run()
    except KeyboardInterrupt:
        print("\n\n👋 Build cancelled by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
