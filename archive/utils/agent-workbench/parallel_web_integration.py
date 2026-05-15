"""
Web server modifications for parallel script analysis integration
This file shows the changes needed in web_server.py to enable parallel processing
"""

# Add these imports at the top of web_server.py
# from parallel_integration import analyze_scripts_parallel_integration, analyze_uploaded_scripts_parallel, get_parallel_config

def modify_generate_tool_agent_definitions():
    """
    This function shows the modifications needed in the generate_tool_agent_definitions endpoint
    to enable parallel script analysis
    """
    
    # BEFORE: Original sequential processing (around line 10250 in web_server.py)
    original_code = """
    if os.path.isdir(resolved_scripts_path):
        # Analyze script directory with LLM-generated documentation
        try:
            print(f"  🔍 Analyzing scripts directory with enhanced LLM analysis")
            if conversation_manager and api_url and subscription_key:
                scripts_info = analyze_scripts_with_llm(resolved_scripts_path, conversation_manager)
                print(f"  ✅ Scripts analyzed with enhanced 3-stage LLM process: {len(scripts_info)} chars comprehensive documentation")
            else:
                # Fallback to basic file listing if LLM not available
                script_files = []
                for root, dirs, files in os.walk(resolved_scripts_path):
                    for file in files:
                        if file.endswith(('.py', '.sh', '.ps1', '.bat', '.js', '.ts')):
                            rel_path = os.path.relpath(os.path.join(root, file), resolved_scripts_path)
                            script_files.append(rel_path)
                scripts_info = f"Script files found (basic listing - LLM analysis not available):\\n" + "\\n".join(script_files)
                print(f"  ⚠️ Scripts directory scanned (basic mode): {len(script_files)} files")
    """
    
    # AFTER: Parallel processing replacement
    new_code = """
    if os.path.isdir(resolved_scripts_path):
        # Analyze script directory with PARALLEL LLM analysis
        try:
            print(f"  🚀 Analyzing scripts directory with PARALLEL LLM analysis")
            if conversation_manager and api_url and subscription_key:
                # Get parallel configuration
                parallel_config = get_parallel_config()
                max_concurrent = parallel_config['max_concurrent_requests']
                
                print(f"  🔧 Using parallel analysis with {max_concurrent} concurrent requests")
                scripts_info = analyze_scripts_parallel_integration(
                    resolved_scripts_path, api_url, subscription_key, dockerfile_content, max_concurrent
                )
                print(f"  ✅ Scripts analyzed with PARALLEL LLM process: {len(scripts_info)} chars comprehensive documentation")
            else:
                # Fallback to basic file listing if LLM not available
                script_files = []
                for root, dirs, files in os.walk(resolved_scripts_path):
                    for file in files:
                        if file.endswith(('.py', '.sh', '.ps1', '.bat', '.js', '.ts')):
                            rel_path = os.path.relpath(os.path.join(root, file), resolved_scripts_path)
                            script_files.append(rel_path)
                scripts_info = f"Script files found (basic listing - LLM analysis not available):\\n" + "\\n".join(script_files)
                print(f"  ⚠️ Scripts directory scanned (basic mode): {len(script_files)} files")
    """
    
    # BEFORE: Original uploaded scripts processing (around line 10290 in web_server.py)  
    original_uploaded_code = """
    # Try to gather uploaded scripts from ephemeral storage
    if inputs_summary.get('scripts'):
        try:
            script_docs = []
            script_files_count = 0
            for s in inputs_summary['scripts']:
                # s is a relative path (e.g., 'subdir/io_utils.py') relative to shared_input_dir
                p = os.path.join(shared_input_dir, *s.split('/'))
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        content = f.read()
                    script_files_count += 1

                    # If conversation_manager and LLM are available, analyze each script individually
                    if conversation_manager and api_url and subscription_key:
                        try:
                            folder_ctx = os.path.dirname(s) or '.'
                            print(f"  🎯 Sending script to LLM analysis: '{s}'")
                            doc = extract_script_api_documentation(s, content, folder_ctx, conversation_manager, dockerfile_content)
                            if doc:
                                script_docs.append(doc)
                        except Exception as e:
                            # Fallback to raw inclusion if analysis fails for a file
                            errors.append(f"LLM analysis failed for {s}: {e}")
                            script_docs.append({'script_path': s, 'folder_context': folder_ctx, 'documentation': f"# {s}\\n" + content, 'size': len(content)})
                    else:
                        # No LLM available: include raw content with header
                        folder_ctx = os.path.dirname(s) or '.'
                        script_docs.append({'script_path': s, 'folder_context': folder_ctx, 'documentation': f"# {s}\\n" + content, 'size': len(content)})

                except Exception as e:
                    errors.append(f"Could not read uploaded script {s}: {str(e)}")

            # Combine per-file docs into a single organized API document when possible
            if script_docs:
                try:
                    # Build an actual folder structure from the uploads directory so the combiner gets accurate context
                    folder_structure = build_folder_structure(shared_input_dir)
                    folder_structure['total_files'] = len(script_docs)
                    
                    combined = combine_script_docs_into_api_doc(script_docs, folder_structure, conversation_manager, dockerfile_content)
                    scripts_info = combined
                    print(f"  ✅ Scripts analyzed and combined from uploads: {len(script_docs)} files")
                except Exception as e:
                    # Fallback: concatenate raw docs
                    scripts_info = "\\n\\n".join([d.get('documentation','') for d in script_docs])
                    errors.append(f"Could not combine script docs: {e}")
                    print(f"  ⚠️ Could not combine script docs into organized doc: {e}")
    """
    
    # AFTER: Parallel uploaded scripts processing
    new_uploaded_code = """
    # Try to gather uploaded scripts from ephemeral storage with PARALLEL processing
    if inputs_summary.get('scripts'):
        try:
            print(f"  🚀 Starting PARALLEL analysis of {len(inputs_summary['scripts'])} uploaded scripts")
            
            if conversation_manager and api_url and subscription_key:
                # Get parallel configuration
                parallel_config = get_parallel_config()
                max_concurrent = parallel_config['max_concurrent_requests']
                
                print(f"  🔧 Using parallel analysis with {max_concurrent} concurrent requests")
                script_docs, scripts_info = analyze_uploaded_scripts_parallel(
                    shared_input_dir, api_url, subscription_key, dockerfile_content, max_concurrent
                )
                print(f"  ✅ PARALLEL analysis completed: {len(script_docs)} scripts processed")
            else:
                # Fallback to basic processing without LLM
                script_docs = []
                for s in inputs_summary['scripts']:
                    p = os.path.join(shared_input_dir, *s.split('/'))
                    try:
                        with open(p, 'r', encoding='utf-8') as f:
                            content = f.read()
                        folder_ctx = os.path.dirname(s) or '.'
                        script_docs.append({
                            'script_path': s, 
                            'folder_context': folder_ctx, 
                            'documentation': f"# {s}\\n" + content, 
                            'size': len(content)
                        })
                    except Exception as e:
                        errors.append(f"Could not read uploaded script {s}: {str(e)}")
                
                scripts_info = "\\n\\n".join([d.get('documentation','') for d in script_docs])
                print(f"  ⚠️ Basic processing completed: {len(script_docs)} scripts")
    """

def add_parallel_config_endpoint():
    """
    New endpoint to manage parallel processing configuration
    Add this to web_server.py
    """
    endpoint_code = """
@app.route('/api/parallel-config', methods=['GET', 'POST'])
def manage_parallel_config():
    '''Manage parallel processing configuration for tool agent creation'''
    if request.method == 'GET':
        from parallel_integration import get_parallel_config
        config = get_parallel_config()
        return jsonify({
            'success': True,
            'config': config,
            'description': {
                'max_concurrent_requests': 'Maximum number of concurrent LLM API requests',
                'use_async_by_default': 'Whether to use async processing by default',
                'timeout_seconds': 'Timeout for individual API requests',
                'fallback_to_threading': 'Whether to fallback to threading if async fails'
            }
        })
    
    elif request.method == 'POST':
        try:
            from parallel_integration import update_parallel_config
            
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': 'No configuration data provided'}), 400
            
            # Validate and update configuration
            valid_keys = ['max_concurrent_requests', 'use_async_by_default', 'timeout_seconds', 'fallback_to_threading']
            update_data = {k: v for k, v in data.items() if k in valid_keys}
            
            if not update_data:
                return jsonify({'success': False, 'error': 'No valid configuration keys provided'}), 400
            
            # Type validation
            if 'max_concurrent_requests' in update_data:
                update_data['max_concurrent_requests'] = int(update_data['max_concurrent_requests'])
                if update_data['max_concurrent_requests'] < 1 or update_data['max_concurrent_requests'] > 20:
                    return jsonify({'success': False, 'error': 'max_concurrent_requests must be between 1 and 20'}), 400
            
            if 'timeout_seconds' in update_data:
                update_data['timeout_seconds'] = int(update_data['timeout_seconds'])
                if update_data['timeout_seconds'] < 30 or update_data['timeout_seconds'] > 300:
                    return jsonify({'success': False, 'error': 'timeout_seconds must be between 30 and 300'}), 400
            
            update_parallel_config(**update_data)
            
            return jsonify({
                'success': True,
                'message': 'Parallel configuration updated successfully',
                'updated_config': get_parallel_config()
            })
            
        except Exception as e:
            return jsonify({'success': False, 'error': f'Configuration update failed: {str(e)}'}), 500
"""
    return endpoint_code

def add_parallel_status_endpoint():
    """
    New endpoint to monitor parallel processing status
    Add this to web_server.py
    """
    endpoint_code = """
@app.route('/api/parallel-status', methods=['GET'])
def get_parallel_status():
    '''Get current parallel processing status and statistics'''
    try:
        from parallel_integration import get_parallel_config
        import psutil
        import asyncio
        
        config = get_parallel_config()
        
        # Get system information
        cpu_count = psutil.cpu_count()
        memory_info = psutil.virtual_memory()
        
        # Check if async loop is running
        try:
            loop = asyncio.get_running_loop()
            async_available = True
            async_tasks = len([task for task in asyncio.all_tasks(loop) if not task.done()])
        except RuntimeError:
            async_available = False
            async_tasks = 0
        
        # Calculate recommended settings
        recommended_concurrent = min(max(2, cpu_count // 2), 8)
        
        status = {
            'current_config': config,
            'system_info': {
                'cpu_cores': cpu_count,
                'memory_gb': round(memory_info.total / (1024**3), 2),
                'memory_available_gb': round(memory_info.available / (1024**3), 2),
                'memory_usage_percent': memory_info.percent
            },
            'async_info': {
                'async_available': async_available,
                'active_tasks': async_tasks
            },
            'recommendations': {
                'recommended_concurrent_requests': recommended_concurrent,
                'recommended_timeout': 120,
                'performance_notes': [
                    f"System has {cpu_count} CPU cores",
                    f"Recommended concurrent requests: {recommended_concurrent}",
                    "Higher concurrency may improve speed but increase memory usage",
                    "Monitor API rate limits and adjust accordingly"
                ]
            }
        }
        
        return jsonify({'success': True, 'status': status})
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Status check failed: {str(e)}'}), 500
"""
    return endpoint_code

# Summary of changes needed
INTEGRATION_SUMMARY = '''
INTEGRATION PLAN FOR PARALLEL SCRIPT ANALYSIS

1. File Structure:
   ├── parallel_script_analyzer.py (✅ Created)
   ├── parallel_integration.py (✅ Created)  
   └── web_server.py (Needs modification)

2. Web Server Changes:
   a) Add imports:
      from parallel_integration import (
          analyze_scripts_parallel_integration, 
          analyze_uploaded_scripts_parallel, 
          get_parallel_config
      )
   
   b) Replace sequential script processing in generate_tool_agent_definitions():
      - Line ~10250: Replace analyze_scripts_with_llm() call
      - Line ~10290: Replace sequential uploaded script processing
   
   c) Add new endpoints:
      - /api/parallel-config (GET/POST)
      - /api/parallel-status (GET)

3. Configuration:
   Environment variables for tuning:
   - TOOL_AGENT_MAX_CONCURRENT=5
   - TOOL_AGENT_USE_ASYNC=true 
   - TOOL_AGENT_TIMEOUT=120
   - TOOL_AGENT_FALLBACK_THREADING=true

4. Performance Benefits:
   - Sequential: N scripts × 2-5 seconds each = 10-50 seconds for 10 scripts
   - Parallel: max(N/concurrent, longest_script) = 2-10 seconds for 10 scripts
   - Expected speedup: 3-5x for typical workloads

5. Fallback Strategy:
   - Primary: AsyncIO with aiohttp for concurrent API calls
   - Fallback: ThreadPoolExecutor for environments without async support
   - Ultimate fallback: Original sequential processing if both fail

6. Monitoring:
   - Real-time progress tracking
   - Error handling per script
   - Performance statistics
   - System resource monitoring
'''

def print_integration_plan():
    """Print the complete integration plan"""
    print(INTEGRATION_SUMMARY)
