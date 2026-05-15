"""
Prompt loading utilities for Workflow Agent generation and Tool Creation workflow.
Supports loading prompts from external files with template variable substitution.
"""

import os
import re
from typing import Dict, Any, Optional


class PromptLoader:
    """Utility class for loading and processing prompt templates from files."""
    
    def __init__(self, prompts_dir: Optional[str] = None):
        """
        Initialize the prompt loader.
        
        Args:
            prompts_dir: Directory containing prompt files. Defaults to ./prompts/
        """
        if prompts_dir is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            prompts_dir = os.path.join(script_dir, 'prompts')
        
        self.prompts_dir = prompts_dir
        self._cache = {}  # Cache for loaded prompts
    
    def load_prompt(self, prompt_path: str, use_cache: bool = True) -> str:
        """
        Load a prompt from a file.
        
        Args:
            prompt_path: Relative path to the prompt file (e.g., 'components/router_system.txt')
            use_cache: Whether to use cached version if available
            
        Returns:
            The prompt content as a string
            
        Raises:
            FileNotFoundError: If the prompt file doesn't exist
        """
        if use_cache and prompt_path in self._cache:
            return self._cache[prompt_path]
        
        full_path = os.path.join(self.prompts_dir, prompt_path)
        
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"Prompt file not found: {full_path}")
        
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            if use_cache:
                self._cache[prompt_path] = content
            
            return content
        except Exception as e:
            raise IOError(f"Error reading prompt file {full_path}: {str(e)}")
    
    def load_component_prompts(self, component: str) -> tuple[str, str]:
        """
        Load both system and user prompts for a component.
        
        Args:
            component: Component name (router, planner, summarizer, workflow)
            
        Returns:
            Tuple of (system_prompt, user_prompt_template)
        """
        system_prompt = self.load_prompt(f'components/{component}_system.txt')
        user_prompt = self.load_prompt(f'components/{component}_user.txt')
        
        return system_prompt, user_prompt
    
    def load_main_agent_prompts(self) -> tuple[str, str]:
        """
        Load system and user prompts for main agent generation.
        
        Returns:
            Tuple of (system_prompt, user_prompt_template)
        """
        system_prompt = self.load_prompt('main_agent_system.txt')
        user_prompt = self.load_prompt('main_agent_user.txt')
        
        return system_prompt, user_prompt
    
    def substitute_variables(self, template: str, variables: Dict[str, Any]) -> str:
        """
        Substitute template variables in a prompt template.
        
        Args:
            template: The prompt template containing {variable} placeholders
            variables: Dictionary of variable names to values
            
        Returns:
            The template with variables substituted
        """
        result = template
        
        for key, value in variables.items():
            placeholder = f"{{{key}}}"
            if isinstance(value, list):
                # Handle list values - join them appropriately
                if key.endswith('_list'):
                    # Format as bullet list
                    value_str = '\n'.join([f"  * {item}: Specialized agent" for item in value])
                elif key.endswith('_joined'):
                    # Format as comma-separated
                    value_str = ', '.join(value)
                else:
                    # Default list formatting
                    value_str = str(value)
            else:
                value_str = str(value)
                
                # For descriptions and similar text fields that might contain colons,
                # quote them to ensure YAML validity when used in YAML context
                if key in ['tool_description', 'agent_description', 'description'] and ':' in value_str:
                    # Check if this looks like it's being used in a YAML context
                    # by looking for YAML-like patterns in the template around this placeholder
                    lines = template.split('\n')
                    for line in lines:
                        if placeholder in line and ':' in line:
                            # This placeholder appears to be used as a YAML value
                            # Quote it to prevent YAML parsing issues
                            value_str = f'"{value_str}"'
                            break

            # Debug: print selected_agents_capabilities so server logs show exactly
            # what will be sent to the LLM. This helps diagnose missing descriptions.
            try:
                if key == 'selected_agents_capabilities':
                    # Use a concise representation to avoid overly verbose logs
                    # If it's a list or dict, print with indentation
                    if isinstance(value, (list, dict)):
                        import json as _json
                        try:
                            print(_json.dumps(value, indent=2))
                        except Exception:
                            print(repr(value))
                    else:
                        print(str(value))
            except Exception:
                # Never fail substitution due to logging
                pass
            
            result = result.replace(placeholder, value_str)
        
        return result
    
    def format_agent_details(self, selected_agents: list) -> str:
        """
        Format agent details for use in prompts.
        
        Args:
            selected_agents: List of selected agent names
            
        Returns:
            Formatted agent details string
        """
        return '\n'.join([f"  * {agent}: Specialized agent" for agent in selected_agents])
    
    def validate_template_variables(self, template: str) -> list[str]:
        """
        Extract and validate template variables in a prompt.
        
        Args:
            template: The prompt template to validate
            
        Returns:
            List of unresolved template variables (those still containing {variable})
        """
        # Find all {variable} patterns
        pattern = r'\{([^}]+)\}'
        matches = re.findall(pattern, template)
        
        return matches
    
    def clear_cache(self):
        """Clear the prompt cache."""
        self._cache.clear()
    
    # Tool Creation specific methods
    def load_tool_creation_prompts(self, prompt_type: str) -> tuple[str, str]:
        """
        Load tool creation prompts (system and user template).
        
        Args:
            prompt_type: Type of prompt ('script_analysis', 'combine_docs', 'organize_final')
            
        Returns:
            Tuple of (system_prompt, user_prompt_template)
        """
        system_prompt = self.load_prompt(f'tool-creation/{prompt_type}_system.txt')
        user_template = self.load_prompt(f'tool-creation/{prompt_type}_user.txt')
        return system_prompt, user_template
    
    def get_script_analysis_user_prompt(self, script_path: str, script_content: str, 
                                       folder_context: str, dockerfile_content: str = "") -> str:
        """
        Generate formatted user prompt for script analysis.
        
        Args:
            script_path: Path to the script being analyzed
            script_content: Content of the script (will be truncated if too long)
            folder_context: Folder context for the script
            dockerfile_content: Optional Dockerfile content for context
            
        Returns:
            Formatted user prompt string
        """
        _, user_template = self.load_tool_creation_prompts('script_analysis')
        
        # Previously we truncated script and dockerfile content before sending to the LLM.
        # To ensure the LLM sees the full script documentation and APIs we no longer
        # truncate here. If content is extremely large, we emit a debug warning so
        # operators can decide to adjust conversation limits explicitly.
        if len(dockerfile_content) > 200000 or len(script_content) > 200000:
            try:
                print(f"DEBUG: Large content sizes - dockerfile:{len(dockerfile_content)} chars, script:{len(script_content)} chars")
            except Exception:
                pass

        return self.substitute_variables(user_template, {
            'script_path': script_path,
            'folder_context': folder_context,
            'dockerfile_content': dockerfile_content,
            'script_content': script_content
        })
    
    def get_combine_docs_user_prompt(self, combined_content: str) -> str:
        """
        Generate formatted user prompt for combining documentation.
        
        Args:
            combined_content: Combined content from all script documentations
            
        Returns:
            Formatted user prompt string
        """
        _, user_template = self.load_tool_creation_prompts('combine_docs')
        
        # Send the full combined content to the LLM so API docs are complete.
        if len(combined_content) > 200000:
            try:
                print(f"DEBUG: Large combined_content length: {len(combined_content)} chars")
            except Exception:
                pass

        return self.substitute_variables(user_template, {
            'combined_content': combined_content
        })
    
    def get_organize_final_user_prompt(self, scripts_path: str, total_scripts: int, 
                                      folder_count: int, combined_api_doc: str) -> str:
        """
        Generate formatted user prompt for final organization.
        
        Args:
            scripts_path: Path to the scripts directory
            total_scripts: Total number of scripts processed
            folder_count: Number of folders in the project
            combined_api_doc: Combined API documentation
            
        Returns:
            Formatted user prompt string
        """
        _, user_template = self.load_tool_creation_prompts('organize_final')
        
        # Send the full combined API documentation to the LLM. This avoids missing
        # APIs in generated per-script documentation. Emit a debug warning for
        # unusually large docs so operators can tune conversation token limits.
        if len(combined_api_doc) > 200000:
            try:
                print(f"DEBUG: Large combined_api_doc length: {len(combined_api_doc)} chars")
            except Exception:
                pass

        return self.substitute_variables(user_template, {
            'scripts_path': scripts_path,
            'total_scripts': total_scripts,
            'folder_count': folder_count,
            'combined_api_doc': combined_api_doc
        })


# Global prompt loader instance
_prompt_loader = None

def get_prompt_loader() -> PromptLoader:
    """Get the global prompt loader instance."""
    global _prompt_loader
    if _prompt_loader is None:
        _prompt_loader = PromptLoader()
    return _prompt_loader


def load_component_prompts(component: str) -> tuple[str, str]:
    """
    Convenience function to load component prompts.
    
    Args:
        component: Component name (router, planner, summarizer, workflow)
        
    Returns:
        Tuple of (system_prompt, user_prompt_template)
    """
    return get_prompt_loader().load_component_prompts(component)


def load_main_agent_prompts() -> tuple[str, str]:
    """
    Convenience function to load main agent prompts.
    
    Returns:
        Tuple of (system_prompt, user_prompt_template)
    """
    return get_prompt_loader().load_main_agent_prompts()


def substitute_prompt_variables(template: str, variables: Dict[str, Any]) -> str:
    """
    Convenience function to substitute template variables.
    
    Args:
        template: The prompt template containing {variable} placeholders
        variables: Dictionary of variable names to values
        
    Returns:
        The template with variables substituted
    """
    return get_prompt_loader().substitute_variables(template, variables)


# Tool Creation convenience functions
def load_tool_creation_prompts(prompt_type: str) -> tuple[str, str]:
    """
    Convenience function to load tool creation prompts.
    
    Args:
        prompt_type: Type of prompt ('script_analysis', 'combine_docs', 'organize_final')
        
    Returns:
        Tuple of (system_prompt, user_prompt_template)
    """
    return get_prompt_loader().load_tool_creation_prompts(prompt_type)


def get_script_analysis_prompts(script_path: str, script_content: str, 
                               folder_context: str, dockerfile_content: str = "") -> tuple[str, str]:
    """
    Convenience function to get script analysis prompts.
    
    Args:
        script_path: Path to the script being analyzed
        script_content: Content of the script
        folder_context: Folder context for the script
        dockerfile_content: Optional Dockerfile content for context
        
    Returns:
        Tuple of (system_prompt, formatted_user_prompt)
    """
    loader = get_prompt_loader()
    system_prompt, _ = loader.load_tool_creation_prompts('script_analysis')
    user_prompt = loader.get_script_analysis_user_prompt(
        script_path, script_content, folder_context, dockerfile_content
    )
    return system_prompt, user_prompt


def get_script_chunk_analysis_prompts(script_path: str, chunk_content: str, 
                                     chunk_num: int, total_chunks: int,
                                     chunk_description: str, folder_context: str, 
                                     dockerfile_content: str = "") -> tuple[str, str]:
    """
    Convenience function to get prompts for analyzing a chunk of a large script.
    
    Args:
        script_path: Path to the script being analyzed
        chunk_content: Content of this specific chunk
        chunk_num: Chunk number (1-indexed)
        total_chunks: Total number of chunks
        chunk_description: Description of what this chunk contains (e.g., "Lines 1-500")
        folder_context: Folder context for the script
        dockerfile_content: Optional Dockerfile content for context
        
    Returns:
        Tuple of (system_prompt, formatted_user_prompt)
    """
    loader = get_prompt_loader()
    system_prompt, _ = loader.load_tool_creation_prompts('script_analysis')
    
    # Modified user prompt for chunk analysis
    user_prompt = f"""Analyze this section of {script_path} and extract its API definitions:

**Script: {script_path}** (Chunk {chunk_num}/{total_chunks}: {chunk_description})
**Folder Context: {folder_context}**

Dockerfile (if provided):
```
{dockerfile_content}
```

```
{chunk_content}
```

Extract ALL functions, classes, and APIs from this section. Include:
1. **Function signatures** with full parameters
2. **Return types** and values
3. **Purpose and usage**
4. **Dependencies and imports**
5. **CLI arguments** (if applicable)
6. **Configuration requirements**

Be comprehensive - this is part {chunk_num} of {total_chunks} of the complete script. 
Document everything visible in this chunk as if providing a complete reference for this section."""

    return system_prompt, user_prompt


def get_combine_docs_prompts(combined_content: str) -> tuple[str, str]:
    """
    Convenience function to get documentation combination prompts.
    
    Args:
        combined_content: Combined content from all script documentations
        
    Returns:
        Tuple of (system_prompt, formatted_user_prompt)
    """
    loader = get_prompt_loader()
    system_prompt, _ = loader.load_tool_creation_prompts('combine_docs')
    user_prompt = loader.get_combine_docs_user_prompt(combined_content)
    return system_prompt, user_prompt


def get_organize_final_prompts(scripts_path: str, total_scripts: int, 
                              folder_count: int, combined_api_doc: str) -> tuple[str, str]:
    """
    Convenience function to get final organization prompts.
    
    Args:
        scripts_path: Path to the scripts directory
        total_scripts: Total number of scripts processed
        folder_count: Number of folders in the project
        combined_api_doc: Combined API documentation
        
    Returns:
        Tuple of (system_prompt, formatted_user_prompt)
    """
    loader = get_prompt_loader()
    system_prompt, _ = loader.load_tool_creation_prompts('organize_final')
    user_prompt = loader.get_organize_final_user_prompt(
        scripts_path, total_scripts, folder_count, combined_api_doc
    )
    return system_prompt, user_prompt
