// Entry Agent Diagram Renderer
// Lazy-load Mermaid and render a workflow diagram based on current YAML

(function(){
  const state = {
    mermaidLoaded: false,
    mermaidLoading: false,
    lastMermaidText: '',
    debouncer: null,
  controlsBound: false,
  liveUpdatesBound: false,
  };

  async function ensureMermaidLoaded() {
    if (state.mermaidLoaded) return;
    if (state.mermaidLoading) {
      // wait until available
      await new Promise(res => {
        const check = () => {
          if (state.mermaidLoaded) return res();
          setTimeout(check, 50);
        };
        check();
      });
      return;
    }
    state.mermaidLoading = true;
    await new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
      script.crossOrigin = 'anonymous';
      script.onload = () => {
        try {
          // Prefer neutral theme; Mermaid will adapt to CSS variables if configured
          window.mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral' });
          state.mermaidLoaded = true;
          resolve();
        } catch (e) {
          reject(e);
        }
      };
      script.onerror = (e) => reject(new Error('Failed to load Mermaid'));
      document.head.appendChild(script);
    });
  }

  // (removed) sanitizeLabel: no longer needed in LLM-only flow

  function getActiveWorkflowYaml() {
    try {
      // Prefer discovery_client helper if present
      if (window.discoveryClient && typeof window.discoveryClient.tryGetInlineWorkflowYaml === 'function') {
        const inline = window.discoveryClient.tryGetInlineWorkflowYaml();
        if (inline && inline.trim()) {
          return inline;
        }
      }
      
      // Try multiple ways to access the agent object
      const agent = window.agent || window.discoveryAgent || (typeof discoveryAgent !== 'undefined' ? discoveryAgent : null);
      
      if (agent) {
        const cm = agent.entryWorkflowCodeMirror || agent.agentConfigCodeMirror;
        if (cm && typeof cm.getValue === 'function') {
          const val = cm.getValue();
          if (val && val.trim()) return val;
        } else {
          console.debug('[Diagram] No CodeMirror editor found or getValue not available');
          console.debug('[Diagram] agent.entryWorkflowCodeMirror:', agent.entryWorkflowCodeMirror);
        }
      } else {
        console.debug('[Diagram] No agent object found');
        console.debug('[Diagram] window.agent:', window.agent);
        console.debug('[Diagram] window.discoveryAgent:', window.discoveryAgent);
        console.debug('[Diagram] global discoveryAgent:', typeof discoveryAgent !== 'undefined' ? discoveryAgent : 'undefined');
      }
      
      console.debug('[Diagram] Checking textarea fallback...');
      const ta = document.getElementById('entryWorkflowEditor') || document.getElementById('agentConfigEditor');
      if (ta && ta.value && ta.value.trim()) {
        console.debug('[Diagram] Got YAML from textarea:', ta.value.length, 'characters');
        return ta.value;
      } else {
        console.debug('[Diagram] No textarea found or empty');
      }
      
      console.debug('[Diagram] No YAML found anywhere');
      return '';
    } catch (e) {
      console.error('[Diagram] Error in getActiveWorkflowYaml:', e);
      return '';
    }
  }

  // Use LLM to generate Mermaid diagram from YAML workflow
  // previousError: optional string containing the validation/render error from a prior attempt
  async function generateMermaidFromYaml(yamlText, previousError = null) {
    try {
      console.debug('[Diagram] Generating Mermaid diagram using LLM...');
      if (previousError) {
        console.debug('[Diagram] Including previous error feedback for retry:', previousError);
      }

      // Check if we have access to an LLM API (adjust this based on your setup)
      if (window.fetch) {
        // Get current workflow name for auto-saving the diagram
        let workflowName = null;
        try {
          if (window.agent && window.agent.currentEntryAgentData && window.agent.currentEntryAgentData.name) {
            workflowName = window.agent.currentEntryAgentData.name;
            console.debug('[Diagram] Found workflow name for auto-save:', workflowName);
          }
        } catch (e) {
          console.debug('[Diagram] Could not determine workflow name:', e);
        }

        // Call our server endpoint with YAML and workflow name; server will compose the strict prompt
        // Include previousError if we're retrying after a validation failure
        const body = { 
          yaml: yamlText,
          workflowName: workflowName
        };
        if (previousError) {
          body.previousError = previousError;
        }
        console.debug('[Diagram] Calling /api/generate-diagram...', previousError ? '(with error feedback)' : '(initial attempt)');
        const response = await fetch('/api/generate-diagram', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(body)
        });
        
        if (response.ok) {
          const result = await response.json();
          
          // Show auto-save notification if diagram was saved
          if (result.savedTo && workflowName) {
            const filename = result.savedTo.split(/[\\\/]/).pop(); // Extract filename from path
            console.log(`[Diagram] Auto-saved diagram as: ${filename}`);
            
            // Show a toast notification if available
            if (typeof showToast === 'function') {
              showToast(`Diagram auto-saved as ${filename}`, 'success');
            } else if (window.showToast) {
              window.showToast(`Diagram auto-saved as ${filename}`, 'success');
            }
          }
          
          return result.diagram || result.text || '';
        } else {
          throw new Error(`LLM endpoint returned ${response.status}: ${response.statusText}`);
        }
      }
      throw new Error('Fetch API not available in this environment.');
      
    } catch (error) {
      console.error('[Diagram] Error generating Mermaid diagram:', error);
      throw error;
    }
  }

  // (removed) extractGraphFromYaml: replaced by LLM-only generation

  // (removed) graphToMermaid and sanitizeId: replaced by LLM-only generation

  // Helper to remove Mermaid's temporary render div (prevents stray element at bottom-left)
  function cleanupMermaidTemp(id = 'entryAgentDiagram') {
    try {
      const temp = document.getElementById('d' + id);
      if (temp && temp.parentNode) temp.parentNode.removeChild(temp);
    } catch {}
  }

  // Display a placeholder diagram showing work in progress
  async function showPlaceholderDiagram(container) {
    const placeholderMermaid = `%%{init: {"securityLevel": "strict"}}%%
sequenceDiagram
    autonumber
    participant User
    participant System as "Diagram Generator"
    participant LLM as "Copilot LLM"
    participant Validator as "Mermaid Validator"
    
    User->>System: Generate Diagram
    activate System
    note over System: Processing YAML workflow...
    
    loop Up to 3 attempts
        System->>LLM: Generate Mermaid
        activate LLM
        note over LLM: 🤖 Analyzing workflow<br/>and creating diagram
        LLM->>System: Mermaid Code
        deactivate LLM
        
        System->>Validator: Validate Syntax
        activate Validator
        Validator->>System: Validation Result
        deactivate Validator
        
        alt Valid Diagram
            note over System: ✅ Valid - Rendering final diagram...
        else Invalid Diagram  
            note over System: ❌ Error - Providing feedback<br/>for retry...
        end
    end
    
    System->>User: Final Diagram
    deactivate System
    
    note over User, Validator: 🔄 Currently generating your workflow diagram...`;

    try {
      await ensureMermaidLoaded();
      const { svg } = await window.mermaid.render('placeholderDiagram', placeholderMermaid);
      cleanupMermaidTemp('placeholderDiagram');
      container.innerHTML = svg;
      
      // Add a subtle visual indicator that this is a placeholder
      const svgElement = container.querySelector('svg');
      if (svgElement) {
        svgElement.style.opacity = '0.7';
        svgElement.style.filter = 'blur(0.5px)';
      }
      
    } catch (e) {
      console.warn('[Diagram] Failed to render placeholder:', e);
      // Fallback to simple loading graphic
      container.innerHTML = `
        <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 300px; color: #666;">
          <div style="font-size: 48px; margin-bottom: 16px;">🤖</div>
          <div style="font-size: 16px; font-weight: 500;">Copilot Generating Diagram</div>
          <div style="font-size: 14px; opacity: 0.8; margin-top: 8px;">Analyzing → Generating → Validating → Retrying if needed</div>
        </div>
      `;
    }
  }

  // Attempt to validate Mermaid without injecting into the UI. Fallback uses render but cleans up temp element.
  async function validateMermaidText(text) {
    // Prefer mermaid.parse if available (no DOM side-effects)
    if (window.mermaid && typeof window.mermaid.parse === 'function') {
      try {
        await window.mermaid.parse(text);
        return { ok: true };
      } catch (e) {
        return { ok: false, error: e?.message || String(e) };
      }
    }
    // Fallback: try a dry render and immediately discard
    try {
      await window.mermaid.render('entryAgentDiagram', text);
      cleanupMermaidTemp('entryAgentDiagram');
      return { ok: true };
    } catch (e) {
      const msg = e?.str || e?.message || String(e);
      cleanupMermaidTemp('entryAgentDiagram');
      return { ok: false, error: msg };
    }
  }

  async function renderDiagram() {
    console.debug('[Diagram] renderDiagram invoked');
    const msg = document.getElementById('diagramMessages');
    const container = document.getElementById('diagramContainer');
    if (!container || !msg) {
      console.error('[Diagram] Missing container or message elements');
      return;
    }
    try {

      // Show loading message while we wait for the LLM endpoint to return the mermaid document
      msg.textContent = 'Copilot generating mermaid diagram...';
      
      // Show placeholder diagram while generating
      await showPlaceholderDiagram(container);
      cleanupMermaidTemp('entryAgentDiagram');

      let yaml = getActiveWorkflowYaml();
      console.debug('[Diagram] Got YAML from editor:', yaml ? `${yaml.length} characters` : 'null');
      
      if (!yaml) {
        // Fallback: try fetching from server for the current agent
        console.debug('[Diagram] No YAML from editor, trying server...');
        try {
          const agent = window.agent || window.discoveryAgent || (typeof discoveryAgent !== 'undefined' ? discoveryAgent : null);
          const currentAgent = agent?.findCurrentAgent?.();
          const agentName = currentAgent?.name || agent?.agentName;
          console.debug('[Diagram] Current agent name:', agentName);
          if (agentName) {
            const resp = await fetch(`/api/agents/${agentName}/entry-component/workflow`);
            console.debug('[Diagram] Server response status:', resp.status);
            if (resp.ok) {
              const data = await resp.json();
              console.debug('[Diagram] Server response data:', data);
              if (data?.success && data?.content) {
                yaml = data.content;
                console.debug('[Diagram] Got YAML from server:', `${yaml.length} characters`);
              }
            }
          }
        } catch (e) { 
          console.error('[Diagram] Error fetching from server:', e);
        }
      }
      
      if (!yaml) {
        // Check if we're on a tool agent vs entry agent
        const agent = window.agent || window.discoveryAgent || (typeof discoveryAgent !== 'undefined' ? discoveryAgent : null);
        const currentAgent = agent?.findCurrentAgent?.();
        const agentName = currentAgent?.name || agent?.agentName;
        const isEntryAgent = agent?.availableAgents?.entry_agents?.some(ea => ea.name === agentName);
        
        let errorMsg;
        if (!isEntryAgent) {
          errorMsg = `Current agent "${agentName}" is not an Entry Agent. Switch to an Entry Agent (like QuantumChemistry, PDBSearch, or Surfactant20) to see workflow diagrams.`;
        } else {
          errorMsg = 'No workflow YAML found. Open Workflow tab or paste YAML.';
        }
        
        msg.textContent = errorMsg;
        console.warn('[Diagram]', errorMsg);
        state.lastMermaidText = '';
        return;
      }

      console.debug('[Diagram] Loading Mermaid...');
      await ensureMermaidLoaded();

      // Up to 3 attempts: first is normal, subsequent attempts include feedback about the prior parse/render error
      let attempt = 1;
      const maxAttempts = 3;
      let finalMermaidText = '';
      let rendered = false;
      let lastError = null; // Track the last validation/render error for feedback to LLM

      while (attempt <= maxAttempts && !rendered) {
        try {
          console.debug(`[Diagram] LLM generation attempt ${attempt}/${maxAttempts}${attempt === 1 ? ' (initial)' : ''}`);
          // Keep the first call message generic per requirement
          if (attempt > 1) {
            msg.textContent = 'Received an invalid diagram; asking Copilot to fix and retry...';
          }

          // Pass the previous error to help the LLM avoid repeating the same mistake
          const mermaidText = await generateMermaidFromYaml(yaml, lastError);

          if (!mermaidText || !mermaidText.trim()) {
            throw new Error('LLM returned empty Mermaid diagram');
          }

          // Ensure security directive if missing
          finalMermaidText = mermaidText.startsWith('%%{init:')
            ? mermaidText
            : '%%{init: {"securityLevel": "strict"}}%%\n' + mermaidText;

          state.lastMermaidText = finalMermaidText;

          // Show raw Mermaid briefly for debugging context
          msg.innerHTML = `<pre style="font-size: 10px; background: #f5f5f5; padding: 8px; border-radius: 4px; margin: 4px 0; max-height: 100px; overflow-y: auto;">${finalMermaidText}</pre>Rendering diagram...`;

          // Validate before actual render to avoid stray DOM artifacts
          const validation = await validateMermaidText(finalMermaidText);
          if (!validation.ok) {
            throw new Error(validation.error || 'Unknown Mermaid validation error');
          }

          // Render to SVG and place strictly inside our container
          console.debug('[Diagram] Rendering Mermaid to SVG...');
          const { svg } = await window.mermaid.render('entryAgentDiagram', finalMermaidText);
          cleanupMermaidTemp('entryAgentDiagram');
          console.debug('[Diagram] Mermaid render successful, SVG length:', svg.length);
          
          // Replace placeholder with final diagram
          container.innerHTML = svg;
          
          // Remove placeholder styling if any
          const svgElement = container.querySelector('svg');
          if (svgElement) {
            svgElement.style.opacity = '';
            svgElement.style.filter = '';
          }
          
          msg.textContent = '';
          rendered = true;

        } catch (attemptErr) {
          console.warn('[Diagram] Attempt failed:', attemptErr);
          cleanupMermaidTemp('entryAgentDiagram');
          // Capture the error message to pass as feedback on next attempt
          lastError = attemptErr?.message || String(attemptErr);
          if (attempt >= maxAttempts) {
            throw attemptErr; // Bubble up to outer catch after final attempt
          }
          attempt += 1;
          // Loop to retry with feedback
          continue;
        }
      }
      
    } catch (e) {
      const errorMsg = 'Diagram error: ' + (e?.message || e);
      if (msg) msg.textContent = errorMsg + ' Showing raw Mermaid below.';
      console.error('[Diagram] Render error:', e);
      console.error('[Diagram] Error stack:', e.stack);
      // Ensure stray temp nodes are cleaned up on failure
      cleanupMermaidTemp('entryAgentDiagram');
      // Display the raw Mermaid text returned (if any) to help the user debug
      try {
        container.innerHTML = '';
        const pre = document.createElement('pre');
        pre.style.fontSize = '11px';
        pre.style.background = '#f5f5f5';
        pre.style.padding = '8px';
        pre.style.borderRadius = '4px';
        pre.style.whiteSpace = 'pre-wrap';
        pre.style.wordBreak = 'break-word';
        pre.textContent = state.lastMermaidText || '(No Mermaid text returned)';
        container.appendChild(pre);
      } catch (noop) {}
    }
  }

  function setupControls() {
  if (state.controlsBound) return;
  console.debug('[Diagram] setupControls');
  const refresh = document.getElementById('diagramRefreshBtn');
  const copy = document.getElementById('diagramCopyBtn');
  const svgBtn = document.getElementById('diagramExportSvgBtn');
  const expandBtn = document.getElementById('diagramExpandBtn');
  const container = document.getElementById('diagramContainer');

    const expandDiagram = async () => {
      const svgEl = document.getElementById('diagramContainer')?.querySelector('svg');
      if (!svgEl) return;
      try {
        // Serialize current SVG
        const xml = new XMLSerializer().serializeToString(svgEl);

        // Ensure extension system is available
        if (typeof extensionManager !== 'undefined' && typeof extensionManager.showFullView === 'function') {
          // Create a pseudo filename so image extension handles it as SVG
          const pseudoFilename = 'entry-agent-diagram.svg';
          await extensionManager.showFullView(pseudoFilename, xml);
        } else if (window.extensionManager && typeof window.extensionManager.showFullView === 'function') {
          const pseudoFilename = 'entry-agent-diagram.svg';
          await window.extensionManager.showFullView(pseudoFilename, xml);
        } else if (window.discoveryAgent && typeof window.discoveryAgent.showFileFullView === 'function') {
          // Fallback to discoveryAgent helper if available
          await window.discoveryAgent.showFileFullView('entry-agent-diagram.svg');
        } else {
          // If no modal available, open in new tab as a minimal fallback
          const win = window.open();
          if (win) {
            win.document.write(`<html><head><title>Workflow Diagram</title></head><body style="margin:0">${xml}</body></html>`);
            win.document.close();
          }
        }
      } catch (err) {
        console.error('[Diagram] Failed to expand diagram:', err);
      }
    };

    refresh?.addEventListener('click', () => renderDiagram());
    copy?.addEventListener('click', async () => {
      if (!state.lastMermaidText) return;
      try {
        await navigator.clipboard.writeText(state.lastMermaidText);
        const msg = document.getElementById('diagramMessages');
        if (msg) msg.textContent = 'Mermaid copied to clipboard.';
        setTimeout(() => { if (msg && msg.textContent.startsWith('Mermaid')) msg.textContent = ''; }, 1500);
      } catch {}
    });

    svgBtn?.addEventListener('click', () => {
      if (!state.lastMermaidText) return;
      const blob = new Blob([document.getElementById('diagramContainer')?.innerHTML || ''], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      // Use the current agent name for the filename
      let filename = 'entry-agent-diagram.svg';
      try {
        const agentName = window.agent?.currentEntryAgentData?.name || 
                          window.agent?.findCurrentAgent?.()?.name ||
                          window.discoveryAgent?.currentEntryAgentData?.name;
        if (agentName) {
          filename = `${agentName.toLowerCase()}-diagram.svg`;
        }
      } catch (e) {
        console.debug('[Diagram] Could not get agent name for filename:', e);
      }
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    });

    // Expand to full view using the extensions modal and image viewer
    expandBtn?.addEventListener('click', expandDiagram);

    // Also expand when clicking anywhere on the diagram container (if an SVG is present)
    container?.addEventListener('click', () => {
      if (container.querySelector('svg')) {
        expandDiagram();
      }
    });
  state.controlsBound = true;
  }

  function setupLiveUpdates() {
  if (state.liveUpdatesBound) return;
  console.debug('[Diagram] setupLiveUpdates (disabled auto-render)');
    // Auto-render on editor changes intentionally disabled per request.
    // Keeping hook in case we want to display a subtle hint when YAML changes.
    const maybeAttach = (cm) => {
      if (!cm || typeof cm.on !== 'function') return;
      cm.on('change', () => {
        // No auto rendering; could set a flag or UI hint here if desired.
        // Example: document.getElementById('diagramMessages').textContent = 'YAML changed — click Generate to update diagram.';
      });
    };
    maybeAttach(window.agent?.entryWorkflowCodeMirror);
    maybeAttach(window.agent?.agentConfigCodeMirror);
  state.liveUpdatesBound = true;
  }

  function onTabShown(tabName) {
    console.debug('[Diagram] onTabShown', tabName);
    if (tabName !== 'entry-workflow') return;
    
    // Initialize controls and render
    setupControls();
    setupLiveUpdates();
    
    // Check if there's preloaded diagram content to display
    if (window.agent && window.agent._preloadedDiagramContent) {
      console.log('[Diagram] Found preloaded diagram content, displaying...');
      console.log('[Diagram] Content length:', window.agent._preloadedDiagramContent.length);
      
      // If Mermaid is already loaded, display immediately
      if (window.mermaid) {
        setDiagramContent(window.agent._preloadedDiagramContent);
        window.agent._preloadedDiagramContent = null; // Clear after use
      } else {
        console.log('[Diagram] Mermaid not loaded yet, will display after loading...');
        // Wait for Mermaid to load, then display
        ensureMermaidLoaded().then(() => {
          if (window.agent && window.agent._preloadedDiagramContent) {
            setDiagramContent(window.agent._preloadedDiagramContent);
            window.agent._preloadedDiagramContent = null; // Clear after use
          }
        }).catch(error => {
          console.error('[Diagram] Failed to load Mermaid for auto-display:', error);
        });
      }
    } else {
      console.log('[Diagram] No preloaded diagram content found');
      console.log('[Diagram] window.agent exists:', !!window.agent);
      if (window.agent) {
        console.log('[Diagram] _preloadedDiagramContent exists:', !!window.agent._preloadedDiagramContent);
      }
    }
    // Do not auto-generate; user must click Generate.
  }

  // Set diagram content directly (used for auto-loading saved diagrams)
  // This is now async to properly wait for Mermaid to load
  async function setDiagramContent(mermaidContent) {
    try {
      console.debug('[Diagram] Setting diagram content directly');
      console.debug('[Diagram] Content length:', mermaidContent?.length);
      console.debug('[Diagram] First 100 chars:', mermaidContent?.substring(0, 100));
      
      state.currentDiagram = mermaidContent;
      // Keep lastMermaidText in sync so controls (Copy/Export) work for auto-loaded diagrams
      try { state.lastMermaidText = mermaidContent; } catch(e) { console.debug('[Diagram] Could not set lastMermaidText:', e); }
      
      // Update the textarea if it exists
      const textarea = document.getElementById('generatedDiagramSource');
      if (textarea) {
        textarea.value = mermaidContent;
        console.debug('[Diagram] Updated textarea with content');
      } else {
        console.debug('[Diagram] Textarea not found: generatedDiagramSource');
      }
      
      // Render the diagram immediately - use the correct container ID
      const container = document.getElementById('diagramContainer');
      console.debug('[Diagram] Container found:', !!container);
      console.debug('[Diagram] Mermaid available:', !!window.mermaid);
      
      if (container && mermaidContent && mermaidContent.trim()) {
        // Show loading message while we wait for Mermaid to load
        if (!window.mermaid) {
          console.log('[Diagram] Mermaid library not loaded yet, loading now...');
          container.innerHTML = '<div class="info" style="padding: 20px; text-align: center;"><span class="loading-spinner" style="display: inline-block; margin-right: 8px;"></span>Loading diagram renderer...</div>';
        }
        
        // Wait for Mermaid to be loaded
        await ensureMermaidLoaded();
        console.debug('[Diagram] Mermaid library loaded, proceeding with render');
        
        console.debug('[Diagram] Rendering diagram with window.mermaid.render...');
        state.isRendering = true;
        
        // Clear any existing messages
        const messagesDiv = document.getElementById('diagramMessages');
        if (messagesDiv) {
          messagesDiv.textContent = '';
          messagesDiv.className = '';
        }
        
        try {
          const { svg } = await window.mermaid.render('autoLoadedDiagram', mermaidContent);
          container.innerHTML = svg;
          console.debug('[Diagram] Successfully rendered auto-loaded diagram');
          // Ensure the container enforces scrolling when SVG is larger than available area
          try { container.style.overflow = 'auto'; container.scrollTop = 0; } catch(e){}
          // Clean up temp element
          cleanupMermaidTemp('autoLoadedDiagram');
        } catch (renderError) {
          console.error('[Diagram] Error rendering auto-loaded diagram:', renderError);
          container.innerHTML = '<div class="error" style="padding: 20px; color: #d13438;">Error rendering diagram: ' + (renderError.message || renderError) + '</div>';
          cleanupMermaidTemp('autoLoadedDiagram');
        } finally {
          state.isRendering = false;
        }
      } else {
        console.debug('[Diagram] Cannot render - container:', !!container, 'content:', !!mermaidContent?.trim());
      }
    } catch (error) {
      console.error('[Diagram] Error setting diagram content:', error);
    }
  }

  // Expose small API for the main app
  window.entryDiagram = {
    onTabShown,
    render: renderDiagram,
    setDiagramContent: setDiagramContent,
    // Debug functions
    debug: {
      getYaml: getActiveWorkflowYaml,
      renderDiagram: renderDiagram,
      state: state
    }
  };

  // Defensive: initialize when DOM is ready in case the panel is already active
  document.addEventListener('DOMContentLoaded', () => {
    try {
      const active = document.querySelector('#entry-workflow-panel.tab-panel.active');
      if (active) {
        console.debug('[Diagram] DOMContentLoaded: diagram panel already active, initializing');
        setupControls();
  setupLiveUpdates();
  // No auto render on load.
      }
    } catch (_) {}
  });
})();
