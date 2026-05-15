"""
Integration functions for parallel script analysis in tool agent creation workflow
"""

import asyncio
import os
import time
from typing import List, Dict, Any, Tuple, Optional
from parallel_script_analyzer import create_script_analyzer
from prompt_loader import get_combine_docs_prompts, get_organize_final_prompts
from llm_client import get_default_client


def analyze_scripts_parallel_integration(scripts_path: str, api_url: Optional[str] = None, api_key: Optional[str] = None, 
                                       dockerfile_content: str = "", max_concurrent: int = 10) -> str:
    """
    Enhanced parallel script analysis function to replace analyze_scripts_with_llm
    
    Args:
        scripts_path: Path to scripts directory
        api_url: DEPRECATED - Azure OpenAI API URL (now uses LLMClient from config)
        api_key: DEPRECATED - Azure OpenAI API key (now uses LLMClient from config)
        dockerfile_content: Optional Dockerfile content for context
        max_concurrent: Maximum concurrent API requests
        
    Returns:
        Combined API documentation string
    """
    script_docs = []
    folder_structure = {}
    
    if os.path.isdir(scripts_path):
        # Build folder structure
        folder_structure = build_folder_structure_parallel(scripts_path)
        
        # Collect all script files for parallel processing
        script_files = []
        for root, dirs, files in os.walk(scripts_path):
            for file in files:
                if file.endswith(('.py', '.sh', '.ps1', '.bat', '.js', '.ts')):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, scripts_path)
                    folder_context = os.path.dirname(rel_path) if os.path.dirname(rel_path) != '.' else 'root'
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            script_content = f.read()
                        
                        script_files.append({
                            'path': rel_path,
                            'content': script_content,
                            'folder_context': folder_context
                        })
                    except Exception as e:
                        print(f"Warning: Could not read {rel_path}: {e}")
        
        # Analyze scripts in parallel
        if script_files:
            # Use thread-based analyzer directly to avoid aiohttp circular import in Flask
            # Authentication now handled via centralized LLMClient (no need for api_url/api_key)
            from parallel_script_analyzer import ThreadPoolScriptAnalyzer
            analyzer = ThreadPoolScriptAnalyzer(max_workers=max_concurrent)
            script_docs, stats = analyzer.analyze_scripts_parallel_threads(script_files, dockerfile_content)
            
            # Combine all script docs into comprehensive API documentation
            if script_docs:
                combined_api_doc = combine_script_docs_parallel(
                    script_docs, folder_structure, api_url, api_key, dockerfile_content
                )
                
                # Final organizational pass
                final_doc = organize_final_documentation_parallel(
                    combined_api_doc, scripts_path, folder_structure, api_url, api_key
                )
                return final_doc
    
    return "No script documentation available"


def analyze_uploaded_scripts_parallel(shared_input_dir: str, api_url: str, api_key: str,
                                     dockerfile_content: str = "", max_concurrent: int = 5,
                                     conversation_manager = None) -> Tuple[List[Dict], str]:
    """
    Parallel analysis of uploaded scripts from session directory
    
    Args:
        shared_input_dir: Path to uploaded files directory
        api_url: Azure OpenAI API URL
        api_key: Azure OpenAI API key  
        dockerfile_content: Optional Dockerfile content
        max_concurrent: Maximum concurrent requests
        conversation_manager: Optional ConversationManager (unused in parallel mode, for compatibility)
        
    Returns:
        Tuple of (script_docs, combined_documentation)
    """
    script_files = []
    script_docs = []
    
    # Collect script files from uploads
    for root, dirs, files in os.walk(shared_input_dir):
        for file in files:
            if file.endswith(('.py', '.sh', '.ps1', '.bat', '.js', '.ts')):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, shared_input_dir).replace('\\', '/')
                folder_context = os.path.dirname(rel_path) or '.'
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    script_files.append({
                        'path': rel_path,
                        'content': content,
                        'folder_context': folder_context
                    })
                except Exception as e:
                    print(f"Warning: Could not read uploaded script {rel_path}: {e}")
    
    if script_files:
        print(f"🔍 Analyzing {len(script_files)} uploaded scripts in parallel...")
        
        # Use thread-based analyzer to avoid aiohttp circular import issues in Flask context
        # Authentication now handled via centralized LLMClient (no need for api_url/api_key)
        from parallel_script_analyzer import ThreadPoolScriptAnalyzer
        analyzer = ThreadPoolScriptAnalyzer(max_workers=max_concurrent)
        script_docs, stats = analyzer.analyze_scripts_parallel_threads(script_files, dockerfile_content)
        
        # Build folder structure for uploaded files
        folder_structure = build_folder_structure_parallel(shared_input_dir)
        
        # Combine docs
        combined_docs = combine_script_docs_parallel(
            script_docs, folder_structure, api_url, api_key, dockerfile_content
        )
        
        return script_docs, combined_docs
    
    return [], "No uploaded scripts found for analysis"


def build_folder_structure_parallel(scripts_path: str) -> Dict:
    """Enhanced folder structure builder with parallel processing support"""
    structure = {
        'root_path': scripts_path,
        'folders': {},
        'files_by_folder': {},
        'total_files': 0,
        'folder_summary': [],
        'processing_metadata': {
            'total_scripts': 0,
            'total_other_files': 0,
            'folder_count': 0
        }
    }
    
    for root, dirs, files in os.walk(scripts_path):
        rel_root = os.path.relpath(root, scripts_path)
        if rel_root == '.':
            rel_root = 'root'
        
        structure['processing_metadata']['folder_count'] += 1
        
        # Categorize files
        script_files = []
        other_files = []
        for file in files:
            if file.endswith(('.py', '.sh', '.ps1', '.bat', '.js', '.ts')):
                script_files.append(file)
                structure['total_files'] += 1
                structure['processing_metadata']['total_scripts'] += 1
            elif file.endswith(('.md', '.txt', '.json', '.yaml', '.yml', '.cfg', '.ini', '.toml')):
                other_files.append(file)
                structure['processing_metadata']['total_other_files'] += 1
        
        if script_files or other_files:
            structure['folders'][rel_root] = {
                'path': root,
                'subdirs': dirs,
                'script_files': script_files,
                'other_files': other_files
            }
            
            structure['files_by_folder'][rel_root] = script_files
            
            # Create folder summary
            folder_desc = f"{rel_root}: {len(script_files)} scripts"
            if other_files:
                folder_desc += f", {len(other_files)} config/docs"
            structure['folder_summary'].append(folder_desc)
    
    return structure


def combine_script_docs_parallel(script_docs: List[Dict], folder_structure: Dict, 
                                api_url: Optional[str] = None, api_key: Optional[str] = None, dockerfile_content: str = "") -> str:
    """
    Parallel-aware version of combine_script_docs_into_api_doc
    Optimized for handling results from parallel analysis
    
    Args:
        script_docs: List of analyzed script documentation
        folder_structure: Directory structure metadata
        api_url: DEPRECATED - Azure OpenAI API URL (now uses LLMClient from config)
        api_key: DEPRECATED - Azure OpenAI API key (now uses LLMClient from config)
        dockerfile_content: Optional Dockerfile content for context
    """
    # Create folder-organized summary
    folder_summary = "\n".join(folder_structure.get('folder_summary', []))
    
    # Group scripts by folder
    scripts_by_folder = {}
    for doc in script_docs:
        folder = doc['folder_context']
        if folder not in scripts_by_folder:
            scripts_by_folder[folder] = []
        scripts_by_folder[folder].append(doc)
    
    # Create organized summary
    folder_org = []
    for folder, docs in scripts_by_folder.items():
        doc_list = [f"- {doc['script_path']}: {len(doc['documentation'])} chars" for doc in docs]
        folder_org.append(f"{folder}/:\n" + "\n".join(doc_list))
    
    # Combine all documentation
    all_docs = []
    for doc in script_docs:
        doc_text = f"## {doc['script_path']} ({doc['folder_context']})\n{doc['documentation']}"
        all_docs.append(doc_text)

    combined_content = f"""
# Project Structure
{folder_summary}

# Folder Organization
{chr(10).join(folder_org)}

# Individual Script Documentation
{chr(10).join(all_docs)}

# Dockerfile Context
{dockerfile_content[:1000]}{'...' if len(dockerfile_content) > 1000 else ''}
"""

    # Load prompts from external files
    system_prompt, user_prompt = get_combine_docs_prompts(combined_content)

    try:
        # Use LLMClient which handles both API Key and Azure AD authentication
        llm_client = get_default_client()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response_data = llm_client.call_azure_openai_direct(
            messages,
            max_output_tokens=16384,
            temperature=0.1,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            stream=False
        )
        
        if 'choices' in response_data and response_data['choices']:
            choice = response_data['choices'][0]
            if 'message' in choice and 'content' in choice['message']:
                return choice['message']['content']
        
    except Exception as e:
        print(f"Error combining script docs: {e}")
    
    # Fallback: return concatenated documentation
    return combined_content


def organize_final_documentation_parallel(combined_api_doc: str, scripts_path: str, 
                                        folder_structure: Dict, api_url: Optional[str] = None, api_key: Optional[str] = None) -> str:
    """
    Parallel-aware version of organize_api_documentation
    Enhanced with folder structure context
    
    Args:
        combined_api_doc: Combined API documentation string
        scripts_path: Path to scripts directory
        folder_structure: Directory structure metadata
        api_url: DEPRECATED - Azure OpenAI API URL (now uses LLMClient from config)
        api_key: DEPRECATED - Azure OpenAI API key (now uses LLMClient from config)
    """
    try:
        # Get metadata for prompt
        total_scripts = folder_structure.get('processing_metadata', {}).get('total_scripts', 0)
        folder_count = folder_structure.get('processing_metadata', {}).get('folder_count', 0)
        
        # Load prompts from external files
        system_prompt, user_prompt = get_organize_final_prompts(
            scripts_path, total_scripts, folder_count, combined_api_doc
        )

        # Use LLMClient which handles both API Key and Azure AD authentication
        llm_client = get_default_client()
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response_data = llm_client.call_azure_openai_direct(
            messages,
            max_output_tokens=16384,
            temperature=0.1,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            stream=False
        )
        
        if 'choices' in response_data and response_data['choices']:
            choice = response_data['choices'][0]
            if 'message' in choice and 'content' in choice['message']:
                return choice['message']['content']
        
    except Exception as e:
        print(f"Error in final organization: {e}")
    
    # Return original if organization fails
    return combined_api_doc


# Configuration management for parallel processing
PARALLEL_CONFIG = {
    'max_concurrent_requests': int(os.getenv('TOOL_AGENT_MAX_CONCURRENT', '10')),
    'use_async_by_default': os.getenv('TOOL_AGENT_USE_ASYNC', 'true').lower() == 'true',
    'timeout_seconds': int(os.getenv('TOOL_AGENT_TIMEOUT', '120')),
    'fallback_to_threading': os.getenv('TOOL_AGENT_FALLBACK_THREADING', 'true').lower() == 'true'
}

def get_parallel_config() -> Dict[str, Any]:
    """Get current parallel processing configuration"""
    return PARALLEL_CONFIG.copy()

def update_parallel_config(**kwargs):
    """Update parallel processing configuration"""
    PARALLEL_CONFIG.update(kwargs)
