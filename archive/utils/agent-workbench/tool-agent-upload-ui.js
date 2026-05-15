// Modal-scoped upload UI for Tool Agent creation using Dropzone
(function(){
    const uploadsMap = new Map(); // key: uploaded filename -> { originalName, uploadedName, type }

    function categorizeFilename(name){
        const ln = name.toLowerCase();
        if(ln === 'dockerfile' || ln.endsWith('/dockerfile') || ln.endsWith('dockerfile') || ln.endsWith('.dockerfile')) return 'Dockerfile';
        if(ln.endsWith('.yaml')||ln.endsWith('.yml')||ln.endsWith('.json')||ln.endsWith('.md')||ln.endsWith('.txt')) return 'Docs';
        if(ln.endsWith('.py')||ln.endsWith('.js')||ln.endsWith('.ts')||ln.endsWith('.go')||ln.endsWith('.java')||ln.endsWith('.sh')||ln.endsWith('.ps1')||ln.endsWith('.bat')) return 'Script';
        return 'Other';
    }

    function $(id){ return document.getElementById(id); }

    function sanitizeContent(content){
        if(!content) return '';
        let s = String(content).replace(/\uFEFF/g, '').replace(/\u200B/g, '').replace(/\u200C/g, '').replace(/\u200D/g, '').replace(/\u2060/g, '').trim();
        // Fix unclosed code fences
        const openingBlocks = (s.match(/```[\w]*\n/g) || []).length;
        const closingBlocks = (s.match(/\n```/g) || []).length;
        if(openingBlocks > closingBlocks) s += '\n```';
        return s;
    }

    function init(){
        const dzEl = $('toolDropzone');
        const folderInput = $('toolUploadFolderInput');
        const validationEl = $('toolUploadValidation');
        const modal = $('createToolAgentModal');

        if(!dzEl) return;

        // Configure Dropzone (use tool-agent per-session upload endpoint)
        let sessionId = null;

    // Helper to create a session and set sessionId (returns the id)
        async function startSession(){
            try{
                const r = await fetch('/api/tool-agent/start-session', { method: 'POST' });
                const d = await r.json();
                if(d && d.success && d.sessionId){ sessionId = d.sessionId; return sessionId; }
                // If response didn't include a session, clear and report
                sessionId = null;
                return null;
            }catch(e){ sessionId = null; return null; }
        }
    // Prevent Dropzone auto-attaching itself elsewhere which can cause "Dropzone already attached." errors
    try{ if(window.Dropzone) window.Dropzone.autoDiscover = false; }catch(e){}

    const dz = new Dropzone(dzEl, {
            url: '/api/tool-agent/upload',
            autoProcessQueue: true,
            parallelUploads: 4,
            maxFilesize: 50, // MB per file
            clickable: false, // Disable default clickable behavior - we'll handle it manually
            addRemoveLinks: true,
            init: function(){
                const self = this;

                // Attach sessionId to each upload when sending
                self.on('sending', function(file, xhr, formData){
                    try{
                        if(sessionId) formData.append('sessionId', sessionId);
                        // Preserve client-side relative path when available (directory uploads).
                        // We append both common field names so the server can accept whichever is present.
                        const rel = file._relativePath || file.webkitRelativePath || file.relativePath || (file.fullPath ? file.fullPath.replace(/^\\/,'') : null) || file.name;
                        if(rel){
                            formData.append('relativePath', rel);
                            formData.append('webkitRelativePath', rel);
                        }
                    }catch(e){}
                });

                self.on('addedfile', function(file){
                    // categorize and keep a mapping
                    const cat = categorizeFilename(file.name);
                    const originalRelative = file.webkitRelativePath || file.relativePath || (file.fullPath ? file.fullPath.replace(/^\\/,'') : null) || file.name;
                    // Ensure the File object carries a stable relative path property that survives Dropzone handling.
                    try{
                        // store on a private property and also set common names to maximize cross-browser support
                        file._relativePath = originalRelative;
                        if(!file.relativePath) file.relativePath = originalRelative;
                        if(!file.webkitRelativePath) file.webkitRelativePath = originalRelative;
                    }catch(e){}

                    uploadsMap.set(file.name, { originalName: file.name, originalRelativePath: originalRelative, uploadedName: null, type: cat, status: 'queued' });
                    updateValidation();
                });

                self.on('success', function(file, resp){
                    // resp expected: { message, filename, success: true }
                    const data = resp || {};
                    const uploadedName = data.filename || file.name;
                    const meta = uploadsMap.get(file.name) || { originalName: file.name };
                    meta.uploadedName = uploadedName; // stored relative path returned by server
                    if(data.sessionId) sessionId = data.sessionId;
                    meta.sessionId = sessionId;
                    meta.status = 'uploaded';
                    uploadsMap.set(file.name, meta);
                    updateValidation();
                });

                self.on('error', function(file, err){
                    const meta = uploadsMap.get(file.name) || { originalName: file.name };
                    meta.status = 'error';
                    uploadsMap.set(file.name, meta);
                    updateValidation();
                });

                self.on('removedfile', function(file){
                    // Remove mapping and optionally delete server file if uploaded
                    const meta = uploadsMap.get(file.name);
                    if(meta && meta.uploadedName){
                        // Attempt server delete in the session folder (best-effort)
                        const sid = meta.sessionId || sessionId || '';
                        if(sid){
                            fetch(`/api/tool-agent/delete/${encodeURIComponent(sid)}/${encodeURIComponent(meta.uploadedName)}`, { method: 'DELETE' }).catch(()=>{});
                        } else {
                            // Fallback to global inputs delete if session unknown
                            fetch(`/api/inputs/delete/${encodeURIComponent(meta.uploadedName)}`, { method: 'DELETE' }).catch(()=>{});
                        }
                    }
                    uploadsMap.delete(file.name);
                    updateValidation();
                });
            }
        });

        // Support folder input for browsers that allow it
        if(folderInput){
            folderInput.addEventListener('change', (e)=>{
                const files = Array.from(e.target.files || []);
                // When selecting a folder, Dropzone won't see these automatically; add them programmatically
                files.forEach(f=> dz.addFile(f));
                folderInput.value = '';
            });
        }

        // Manual Browse button handling - provide choice between files and folders
        // Note: Browse button is now outside dz-message so it stays visible when files are added
        const browseBtn = dzEl.querySelector('.dz-browse-btn');
        if(browseBtn){
            browseBtn.addEventListener('click', (e)=>{
                e.preventDefault();
                e.stopPropagation();
                
                // Create and show a simple choice menu
                const menu = document.createElement('div');
                menu.className = 'browse-choice-menu';
                menu.style.cssText = `
                    position: fixed;
                    background: white;
                    border: 1px solid #ccc;
                    border-radius: 4px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
                    z-index: 99999;
                    min-width: 160px;
                    padding: 4px 0;
                `;
                
                // Position the menu near the button with better visibility
                const rect = browseBtn.getBoundingClientRect();
                menu.style.left = rect.left + 'px';
                menu.style.top = (rect.bottom + 2) + 'px';
                
                // Create file selection option
                const fileOption = document.createElement('div');
                fileOption.className = 'browse-menu-item';
                fileOption.style.cssText = `
                    padding: 8px 16px;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                `;
                fileOption.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M4 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H4zm0 1h8a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/>
                    </svg>
                    Select Files
                `;
                
                // Create folder selection option  
                const folderOption = document.createElement('div');
                folderOption.className = 'browse-menu-item';
                folderOption.style.cssText = fileOption.style.cssText;
                folderOption.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M.5 3l.04.87a1.99 1.99 0 0 0-.342 1.311l.637 7A2 2 0 0 0 2.826 14H9.81a2 2 0 0 0 1.991-1.819l.637-7a1.99 1.99 0 0 0-.342-1.31L12.5 3h2a.5.5 0 0 1 0 1h-2v.5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 .5 4.5V4h2a.5.5 0 0 1 0-1h-2z"/>
                    </svg>
                    Select Folder
                `;
                
                // Add hover effects
                [fileOption, folderOption].forEach(option => {
                    option.addEventListener('mouseenter', () => {
                        option.style.backgroundColor = '#f0f0f0';
                    });
                    option.addEventListener('mouseleave', () => {
                        option.style.backgroundColor = '';
                    });
                });
                
                // Handle file selection
                fileOption.addEventListener('click', () => {
                    menu.remove();
                    // Create temporary file input for individual files
                    const fileInput = document.createElement('input');
                    fileInput.type = 'file';
                    fileInput.multiple = true;
                    fileInput.style.display = 'none';
                    fileInput.addEventListener('change', (e) => {
                        const files = Array.from(e.target.files || []);
                        files.forEach(f => dz.addFile(f));
                        fileInput.remove();
                    });
                    document.body.appendChild(fileInput);
                    fileInput.click();
                });
                
                // Handle folder selection
                if(folderInput){
                    folderOption.addEventListener('click', () => {
                        menu.remove();
                        folderInput.click(); // Trigger the folder input with webkitdirectory
                    });
                } else {
                    // Disable folder option if not supported
                    folderOption.style.opacity = '0.5';
                    folderOption.style.cursor = 'not-allowed';
                    folderOption.title = 'Folder selection not supported in this browser';
                }
                
                // Add options to menu
                menu.appendChild(fileOption);
                menu.appendChild(folderOption);
                
                // Add menu to body
                document.body.appendChild(menu);
                
                // Remove menu when clicking outside
                const removeMenu = (event) => {
                    if (!menu.contains(event.target)) {
                        menu.remove();
                        document.removeEventListener('click', removeMenu);
                    }
                };
                setTimeout(() => {
                    document.addEventListener('click', removeMenu);
                }, 0);
            });
        }

        // When modal opens, clear previous state and start a new session for tool-agent uploads
    const mo = new MutationObserver((mutations)=>{
            for(const m of mutations){
                if(m.attributeName === 'class'){
                    const hidden = modal.classList.contains('hidden');
                        if(!hidden){
                        // Reset dropzone
                        dz.removeAllFiles(true);
                        uploadsMap.clear();
                        updateValidation();
                        // Start new tool-agent session (ensure sessionId exists)
                        startSession().catch(()=>{ sessionId = null; });
                    }
                    else {
                        // Modal was hidden: attempt to cleanup session folder
                        try{
                            if(sessionId){
                                fetch(`/api/tool-agent/delete-session/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }).catch(()=>{});
                                sessionId = null;
                            }
                        }catch(e){}
                    }
                }
            }
        });
        if(modal) mo.observe(modal, { attributes: true });

        // Helper: attempt to sync generated definitions into global discoveryAgent.toolAgentCreator
        // Retries for a short period in case the global instance isn't initialized yet (race condition)
        function syncGeneratedDefinitionsToGlobal(data, maxAttempts = 10, delay = 200){
            let attempts = 0;
            const trySync = () => {
                attempts++;
                try{
                    const globalDiscovery = (typeof discoveryAgent !== 'undefined') ? discoveryAgent : (window.discoveryAgent || null);
                    if(globalDiscovery && globalDiscovery.toolAgentCreator){
                        const tac = globalDiscovery.toolAgentCreator;
                        tac.generatedDefinitions = tac.generatedDefinitions || { tooldef: '', agentdef: '', apidocs: '' };
                        tac.generatedDefinitions.tooldef = (data.toolDefinition || '');
                        tac.generatedDefinitions.agentdef = (data.agentDefinition || '');
                        tac.generatedDefinitions.apidocs = (data.apiDocumentation || '');
                        
                        // Store sessionId and dockerfileRelPath for intelligent Dockerfile discovery during finalization
                        if(sessionId && tac.toolData) {
                            tac.toolData.sessionId = sessionId;
                        }
                        if(data.dockerfileRelPath && tac.toolData) {
                            tac.toolData.dockerfileRelPath = data.dockerfileRelPath;
                        }
                        
                        // Keep the creator's textarea elements in-sync as well
                        try{ if(tac.toolDefinitionTextarea) tac.toolDefinitionTextarea.value = tac.generatedDefinitions.tooldef; }catch(e){}
                        try{ if(tac.agentDefinitionTextarea) tac.agentDefinitionTextarea.value = tac.generatedDefinitions.agentdef; }catch(e){}
                        
                        // Update CodeMirror instances with the new content
                        try{ 
                            if(tac.toolDefinitionCodeMirror) {
                                tac.toolDefinitionCodeMirror.setValue(tac.generatedDefinitions.tooldef);
                            }
                        }catch(e){}
                        
                        try{ 
                            if(tac.agentDefinitionCodeMirror) {
                                tac.agentDefinitionCodeMirror.setValue(tac.generatedDefinitions.agentdef);
                            }
                        }catch(e){}
                        
                        return true;
                    }
                }catch(e){ /* swallow */ }
                if(attempts < maxAttempts){
                    setTimeout(trySync, delay);
                } else {
                    console.warn('[Dropzone] Failed to sync generated definitions to global ToolAgentCreator after', attempts, 'attempts');
                }
            };
            trySync();
        }

        // Hook the Generate Definitions button: validate then wait for uploads to complete, then call generation
        const generateBtn = $('toolModalNextBtn');
        if(generateBtn){
            generateBtn.addEventListener('click', async ()=>{
                const name = $('toolAgentName')?.value?.trim() || 'UnnamedTool';
                const ok = validateForGeneration();
                if(!ok) return;

                // Disable button for the generation process
                generateBtn.disabled = true;

                try{
                    // Ensure a session exists before attempting generation
                    if(!sessionId){
                        // Try to pick up sessionId from any uploaded file metadata first
                        for(const m of uploadsMap.values()){ if(m && m.sessionId){ sessionId = m.sessionId; break; } }
                        if(!sessionId){
                            // Create a fresh session if none found
                            const sid = await startSession();
                            if(!sid){
                                showValidation('Generation error: could not create upload session; please try again');
                                return;
                            }
                        }
                    }
                    // Wait for all queued files to finish uploading
                    await waitForUploadsToFinish(dz);

                    // Build payload using uploaded filenames
                    const uploadedFilenames = Array.from(uploadsMap.values()).map(m => m.uploadedName || m.originalName);
                    // If sessionId not set, try to pick it up from any uploaded file metadata
                    if(!sessionId){
                        for(const m of uploadsMap.values()){
                            if(m && m.sessionId){ sessionId = m.sessionId; break; }
                        }
                    }
                    // Choose how to populate apisPath/scriptsPath:
                    // - If exactly one matching file exists, pass it so server treats it as a single-file scriptsPath
                    // - If multiple matching files exist, leave the path blank so server will aggregate uploaded files from the session uploads
                    const dockerfileCandidate = uploadedFilenames.find(n=> /dockerfile/i.test(n)) || '';
                    const docMatches = uploadedFilenames.filter(n=> /\.(yaml|yml|json|md|txt)$/i.test(n));
                    const scriptMatches = uploadedFilenames.filter(n=> /\.(py|js|ts|go|java|sh|ps1|bat)$/i.test(n));

                    // Get SKU data from the ToolAgentCreator instance if available
                    let skuData = {};
                    try {
                        if (window.discoveryAgent && window.discoveryAgent.toolAgentCreator) {
                            skuData = window.discoveryAgent.toolAgentCreator.getSelectedSkuData();
                            console.log('🔍 DEBUG: Upload UI collected SKU data:', skuData);
                        }
                    } catch (e) {
                        console.warn('⚠️ Could not get SKU data from ToolAgentCreator:', e);
                    }

                    const body = {
                        toolName: name,
                        toolDescription: '',
                        dockerImage: '',
                        dockerfilePath: dockerfileCandidate,
                        apiSpecs: '',
                        apisPath: docMatches.length === 1 ? docMatches[0] : '',
                        scriptsPath: scriptMatches.length === 1 ? scriptMatches[0] : '',
                        sessionId: sessionId,
                        // Include SKU data in the request
                        ...skuData
                    };

                    // Set up SSE listener for generation progress
                    let sseClient = null;
                    let subscriptionId = null;
                    
                    try {
                        if (window.SSEClient) {
                            console.log('[SSE] Setting up SSE client for generation tracking');
                            sseClient = new window.SSEClient();
                            
                            // Subscribe to validation channel for this generation
                            subscriptionId = sseClient.subscribe(['validation'], { generation_id: sessionId, tool_name: name }, (event) => {
                                console.log('[SSE] Generation progress event received:', event);
                                // Update status line
                                showValidation(event.message);
                                // Also add to activity tab if available
                                if (window.activityLogger && window.activityLogger.addActivity) {
                                    window.activityLogger.addActivity(event.message, event.level || 'info');
                                }
                            });
                            
                            sseClient.connect();
                        }
                    } catch (e) {
                        console.error('SSE setup failed:', e);
                    }

                    try {
                        // Show initial progress
                        showValidation('Analyzing uploaded files...');
                        
                        // Start the generation request
                        const resp = await fetch('/api/generate-tool-agent-definitions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
                        
                        console.log('[Generation] Fetch completed, parsing response...');
                        const data = await resp.json();
                        console.log('[Generation] Response parsed:', data);
                        
                        // Clean up SSE subscription
                        if (sseClient && subscriptionId) {
                            console.log('[SSE] Cleaning up subscription');
                            sseClient.unsubscribe(subscriptionId);
                            sseClient.disconnect();
                        }
                        
                        if(!data.success){ 
                            console.error('[Generation] Failed:', data.error);
                            showValidation('❌ Generation failed: ' + (data.error || 'Unknown')); 
                            return; 
                        }
                        
                        // Show completion
                        console.log('[Generation] Success! Updating UI...');
                        showValidation('✅ Generation complete!');
                        
                        // Clear the success message after a short delay
                        setTimeout(() => showValidation(''), 3000);

                        // Fill modal Step 2 areas
                        const toolTextarea = document.getElementById('toolDefinitionYaml');
                        const agentTextarea = document.getElementById('toolAgentDefinitionYaml');
                        const apiDocsContainer = document.getElementById('apiDocsContent');
                        
                        console.log('[Generation] Filling textareas...', {
                            toolTextarea: !!toolTextarea,
                            agentTextarea: !!agentTextarea,
                            toolDefLength: data.toolDefinition?.length,
                            agentDefLength: data.agentDefinition?.length
                        });
                        
                        if(toolTextarea) { toolTextarea.value = data.toolDefinition || ''; }
                        if(agentTextarea) { agentTextarea.value = data.agentDefinition || ''; }
                        
                        // Also sync generated definitions into the ToolAgentCreator instance (if present)
                        try{
                            syncGeneratedDefinitionsToGlobal(data);
                            console.log('[Generation] Synced to global ToolAgentCreator');
                        }catch(e){ 
                            console.warn('[Generation] Could not sync to global:', e);
                        }
                        
                        if(apiDocsContainer){
                            const content = data.apiDocumentation || '';
                            const sanitized = sanitizeContent(content);
                            // Store the original markdown content for copying
                            apiDocsContainer.setAttribute('data-markdown-content', sanitized);
                            try{
                                // Render markdown to HTML using marked (included in the page)
                                apiDocsContainer.innerHTML = marked.parse(sanitized);
                            }catch(e){
                                // Fallback to plain text if markdown parsing fails
                                apiDocsContainer.textContent = sanitized;
                            }
                            const placeholder = document.getElementById('apiDocsPlaceholder');
                            if(content && content.trim().length>0){
                                if(placeholder) placeholder.style.display = 'none';
                                apiDocsContainer.style.display = 'block';
                            } else {
                                if(placeholder) placeholder.style.display = '';
                                apiDocsContainer.style.display = '';
                            }
                        }
                        
                        console.log('[Generation] UI update complete');
                        
                        // Heuristic: detect likely truncated agent YAML and warn user
                        try{
                            const agentText = (data.agentDefinition || '').trim();
                            const suspicious = (agentText && (agentText.length < 250 || /instructions:\s*\|\-?\s*$/.test(agentText)));
                            if(suspicious){
                                showValidation('Warning: Agent definition appears incomplete or truncated. Consider regenerating to allow validate-and-retry to correct it.');
                            }
                        }catch(e){ /* truncation check failed silently */ }

                        // Show structured schema validation errors from server if present
                        if(data.validationErrors){
                            try{
                                const v = data.validationErrors;
                                const agentErrs = (v.agent && v.agent.length) ? v.agent : [];
                                const toolErrs = (v.tool && v.tool.length) ? v.tool : [];
                                if(agentErrs.length || toolErrs.length){
                                    let msgs = [];
                                    if(toolErrs.length) msgs.push('Tool validation: ' + toolErrs.map(e=> `${e.path}: ${e.message}`).join('; '));
                                    if(agentErrs.length) msgs.push('Agent validation: ' + agentErrs.map(e=> `${e.path}: ${e.message}`).join('; '));
                                    // Surface as a non-blocking validation message in the modal
                                    showValidation(msgs.join(' \n'));
                                    // Also show an alert so users notice
                                    try{ showAppAlert && showAppAlert({ title: 'Validation Warnings', message: msgs.join('\n') }); }catch(e){}
                                }
                            }catch(e){ /* validationErrors handling failed silently */ }
                        }

                        // Switch to step 2 and adjust controls
                        console.log('[Generation] Transitioning to step 2...');
                        const step1 = document.getElementById('toolStep1');
                        const step2 = document.getElementById('toolStep2');
                        if(step1 && step2){ 
                            step1.classList.remove('active'); 
                            step2.classList.add('active');
                            console.log('[Generation] Step transition complete');
                        } else {
                            console.error('[Generation] Could not find step elements:', { step1: !!step1, step2: !!step2 });
                        }
                        
                        // Hide Generate (Next) button, show Back button
                        const nextBtn = document.getElementById('toolModalNextBtn'); 
                        if(nextBtn) nextBtn.classList.add('hidden');
                        const backBtn = document.getElementById('toolModalBackBtn'); 
                        if(backBtn) backBtn.classList.remove('hidden');
                        
                        // Make YAML textareas editable so user can always edit
                        let t = document.getElementById('toolDefinitionYaml'); 
                        if(t) { t.readOnly = false; t.removeAttribute('readonly'); }
                        let a = document.getElementById('toolAgentDefinitionYaml'); 
                        if(a) { a.readOnly = false; a.removeAttribute('readonly'); }
                        
                        // Show Create Tool Agent button
                        const createBtn = document.getElementById('toolModalCreateBtn'); 
                        if(createBtn) createBtn.classList.remove('hidden');
                        
                        console.log('[Generation] All UI transitions complete');
                        
                    } catch (err) {
                        console.error('[Generation] Error:', err);
                        // Clean up SSE subscription on error
                        if (sseClient && subscriptionId) {
                            sseClient.unsubscribe(subscriptionId);
                            sseClient.disconnect();
                        }
                        showValidation('❌ Error: ' + err.message);
                        throw err;
                    } finally {
                        // Re-enable the generate button
                        generateBtn.disabled = false;
                    }

                    // Force CodeMirror refresh after step transition to ensure content displays
                    setTimeout(() => {
                        try {
                            const globalDiscovery = (typeof discoveryAgent !== 'undefined') ? discoveryAgent : (window.discoveryAgent || null);
                            if(globalDiscovery && globalDiscovery.toolAgentCreator){
                                const tac = globalDiscovery.toolAgentCreator;
                                if(tac.toolDefinitionCodeMirror) {
                                    tac.toolDefinitionCodeMirror.refresh();
                                }
                                if(tac.agentDefinitionCodeMirror) {
                                    tac.agentDefinitionCodeMirror.refresh();
                                }
                            }
                        } catch(e) {}
                    }, 300);
                    
                    showValidation('');
                }catch(err){
                    showValidation('Generation error: ' + err.message);
                }finally{
                    // Restore button state according to validation and name presence
                    updateGenerateButtonState();
                }
            });
            // Disable initially until validation and name are present
            generateBtn.disabled = true;
        }
        
        // Hook the Back button: discard generated content, return to step 1
        const backBtn = document.getElementById('toolModalBackBtn');
        if(backBtn){
            backBtn.addEventListener('click', ()=>{
                console.log('[Back] Returning to step 1, discarding generated content');
                
                // Clear generated content
                const toolTextarea = document.getElementById('toolDefinitionYaml');
                const agentTextarea = document.getElementById('toolAgentDefinitionYaml');
                const apiDocsContainer = document.getElementById('apiDocsContent');
                
                if(toolTextarea) toolTextarea.value = '';
                if(agentTextarea) agentTextarea.value = '';
                if(apiDocsContainer) {
                    apiDocsContainer.innerHTML = '';
                    apiDocsContainer.style.display = 'none';
                }
                
                // Clear from global ToolAgentCreator instance if present
                try{
                    const globalDiscovery = (typeof discoveryAgent !== 'undefined') ? discoveryAgent : (window.discoveryAgent || null);
                    if(globalDiscovery && globalDiscovery.toolAgentCreator){
                        const tac = globalDiscovery.toolAgentCreator;
                        tac.generatedDefinitions = { tooldef: '', agentdef: '', apidoc: '' };
                        if(tac.toolDefinitionCodeMirror) tac.toolDefinitionCodeMirror.setValue('');
                        if(tac.agentDefinitionCodeMirror) tac.agentDefinitionCodeMirror.setValue('');
                    }
                }catch(e){ console.warn('[Back] Could not clear global:', e); }
                
                // Switch back to step 1
                const step1 = document.getElementById('toolStep1');
                const step2 = document.getElementById('toolStep2');
                if(step1 && step2){ 
                    step2.classList.remove('active'); 
                    step1.classList.add('active');
                }
                
                // Show Generate button, hide Back and Create buttons
                const nextBtn = document.getElementById('toolModalNextBtn'); 
                if(nextBtn) nextBtn.classList.remove('hidden');
                if(backBtn) backBtn.classList.add('hidden');
                const createBtn = document.getElementById('toolModalCreateBtn'); 
                if(createBtn) createBtn.classList.add('hidden');
                
                // Clear any status messages
                showValidation('');
                
                console.log('[Back] Returned to step 1, uploads preserved');
            });
        }

        // Ensure cleanup when Create Tool Agent is clicked (successful creation path)
        const createBtnGlobal = document.getElementById('toolModalCreateBtn');
        if(createBtnGlobal){
            createBtnGlobal.addEventListener('click', ()=>{
                try{
                    if(sessionId){
                        // Fire-and-forget cleanup; backend will persist if creation needs files
                        fetch(`/api/tool-agent/delete-session/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }).catch(()=>{});
                        sessionId = null;
                    }
                }catch(e){}
            });
        }

        function updateValidation(){
            const names = Array.from(uploadsMap.values()).map(m=>m.originalName);
            const cats = names.map(n=> categorizeFilename(n));
            const hasDocker = cats.includes('Dockerfile');
            const hasDocs = cats.includes('Docs');
            const hasScripts = cats.includes('Script');
            if(!hasDocker) showValidation('Validation error: Please include a Dockerfile.');
            else if(!(hasDocs || hasScripts)) showValidation('Validation error: Include at least one API docs file or a scripts/source file.');
            else showValidation('');
            updateGenerateButtonState();
        }

        // Enable Generate button only when name is provided and upload validation passes
        function updateGenerateButtonState(){
            const generateBtn = $('toolModalNextBtn');
            if(!generateBtn) return;
            const name = $('toolAgentName')?.value?.trim() || '';
            const validationMsg = $('toolUploadValidation')?.textContent || '';
            const valid = name && (!validationMsg || !validationMsg.startsWith('Validation error'));
            generateBtn.disabled = !valid;
        }

        // Watch name input to enable/disable Generate
        const nameInput = $('toolAgentName');
        if(nameInput){
            nameInput.addEventListener('input', () => updateGenerateButtonState());
        }

        function validateForGeneration(){
            const msg = validationEl.textContent || '';
            if(msg && msg.startsWith('Validation error')){
                showValidation(msg);
                return false;
            }
            return true;
        }

        function showValidation(msg){ if(validationEl) validationEl.textContent = msg || ''; }

        function waitForUploadsToFinish(dzInstance){
            return new Promise((resolve, reject) => {
                const check = () => {
                    const filesStillUploading = dzInstance.files.filter(f => f.status === 'uploading' || f.status === 'queued' || f.status === Dropzone.ADDED);
                    // Dropzone statuses: 'queued','uploading','success','error'
                    const uploading = dzInstance.files.some(f => ['uploading','queued'].includes(f.status));
                    if(!uploading) return resolve();
                    setTimeout(check, 500);
                };
                check();
                // Timeout guard
                setTimeout(()=>{ resolve(); }, 20000);
            });
        }
    }

    // Note: Back button navigation is now handled by the ToolAgentCreator class in agent.js
    // This ensures proper step management and avoids duplicate event listeners.
    // If the ToolAgentCreator is not available, the back button will use its default handler.

    if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
