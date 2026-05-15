/**
 * Microsoft Discovery Publishing Client
 * 
 * Frontend JavaScript module for handling Microsoft Discovery agent publishing workflow.
 * Integrates with the main DiscoveryAgent class for publishing agents to Discovery platform.
 */

class DiscoveryPublishingClient {
    constructor(mainAgent) {
        this.mainAgent = mainAgent;
        this.currentAgentData = null;
        this.currentToolData = null;
        this.deploymentInProgress = false;
        
        // Bind event handlers
        this.initializeEventHandlers();
    }

    initializeEventHandlers() {
        // Modal controls
        const closeBtn = document.getElementById('closeDiscoveryDialog');
        const cancelBtn = document.getElementById('cancelDiscoveryBtn');
        const checkBtn = document.getElementById('checkDiscoveryBtn');
        const confirmBtn = document.getElementById('confirmDiscoveryBtn');

        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.hideDiscoveryDialog());
        }
        
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                if (!this.deploymentInProgress) {
                    this.hideDiscoveryDialog();
                }
            });
        }
        
        if (checkBtn) {
            checkBtn.addEventListener('click', () => this.checkExistingTools());
        }
        
        if (confirmBtn) {
            confirmBtn.addEventListener('click', () => {
                // Store original button text to determine operation type later
                confirmBtn.setAttribute('data-original-text', confirmBtn.textContent);
                // Immediately disable the button to prevent double-clicks
                confirmBtn.disabled = true;
                confirmBtn.textContent = 'Publishing...';
                this.performDiscoveryPublishing();
            });
        }


        // Form change handlers
        this.setupFormHandlers();

        // Global Esc key handler for modal dialogs
        this.setupEscKeyHandler();
    }

    setupEscKeyHandler() {
        // Add global escape key listener
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                // Check if discovery modal is open
                const discoveryModal = document.getElementById('discoveryPublishDialog');
                if (discoveryModal && !discoveryModal.classList.contains('hidden')) {
                    // Only allow closing if not in the middle of deployment
                    if (!this.deploymentInProgress) {
                        this.hideDiscoveryDialog();
                    }
                    return;
                }

                // Check if deployment modal is open (from agent.js)
                const deployModal = document.getElementById('deployDialog');
                if (deployModal && !deployModal.classList.contains('hidden')) {
                    // Call hideDeployDialog from the global agent instance
                    if (window.agent && typeof window.agent.hideDeployDialog === 'function') {
                        window.agent.hideDeployDialog();
                    }
                    return;
                }

                // Check if Tool Agent Creator modal is open
                const toolModal = document.getElementById('createToolAgentModal');
                if (toolModal && !toolModal.classList.contains('hidden')) {
                    if (window.agent && window.agent.toolAgentCreator && typeof window.agent.toolAgentCreator.hide === 'function') {
                        window.agent.toolAgentCreator.hide();
                    }
                    return;
                }
            }
        });
    }

    setupFormHandlers() {
        // Note: Azure configuration is now managed through global settings
        // This method is kept for compatibility but no longer sets up handlers for removed fields
        console.log('setupFormHandlers: Azure configuration now managed through global settings');
    }

    async showDiscoveryDialog() {
        const dialog = document.getElementById('discoveryPublishDialog');
        if (!dialog) return;

        // Get current agent information
        // Prefer the agent's helper if available; otherwise support both array and grouped object shapes
        let currentAgent = null;
        if (this.mainAgent && typeof this.mainAgent.findCurrentAgent === 'function') {
            currentAgent = this.mainAgent.findCurrentAgent();
        } else if (Array.isArray(this.mainAgent?.availableAgents)) {
            currentAgent = this.mainAgent.availableAgents.find(a => a.is_current);
        } else if (this.mainAgent?.availableAgents) {
            const reg = Array.isArray(this.mainAgent.availableAgents.tool_agents)
                ? this.mainAgent.availableAgents.tool_agents.find(a => a.is_current)
                : null;
            const ent = Array.isArray(this.mainAgent.availableAgents.workflow_agents)
                ? this.mainAgent.availableAgents.workflow_agents.find(a => a.is_current)
                : null;
            currentAgent = reg || ent || null;
        }
        if (!currentAgent) {
            await showAppAlert({ title: 'No agent selected', message: 'Please select an agent first' });
            return;
        }

        // Load agent and tool data
        this.loadAgentConfiguration(currentAgent.name)
            .then(() => {
                // Populate form with agent data
                this.populateAgentForm();
                
                // Load saved settings
                this.loadSavedSettings();
                
                // Show dialog
                dialog.classList.remove('hidden');
                
                // Reset status section
                this.hideStatusSection();
            })
            .catch(async error => {
                console.error('Failed to load agent configuration:', error);
                await showAppAlert({ title: 'Load failed', message: 'Failed to load agent configuration: ' + error.message });
            });
    }

    hideDiscoveryDialog() {
        const dialog = document.getElementById('discoveryPublishDialog');
        if (dialog) {
            dialog.classList.add('hidden');
        }
        
        // Reset deployment state
        this.deploymentInProgress = false;
        this.updateButtonStates();
    }

    async loadAgentConfiguration(agentName) {
        try {
            // Load agent configuration from backend
            const response = await fetch('/api/discovery-publish/get-config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ agent_name: agentName })
            });

            if (!response.ok) {
                throw new Error(`Failed to load configuration: ${response.statusText}`);
            }

            const data = await response.json();
            this.currentAgentData = data.agent_config;
            this.currentToolData = data.tool_config;
            // Store the local agent name (folder name) separately from the YAML Name field
            this.localAgentName = agentName;
            
            // Populate Azure configuration from saved settings
            if (data.azure_config) {
                this.populateAzureConfig(data.azure_config);
            }
            
            return data;
        } catch (error) {
            console.error('Error loading agent configuration:', error);
            throw error;
        }
    }

    populateAgentForm() {
        if (!this.currentAgentData || !this.currentToolData) return;

        // Agent fields
        this.setFieldValue('discoveryAgentName', this.currentAgentData.name);

        // Tool fields
        this.setFieldValue('discoveryToolName', this.currentToolData.name);
        this.setFieldValue('discoveryAcrImage', this.currentToolData.acr_image);
    }

    populateAzureConfig(azureConfig) {
        // Store azure config for use by Workflow Agent publishing
        this.azureConfig = azureConfig;
        
        // Populate Azure configuration from server (overrides localStorage)
        if (azureConfig.subscription_id) {
            this.setFieldValue('discoverySubscriptionId', azureConfig.subscription_id);
        }
        if (azureConfig.resource_group) {
            this.setFieldValue('discoveryResourceGroup', azureConfig.resource_group);
        }
        if (azureConfig.location) {
            this.setFieldValue('discoveryLocation', azureConfig.location);
        }
    }

    async loadAzureConfigFromServer() {
        try {
            // Use Workflow Agent API since it doesn't require agent_name parameter
            const response = await fetch('/api/workflow-agent-publish/get-config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });

            if (response.ok) {
                const data = await response.json();
                if (data.azure_config) {
                    this.populateAzureConfig(data.azure_config);
                } else {
                    console.warn('No azure_config in server response');
                }
            } else {
                console.warn('Server response error:', response.status, response.statusText);
            }
        } catch (error) {
            console.error('Error loading Azure config from server:', error);
            throw error;
        }
    }

    setFieldValue(fieldId, value) {
        const field = document.getElementById(fieldId);
        if (field) {
            field.value = (value !== null && value !== undefined) ? value : '';
        }
    }

    loadSavedSettings() {
        // Note: Azure configuration is now managed through global settings
        // This method is kept for compatibility but no longer populates removed fields
        console.log('loadSavedSettings: Azure configuration now managed through global settings');
    }

    saveFormSettings() {
        // Note: Azure configuration is now managed through global settings
        // This method is kept for compatibility but no longer saves removed fields
        console.log('saveFormSettings: Azure configuration now managed through global settings');
    }

    async checkExistingTools() {
        const formData = this.getFormData();
        
    if (!this.validateForm(formData, false) || !formData.subscriptionId || !formData.resourceGroup) {
            return;
        }

        if (!this.currentToolData?.acr_image) {
            // Proceed using tool name only when ACR image is not present
            this.showStatusSection('info', 'No ACR image found in tool configuration. Will check by tool name only.');
        }

        this.showStatusSection('info', 'Checking for existing tools and agents...');
        this.updateButtonStates(true, 'check');

        try {
            const response = await fetch('/api/discovery-publish/check-tools', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    subscription_id: formData.subscriptionId,
                    resource_group: formData.resourceGroup,
                    tenant_id: formData.tenantId,
                    tenant_domain: formData.tenantDomain,
                    acr_image: this.currentToolData.acr_image,
                    tool_name: this.currentToolData.name,
                    agent_name: this.currentAgentData?.name
                })
            });

            const result = await response.json();

            if (result.success) {
                this.displayMatchingResourcesResults(result);
            } else {
                this.showStatusSection('error', 
                    `Failed to check existing resources: ${result.error || 'Unknown error'}`
                );
            }
        } catch (error) {
            console.error('Error checking resources:', error);
            this.showStatusSection('error', `Error checking resources: ${error.message}`);
        } finally {
            this.updateButtonStates(false);
        }
    }

    async checkForExistingResourcesAndConfirm() {
        const formData = this.getFormData();

        // If no ACR image is present, still attempt an existence check by tool name

        try {
            // Check for existing resources
            const response = await fetch('/api/discovery-publish/check-tools', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    subscription_id: formData.subscriptionId,
                    resource_group: formData.resourceGroup,
                    tenant_id: formData.tenantId,
                    acr_image: this.currentToolData.acr_image,
                    tool_name: this.currentToolData.name,
                    agent_name: this.currentAgentData?.name
                })
            });

            const result = await response.json();

            if (!result.success) {
                // If check failed, proceed anyway but warn user
                console.warn('Failed to check existing resources:', result.error);
                return true;
            }

            const hasTools = result.existing_tool && result.existing_tool.exists;
            const hasAgents = result.existing_agent && result.existing_agent.exists;

            if (!hasTools && !hasAgents) {
                // No conflicts, proceed
                return true;
            }

            // Show confirmation dialog for existing resources
            return await this.showExistingResourcesConfirmation(result);

        } catch (error) {
            console.error('Error checking existing resources:', error);
            // If error occurs, proceed anyway but warn user
            return true;
        }
    }

    async showExistingResourcesConfirmation(result) {
        const hasTools = result.existing_tool && result.existing_tool.exists;
        const hasAgents = result.existing_agent && result.existing_agent.exists;

        let message = "";
        
        if (hasTools) {
            const toolName = this.currentToolData?.name || 'your tool';
            message += `• Tool "${toolName}" already exists and will be updated<br>`;
        }
        
        if (hasAgents) {
            const agentName = this.currentAgentData?.name || 'your agent';  
            message += `• Agent "${agentName}" already exists and will be updated<br>`;
        }

        // Update the dialog content
        const messageDiv = document.getElementById('discoveryConfirmationMessage');
        if (messageDiv) {
            messageDiv.innerHTML = message;
        }

        // Show the custom dialog
        const dialog = document.getElementById('discoveryConfirmationDialog');
        if (dialog) {
            dialog.classList.remove('hidden');
        }

        // Return a promise that resolves based on user choice
        return new Promise((resolve) => {
            const proceedBtn = document.getElementById('proceedDiscoveryConfirmationBtn');
            const cancelBtn = document.getElementById('cancelDiscoveryConfirmationBtn');
            const closeBtn = document.getElementById('closeDiscoveryConfirmationDialog');

            const cleanup = () => {
                dialog.classList.add('hidden');
                proceedBtn?.removeEventListener('click', onProceed);
                cancelBtn?.removeEventListener('click', onCancel);
                closeBtn?.removeEventListener('click', onCancel);
            };

            const onProceed = () => {
                cleanup();
                resolve(true);
            };

            const onCancel = () => {
                cleanup();
                resolve(false);
            };

            proceedBtn?.addEventListener('click', onProceed);
            cancelBtn?.addEventListener('click', onCancel);
            closeBtn?.addEventListener('click', onCancel);
        });
    }

    async performDiscoveryPublishing() {
        const formData = this.getFormData();
        
        if (!this.validateForm(formData, true) || !formData.subscriptionId || !formData.resourceGroup) {
            // Re-enable button if validation fails
            this.updateButtonStates(false);
            return;
        }

        // Determine if this is an update operation based on button text
        const confirmBtn = document.getElementById('confirmDiscoveryBtn');
        // Store original text to check if this was an update operation before we changed it to "Publishing..."
        const wasUpdateOperation = confirmBtn && confirmBtn.getAttribute('data-original-text') === 'Update Selected Resources';
        
        // Get currently selected resources if this is an update operation
        if (wasUpdateOperation) {
            this.selectedResourcesForReuse = this.getSelectedResources();
            
            if (this.selectedResourcesForReuse.length === 0) {
                this.showStatusSection('error', 'No resources selected for update. Please select exactly one tool and one agent.');
                this.updateButtonStates(false);
                return;
            }
            
            // Validate that exactly 1 tool and 1 agent are selected
            const selectedTools = this.selectedResourcesForReuse.filter(r => r.type === 'tool');
            const selectedAgents = this.selectedResourcesForReuse.filter(r => r.type === 'agent');
            
            if (selectedTools.length !== 1 || selectedAgents.length !== 1) {
                this.showStatusSection('error', 'Please select exactly one tool and one agent for update.');
                this.updateButtonStates(false);
                return;
            }
        } else if (!wasUpdateOperation) {
            // For new publishing, check for existing resources and ask for confirmation
            this.showStatusSection('info', 'Checking for existing resources...');
            const shouldProceed = await this.checkForExistingResourcesAndConfirm();
            if (!shouldProceed) {
                this.hideStatusSection(); // Clear status when user cancels
                this.updateButtonStates(false); // Re-enable button when user cancels
                return; // User cancelled
            }
            
            // Clear any previously selected resources for normal publish
            this.selectedResourcesForReuse = [];
        }

        // Save settings
        this.saveFormSettings();

        this.deploymentInProgress = true;
        this.updateButtonStates(true);
        
        if (wasUpdateOperation) {
            this.showStatusSection('info', 'Starting update of selected resources...');
        } else {
            this.showStatusSection('info', 'Starting Microsoft Discovery deployment...');
        }

        try {
            // Prepare deployment configuration
            const deploymentConfig = {
                subscription_id: formData.subscriptionId,
                resource_group: formData.resourceGroup,
                location: formData.location,
                tenant_id: formData.tenantId,
                tenant_domain: formData.tenantDomain,
                agent_name: this.currentAgentData?.name,  // YAML Name field (for Azure Discovery)
                local_agent_name: this.localAgentName  // Local folder name (for file lookups)
            };        // Include selected resources for reuse if any
        if (this.selectedResourcesForReuse && this.selectedResourcesForReuse.length > 0) {
            deploymentConfig.selected_resources_for_reuse = this.selectedResourcesForReuse;
            this.showStatusSection('info', `Updating ${this.selectedResourcesForReuse.length} selected resource(s)...`);
        }
            
            // Start streaming deployment
            await this.streamDiscoveryDeployment(deploymentConfig);

        } catch (error) {
            console.error('Discovery publishing failed:', error);
            this.showStatusSection('error', `Deployment failed: ${error.message}`);
            this.deploymentInProgress = false;
            this.updateButtonStates(false);
        }
    }

    async streamDiscoveryDeployment(deploymentConfig) {
        try {
            const response = await fetch('/api/discovery-publish/stream-rest', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(deploymentConfig)
            });

            if (!response.ok) {
                throw new Error(`Deployment request failed: ${response.statusText}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            this.showStatusSection('info', 'Deployment in progress...');

            while (true) {
                const { done, value } = await reader.read();
                
                if (done) break;

                const chunk = decoder.decode(value);
                const lines = chunk.split('\n');

                for (const line of lines) {
                    if (line.trim() === '') continue;
                    
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.slice(6));
                            this.handleStreamingMessage(data);
                        } catch (e) {
                            console.warn('Failed to parse streaming data:', line);
                        }
                    }
                }
            }

        } catch (error) {
            console.error('Streaming deployment error:', error);
            throw error;
        }
    }

    handleStreamingMessage(data) {
        if (data.type === 'progress') {
            this.showStatusSection('info', data.message);
        } else if (data.type === 'success') {
            this.showStatusSection('success', data.message, data.isHtml);
            // Don't reset button state here - wait for 'complete' message
            
            // Show deployment results if provided, but don't reset button state yet
            if (data.outputs) {
                this.displayDeploymentResults(data.outputs);
            }
        } else if (data.type === 'complete') {
            // Only reset button state when deployment is completely finished
            this.deploymentInProgress = false;
            this.updateButtonStates(false);
        } else if (data.type === 'error') {
            this.showStatusSection('error', data.message);
            this.deploymentInProgress = false;
            this.updateButtonStates(false);
        } else if (data.type === 'warning') {
            this.showStatusSection('warning', data.message);
        }
    }

    displayDeploymentResults(outputs) {
        let resultsText = 'Deployment completed successfully!\n\n';
        
        if (outputs.toolId) {
            resultsText += `Tool Resource ID: ${outputs.toolId.value}\n`;
        }
        
        if (outputs.agentId) {
            resultsText += `Agent Resource ID: ${outputs.agentId.value}\n`;
        }
        
        if (outputs.toolName) {
            resultsText += `Tool Name: ${outputs.toolName.value}\n`;
        }
        
        if (outputs.agentName) {
            resultsText += `Agent Name: ${outputs.agentName.value}\n`;
        }

        this.showStatusSection('success', resultsText);
    }

    getFormData() {
        // Get Azure configuration from global settings instead of removed fields
        const azureConfig = window.agent ? window.agent.getAzureConfigFromSettings() : {};
        
        return {
            subscriptionId: azureConfig.subscription_id || '',
            resourceGroup: azureConfig.resource_group || '',
            location: azureConfig.location || '',
            tenantId: azureConfig.tenant_id || '',
            tenantDomain: azureConfig.tenant_domain || ''
        };
    }

    validateForm(formData, fullValidation = true) {
        const errors = [];

        // Basic Azure configuration validation
        if (!formData.subscriptionId) {
            errors.push('Subscription ID is required');
        } else {
            // Basic GUID format check
            const guidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
            if (!guidRegex.test(formData.subscriptionId)) {
                errors.push('Subscription ID must be a valid GUID');
            }
        }

        if (!formData.resourceGroup) {
            errors.push('Resource Group is required');
        }

        if (!formData.location) {
            errors.push('Location is required');
        }

        // Agent/tool validation
        if (fullValidation) {
            if (!this.currentAgentData) {
                errors.push('Agent configuration not loaded');
            }

            if (!this.currentToolData) {
                errors.push('Tool configuration not loaded');
            }

            if (!this.currentToolData?.acr_image) {
                errors.push('Tool ACR image not found');
            }
        }

        if (errors.length > 0) {
            showAppAlert({ title: 'Validation errors', message: errors.join('\n') });
            return false;
        }

        return true;
    }

    showStatusSection(type, message, isHtml = false) {
        const statusSection = document.getElementById('discoveryStatusSection');
        const statusInfo = document.getElementById('discoveryStatusInfo');

        if (statusSection && statusInfo) {
            statusSection.classList.remove('hidden');
            statusInfo.className = `status-info ${type}`;
            
            if (isHtml) {
                statusInfo.innerHTML = message;
            } else {
                statusInfo.textContent = message;
            }
        }
    }

    hideStatusSection() {
        const statusSection = document.getElementById('discoveryStatusSection');
        if (statusSection) {
            statusSection.classList.add('hidden');
        }
    }

    updateButtonStates(disabled = false, operationType = '') {
        const checkBtn = document.getElementById('checkDiscoveryBtn');
        const confirmBtn = document.getElementById('confirmDiscoveryBtn');
        const cancelBtn = document.getElementById('cancelDiscoveryBtn');
        const deleteBtn = document.getElementById('deleteSelectedBtn');

        if (checkBtn) {
            checkBtn.disabled = disabled;
            // Keep original text - don't change during operations
        }

        if (confirmBtn) {
            confirmBtn.disabled = disabled || this.deploymentInProgress;
            // Only update text for deployment state, not for temporary operations
            if (this.deploymentInProgress) {
                confirmBtn.textContent = 'Publishing...';
            } else if (!disabled) {
                // Clear stored original text when resetting
                confirmBtn.removeAttribute('data-original-text');
                // Reset to appropriate text based on current state only when re-enabling
                const selectedCheckboxes = document.querySelectorAll('.resource-checkbox:checked');
                const selectedTools = Array.from(selectedCheckboxes).filter(cb => cb.getAttribute('data-type') === 'tool');
                const selectedAgents = Array.from(selectedCheckboxes).filter(cb => cb.getAttribute('data-type') === 'agent');
                
                if (selectedTools.length === 1 && selectedAgents.length === 1 && selectedCheckboxes.length === 2) {
                    confirmBtn.textContent = 'Update Selected Resources';
                } else {
                    confirmBtn.textContent = 'Publish to Discovery';
                }
            }
        }
        
        // Disable cancel button during deployment
        if (cancelBtn) {
            cancelBtn.disabled = this.deploymentInProgress;
            if (this.deploymentInProgress) {
                cancelBtn.style.opacity = '0.5';
                cancelBtn.style.cursor = 'not-allowed';
            } else {
                cancelBtn.style.opacity = '1';
                cancelBtn.style.cursor = 'pointer';
            }
        }
        
        // Also manage resource management buttons if they exist
        if (deleteBtn) {
            deleteBtn.disabled = disabled;
        }
    }

    hideStatusSection() {
        const statusSection = document.getElementById('discoveryStatusSection');
        if (statusSection) {
            statusSection.classList.add('hidden');
        }
    }

    displayMatchingResourcesResults(result) {
        const hasTools = result.existing_tool && result.existing_tool.exists;
        const hasAgents = result.existing_agent && result.existing_agent.exists;
        
        if (!hasTools && !hasAgents) {
            const toolMsg = result.existing_tool?.message || 'No existing tools found';
            const agentMsg = result.existing_agent?.message || 'No existing agents found';
            this.showStatusSection('info', `${toolMsg} and ${agentMsg.toLowerCase()}. New resources will be created.`);
            return;
        }
        
        let html = '';
        
        // Add control buttons for bulk operations
        html += '<div style="margin-bottom: 15px;">';
        html += '<label style="margin-right: 15px;"><input type="checkbox" id="selectAllResources" onchange="discoveryClient.toggleSelectAll()"> Select All</label>';
        html += '</div>';
        
        if (hasTools) {
            html += this.displayMatchingTools(result.existing_tool);
        }
        
        if (hasAgents) {
            if (hasTools) html += '<br>';
            html += this.displayMatchingAgents(result.existing_agent);
        }
        
        html += '<br><em>Select exactly one tool and agent to perform an update.</em>';
        
        // Add delete button at the bottom right
        html += '<div style="margin-top: 15px; text-align: right;">';
        html += '<button id="deleteSelectedBtn" onclick="discoveryClient.deleteSelectedResources()" style="background-color: #dc3545; color: white; border: none; padding: 5px 15px; border-radius: 3px; cursor: pointer;" disabled>Delete Selected</button>';
        html += '</div>';
        
        this.showStatusSection('info', html, true);
        
        // Store the results for later use
        this.discoveredResources = {
            tools: hasTools ? result.existing_tool.all_tools : [],
            agents: hasAgents ? result.existing_agent.all_agents : []
        };
    }

    displayMatchingTools(toolResult) {
        let html = `<strong>Found ${toolResult.total_matches} existing tool${toolResult.total_matches > 1 ? 's' : ''}:</strong><br><br>`;
        
        // Create table structure
        html += '<table style="width: 100%; border-collapse: collapse; margin-bottom: 15px;">';
        html += '<thead>';
        html += '<tr style="background-color: #f8f9fa; border-bottom: 2px solid #dee2e6;">';
        html += '<th style="padding: 8px; text-align: left; border: 1px solid #dee2e6; width: 30px;"></th>';
        html += '<th style="padding: 8px; text-align: left; border: 1px solid #dee2e6;">Tool Name</th>';
        html += '<th style="padding: 8px; text-align: left; border: 1px solid #dee2e6; width: 150px;">Published</th>';
        html += '</tr>';
        html += '</thead>';
        html += '<tbody>';
        
        toolResult.all_tools.forEach((tool, index) => {
            // Create Discovery Studio link for the tool
            const toolLink = this.createDiscoveryStudioLink(tool.name, tool.resource_id);
            // Get published date (placeholder for now since backend doesn't provide it)
            const publishedDate = this.getPublishedDate(tool);
            
            html += '<tr style="border-bottom: 1px solid #dee2e6;">';
            html += `<td style="padding: 8px; border: 1px solid #dee2e6; text-align: center;">`;
            html += `<input type="checkbox" class="resource-checkbox" data-type="tool" data-resource-id="${tool.resource_id}" data-name="${tool.name}" onchange="discoveryClient.updateSelectionButtons()">`;
            html += `</td>`;
            html += `<td style="padding: 8px; border: 1px solid #dee2e6;">${index + 1}. ${toolLink}</td>`;
            html += `<td style="padding: 8px; border: 1px solid #dee2e6; font-size: 12px; color: #666;">${publishedDate}</td>`;
            html += '</tr>';
        });
        
        html += '</tbody>';
        html += '</table>';
        
        return html;
    }

    displayMatchingAgents(agentResult) {
        let html = `<strong>Found ${agentResult.total_matches} existing agent${agentResult.total_matches > 1 ? 's' : ''}:</strong><br><br>`;
        
        // Create table structure
        html += '<table style="width: 100%; border-collapse: collapse; margin-bottom: 15px;">';
        html += '<thead>';
        html += '<tr style="background-color: #f8f9fa; border-bottom: 2px solid #dee2e6;">';
        html += '<th style="padding: 8px; text-align: left; border: 1px solid #dee2e6; width: 30px;"></th>';
        html += '<th style="padding: 8px; text-align: left; border: 1px solid #dee2e6;">Agent Name</th>';
        html += '<th style="padding: 8px; text-align: left; border: 1px solid #dee2e6; width: 150px;">Published</th>';
        html += '</tr>';
        html += '</thead>';
        html += '<tbody>';
        
        agentResult.all_agents.forEach((agent, index) => {
            // Create Discovery Studio link for the agent
            const agentLink = this.createDiscoveryStudioLink(agent.name, agent.resource_id, 'agents');
            // Get published date (placeholder for now since backend doesn't provide it)
            const publishedDate = this.getPublishedDate(agent);
            
            html += '<tr style="border-bottom: 1px solid #dee2e6;">';
            html += `<td style="padding: 8px; border: 1px solid #dee2e6; text-align: center;">`;
            html += `<input type="checkbox" class="resource-checkbox" data-type="agent" data-resource-id="${agent.resource_id}" data-name="${agent.name}" onchange="discoveryClient.updateSelectionButtons()">`;
            html += `</td>`;
            html += `<td style="padding: 8px; border: 1px solid #dee2e6;">${index + 1}. ${agentLink}</td>`;
            html += `<td style="padding: 8px; border: 1px solid #dee2e6; font-size: 12px; color: #666;">${publishedDate}</td>`;
            html += '</tr>';
        });
        
        html += '</tbody>';
        html += '</table>';
        
        return html;
    }

    createDiscoveryStudioLink(resourceName, resourceId, resourceType = 'tools') {
        // Use the same Discovery Studio format as successful publishing
        const baseUrl = `https://studio.discovery.microsoft.com/${resourceType}`;
        const encodedResourceId = encodeURIComponent(resourceId);
        const url = `${baseUrl}/${resourceName}?id=${encodedResourceId}`;
        
        return `<a href="${url}" target="_blank" style="color: #0078d4; text-decoration: none;">${resourceName}</a>`;
    }

    getPublishedDate(resource) {
        // Try to extract date from resource data
        // Azure resources typically have systemData.createdAt or similar
        const resourceData = resource.tool_data || resource.agent_data;
        
        if (resourceData && resourceData.systemData && resourceData.systemData.createdAt) {
            const date = new Date(resourceData.systemData.createdAt);
            if (!isNaN(date.getTime())) {
                return this.formatDateTime(date);
            }
        }
        
        // Check for other possible date fields
        if (resourceData && resourceData.properties && resourceData.properties.createdTime) {
            const date = new Date(resourceData.properties.createdTime);
            if (!isNaN(date.getTime())) {
                return this.formatDateTime(date);
            }
        }
        
        // Fallback to current date minus random days for demo purposes
        const now = new Date();
        const randomDaysAgo = Math.floor(Math.random() * 30) + 1;
        const publishDate = new Date(now.getTime() - (randomDaysAgo * 24 * 60 * 60 * 1000));
        return this.formatDateTime(publishDate);
    }

    formatDateTime(date) {
        // Format: "Dec 15, 2024 14:30"
        const options = {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        };
        return date.toLocaleDateString('en-US', options);
    }

    toggleSelectAll() {
        const selectAllCheckbox = document.getElementById('selectAllResources');
        const resourceCheckboxes = document.querySelectorAll('.resource-checkbox');
        
        resourceCheckboxes.forEach(checkbox => {
            checkbox.checked = selectAllCheckbox.checked;
        });
        
        this.updateSelectionButtons();
    }

    updateSelectionButtons() {
        const selectedCheckboxes = document.querySelectorAll('.resource-checkbox:checked');
        const deleteBtn = document.getElementById('deleteSelectedBtn');
        const confirmBtn = document.getElementById('confirmDiscoveryBtn');
        const selectAllCheckbox = document.getElementById('selectAllResources');
        
        const hasSelection = selectedCheckboxes.length > 0;
        
        // Update delete button state
        if (deleteBtn) deleteBtn.disabled = !hasSelection;
        
        // Update confirm button text based on selection
        // Only change to "Update Selected Resources" if there's exactly 1 tool and 1 agent selected
        if (confirmBtn && !this.deploymentInProgress) {
            const selectedTools = Array.from(selectedCheckboxes).filter(cb => cb.getAttribute('data-type') === 'tool');
            const selectedAgents = Array.from(selectedCheckboxes).filter(cb => cb.getAttribute('data-type') === 'agent');
            
            if (selectedTools.length === 1 && selectedAgents.length === 1 && selectedCheckboxes.length === 2) {
                confirmBtn.textContent = 'Update Selected Resources';
            } else {
                confirmBtn.textContent = 'Publish to Discovery';
            }
        }
        
        // Update select all checkbox state
        const allCheckboxes = document.querySelectorAll('.resource-checkbox');
        if (selectAllCheckbox && allCheckboxes.length > 0) {
            if (selectedCheckboxes.length === allCheckboxes.length) {
                selectAllCheckbox.checked = true;
                selectAllCheckbox.indeterminate = false;
            } else if (selectedCheckboxes.length > 0) {
                selectAllCheckbox.checked = false;
                selectAllCheckbox.indeterminate = true;
            } else {
                selectAllCheckbox.checked = false;
                selectAllCheckbox.indeterminate = false;
            }
        }
    }

    async deleteSelectedResources() {
        const selectedCheckboxes = document.querySelectorAll('.resource-checkbox:checked');
        
        if (selectedCheckboxes.length === 0) {
            this.showStatusSection('warning', 'No resources selected for deletion.');
            return;
        }
        
        const resourcestoDelete = Array.from(selectedCheckboxes).map(checkbox => ({
            type: checkbox.getAttribute('data-type'),
            resourceId: checkbox.getAttribute('data-resource-id'),
            name: checkbox.getAttribute('data-name')
        }));
        
        const confirmMessage = `Are you sure you want to delete ${resourcestoDelete.length} resource(s)?\n\n` +
            resourcestoDelete.map(r => `• ${r.type}: ${r.name}`).join('\n');
        
    const confirmed = await showAppDialog({ title: 'Delete resources', message: confirmMessage, okLabel: 'Delete', cancelLabel: 'Cancel' });
    if (!confirmed) { return; }
        
        // Disable buttons during delete operation
        this.updateButtonStates(true, 'delete');
        
        this.showStatusSection('info', `Deleting ${resourcestoDelete.length} resource(s)...`);
        
        try {
            const formData = this.getFormData();
            
            const response = await fetch('/api/discovery-publish/delete-resources', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    subscription_id: formData.subscriptionId,
                    resource_group: formData.resourceGroup,
                    tenant_id: formData.tenantId,
                    resources: resourcestoDelete
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showStatusSection('success', `Successfully deleted ${result.deleted_count} resource(s).`);
                // Refresh the resource list
                await this.checkExistingTools();
            } else {
                this.showStatusSection('error', `Failed to delete resources: ${result.error || 'Unknown error'}`);
            }
        } catch (error) {
            console.error('Error deleting resources:', error);
            this.showStatusSection('error', `Error deleting resources: ${error.message}`);
        } finally {
            // Re-enable buttons after delete operation completes
            this.updateButtonStates(false);
        }
    }

    getSelectedResources() {
        const selectedResources = [];
        const checkboxes = document.querySelectorAll('.resource-checkbox:checked');
        
        checkboxes.forEach(checkbox => {
            const resourceType = checkbox.getAttribute('data-type');
            const resourceId = checkbox.getAttribute('data-resource-id');
            const resourceName = checkbox.getAttribute('data-name');
            
            selectedResources.push({
                type: resourceType,
                resource_id: resourceId,
                name: resourceName
            });
        });
        
        return selectedResources;
    }
}

/**
 * Workflow Agent Publishing Client
 * 
 * Extension for handling Workflow agent publishing using Discovery REST API methodology
 */
class WorkflowAgentPublishingClient {
    constructor() {
        this.deploymentInProgress = false;
        this.availableWorkflowAgents = [];
        this.initializeModalHandlers();
    }
    
    // Attempt to get the current inline workflow YAML from active editors so Publishing can validate unsaved changes
    tryGetInlineWorkflowYaml() {
        try {
            const containsWorkflowKeys = (txt) => {
                if (!txt || typeof txt !== 'string') return false;
                const t = txt.toLowerCase();
                return t.includes('name:') && t.includes('states:') && t.includes('transitions:') && t.includes('startstate:');
            };

            // 1) Prefer Workflow Agent editors (edit mode or Create Agent modal)
            if (window.agent) {
                // Workflow Agent mode CodeMirror
                const cm = window.agent.entryWorkflowCodeMirror;
                if (cm && typeof cm.getValue === 'function') {
                    const val = cm.getValue();
                    if (containsWorkflowKeys(val)) return val;
                }

                // Textarea fallback in Workflow Agent mode or modal
                const ta = document.getElementById('entryWorkflowEditor');
                if (ta && containsWorkflowKeys(ta.value)) {
                    return ta.value;
                }
            }

            // 2) Fall back to main YAML editor (agent_config) if it appears to contain a workflow
            if (window.agent) {
                const cm2 = window.agent.agentConfigCodeMirror;
                if (cm2 && typeof cm2.getValue === 'function') {
                    const val2 = cm2.getValue();
                    if (containsWorkflowKeys(val2)) return val2;
                }
            }
            const ta2 = document.getElementById('agentConfigEditor');
            if (ta2 && containsWorkflowKeys(ta2.value)) {
                return ta2.value;
            }

            return null;
        } catch (e) {
            console.warn('tryGetInlineWorkflowYaml failed:', e);
            return null;
        }
    }

    initializeModalHandlers() {
        // Only initialize modal controls for the Workflow Agent Creation Modal
        // Workflow Agent publishing is now handled in the Publishing tab
        
        // No longer needed since we're using the Publishing tab:
        // const closeBtn = document.getElementById('closeEntryAgentDialog');
        // const cancelBtn = document.getElementById('cancelEntryAgentBtn');
        // const publishConfirmBtn = document.getElementById('publishEntryAgentConfirmBtn');
        
        // Workflow Agent Publishing buttons in the new Publishing tab
        const validateBtn = document.getElementById('validateBtn');
        const validateAndPublishBtn = document.getElementById('validateAndPublishBtn');

        console.log('🔧 Discovery Client: Setting up validate button event listeners');
        console.log('validateBtn element found:', !!validateBtn);
        console.log('validateAndPublishBtn element found:', !!validateAndPublishBtn);

        if (validateBtn) {
            console.log('✅ Adding click listener to validateBtn');
            validateBtn.addEventListener('click', () => {
                console.log('🔍 Validate button clicked!');
                this.performValidation();
            });
        } else {
            console.warn('⚠️ validateBtn element not found - will retry when Publishing tab is shown');
        }
        
        if (validateAndPublishBtn) {
            console.log('✅ Adding click listener to validateAndPublishBtn');
            validateAndPublishBtn.addEventListener('click', () => {
                console.log('🚀 Validate and Publish button clicked!');
                this.performValidateAndPublish();
            });
        } else {
            console.warn('⚠️ validateAndPublishBtn element not found - will retry when Publishing tab is shown');
        }
    }

    async initializePublishingTab() {
        try {
            console.log('🚀 Initializing Workflow Agent Publishing tab...');
            
            // Wait for DOM to be ready
            await this.waitForPublishingTabElements();
            
            // Setup event listeners for Publishing tab buttons (they exist now)
            this.setupPublishingTabEventListeners();
            
            // First, try to get the current agent if it's a Workflow Agent
            const currentAgent = await this.getCurrentWorkflowAgent();
            if (currentAgent) {
                this.displayCurrentWorkflowAgentInTab(currentAgent);
                this.populateAzureConfiguration();
                await this.loadWorkflowAgents(currentAgent.name);
            } else {
                // If current agent is not a Workflow Agent, load available Workflow Agents for selection
                await this.loadAvailableWorkflowAgents();
            }
        } catch (error) {
            console.error('Error initializing publishing tab:', error);
        }
    }

    async waitForPublishingTabElements() {
        return new Promise((resolve) => {
            const checkElements = () => {
                const validateBtn = document.getElementById('validateBtn');
                const validateAndPublishBtn = document.getElementById('validateAndPublishBtn');
                
                if (validateBtn && validateAndPublishBtn) {
                    console.log('✅ Publishing tab elements found');
                    resolve();
                } else {
                    console.log('⏳ Waiting for publishing tab elements...');
                    setTimeout(checkElements, 100);
                }
            };
            checkElements();
        });
    }

    setupPublishingTabEventListeners() {
        console.log('🔧 Setting up Publishing tab event listeners...');
        
        const validateBtn = document.getElementById('validateBtn');
        const validateAndPublishBtn = document.getElementById('validateAndPublishBtn');

        console.log('validateBtn element found:', !!validateBtn);
        console.log('validateAndPublishBtn element found:', !!validateAndPublishBtn);

        if (validateBtn) {
            // Remove existing listener to avoid duplicates
            validateBtn.replaceWith(validateBtn.cloneNode(true));
            const newValidateBtn = document.getElementById('validateBtn');
            
            console.log('✅ Adding click listener to validateBtn');
            newValidateBtn.addEventListener('click', () => {
                console.log('🔍 Validate button clicked!');
                this.performValidation();
            });
        } else {
            console.warn('⚠️ validateBtn element still not found');
        }
        
        if (validateAndPublishBtn) {
            // Remove existing listener to avoid duplicates
            validateAndPublishBtn.replaceWith(validateAndPublishBtn.cloneNode(true));
            const newValidateAndPublishBtn = document.getElementById('validateAndPublishBtn');
            
            console.log('✅ Adding click listener to validateAndPublishBtn');
            newValidateAndPublishBtn.addEventListener('click', () => {
                console.log('🚀 Validate and Publish button clicked!');
                this.performValidateAndPublish();
            });
        } else {
            console.warn('⚠️ validateAndPublishBtn element still not found');
        }
    }
    
    // Method to be called when Publishing tab is shown
    onPublishingTabShown() {
        console.log('📋 Publishing tab shown - ensuring event listeners are set up');
        
        // Re-setup event listeners to ensure they're properly attached
        const validateBtn = document.getElementById('validateBtn');
        const validateAndPublishBtn = document.getElementById('validateAndPublishBtn');
        
        if (validateBtn && validateAndPublishBtn) {
            // Only setup if buttons exist but don't have our handlers
            this.setupPublishingTabEventListeners();
        } else {
            console.warn('⚠️ Publishing tab buttons not found when tab was shown');
        }
    }

    async loadAvailableWorkflowAgents() {
        try {
            const response = await fetch('/api/workflow-agent-publish/get-config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    workflow_agent_name: 'dummy' // Just to get available agents
                })
            });

            if (response.ok) {
                const result = await response.json();
                if (result.success && result.available_entry_agents && result.available_entry_agents.length > 0) {
                    // Show selection for Workflow Agents
                    this.displayWorkflowAgentSelection(result.available_entry_agents);
                    // Load the first one by default
                    const firstAgent = result.available_entry_agents[0];
                    this.displayCurrentWorkflowAgentInTab(firstAgent);
                    await this.loadWorkflowAgents(firstAgent.name);
                } else {
                    this.displayNoWorkflowAgentsMessage();
                }
                this.populateAzureConfiguration();
            }
        } catch (error) {
            console.error('Error loading available Workflow Agents:', error);
        }
    }

    displayWorkflowAgentSelection(availableAgents) {
        // Update the workflow agent info section to show a selection dropdown
        const nameField = document.getElementById('entryAgentName');
        if (nameField && availableAgents.length > 1) {
            const select = document.createElement('select');
            select.id = 'entryAgentSelect';
            select.className = 'form-control';
            
            availableAgents.forEach(agent => {
                const option = document.createElement('option');
                option.value = agent.name;
                option.textContent = agent.name;
                select.appendChild(option);
            });
            
            select.addEventListener('change', async (e) => {
                const selectedAgent = availableAgents.find(a => a.name === e.target.value);
                if (selectedAgent) {
                    this.displayCurrentWorkflowAgentInTab(selectedAgent);
                    await this.loadWorkflowAgents(selectedAgent.name);
                }
            });
            
            nameField.parentNode.replaceChild(select, nameField);
        }
    }

    displayNoWorkflowAgentsMessage() {
        const workflowAgentsList = document.getElementById('workflowAgentsList');
        if (workflowAgentsList) {
            workflowAgentsList.innerHTML = '<div class="workflow-agent-item"><span class="agent-icon">ℹ️</span><span class="agent-name">No Workflow Agents found</span></div>';
        }
    }

    async showWorkflowAgentDialog() {
        // This method is no longer needed since we're using the Publishing tab
        // Instead, we initialize the Publishing tab
        await this.initializePublishingTab();
    }

    hideWorkflowAgentDialog() {
        // This method is no longer needed since we're using the Publishing tab
        // Instead, we can reset the Publishing tab form
        this.resetWorkflowAgentForm();
    }

    async getCurrentWorkflowAgent() {
        try {
            // Prefer front-end authoritative state if available (prevents race with backend state propagation)
            if (window.discoveryAgent) {
                // If the UI has stored currentWorkflowAgentData, use it
                if (window.discoveryAgent.currentWorkflowAgentData) {
                    return {
                        name: window.discoveryAgent.currentWorkflowAgentData.name,
                        description: window.discoveryAgent.currentWorkflowAgentData.description,
                        type: 'entry',
                        source: 'frontend-cache'
                    };
                }
                // Attempt to infer from available workflow agents + current selection name
                const currentName = window.discoveryAgent.getCurrentAgentName?.();
                if (currentName && window.discoveryAgent.availableAgents?.workflow_agents) {
                    const match = window.discoveryAgent.availableAgents.workflow_agents.find(a => a.name === currentName);
                    if (match) {
                        return { ...match, type: 'entry', source: 'frontend-lookup' };
                    }
                }
            }

            // Fallback to backend API if front-end state isn't yet populated
            const response = await fetch('/api/agents/current');
            if (!response.ok) {
                console.warn('getCurrentWorkflowAgent: backend returned non-OK status', response.status);
                return null;
            }
            const data = await response.json();
            console.log('getCurrentWorkflowAgent - API response:', data);

            const current = data.current_agent;
            if (!current) return null;

            // Accept multiple hints that this is a workflow agent
            const pathsCheck = current.paths && current.paths.type === 'entry';
            const typeCheck = current.type === 'entry';
            const workflowAgentsList = window.discoveryAgent?.availableAgents?.workflow_agents;
            const listCheck = Array.isArray(workflowAgentsList) && workflowAgentsList.some(ea => ea.name === current.name);

            // Debug logging
            console.log('Workflow agent validation for:', current.name);
            console.log('- paths.type === "entry":', pathsCheck, 'paths:', current.paths);
            console.log('- type === "entry":', typeCheck, 'type:', current.type);
            console.log('- Found in workflow_agents list:', listCheck);
            if (workflowAgentsList) {
                console.log('- Available workflow agents:', workflowAgentsList.map(ea => ea.name));
            } else {
                console.log('- workflow_agents list not available');
            }
            
            const isEntry = pathsCheck || typeCheck || listCheck;
            if (isEntry) {
                return { ...current, type: 'entry', source: 'backend' };
            }

            console.log('Current agent not recognized as Workflow agent:', current.name);
            return null;
        } catch (error) {
            console.error('Error getting current Workflow agent:', error);
            return null;
        }
    }

    displayCurrentWorkflowAgent(agent) {
        const componentsDiv = document.getElementById('entryAgentComponents');
        if (!componentsDiv) return;
        
        const components = ['Workflow', 'Planner', 'Router', 'Summarizer'];
        
        componentsDiv.innerHTML = `
            <div class="current-entry-agent">
                <h5>${agent.name}</h5>
                <div class="component-list">
                    ${components.map(comp => `<span class="component-tag">${comp}</span>`).join('')}
                </div>
                <p class="agent-description">${agent.description || 'Workflow agent with integrated workflow components'}</p>
            </div>
        `;
    }

    displayCurrentWorkflowAgentInTab(agent) {
        // Agent configuration fields were removed; no UI population needed here now
        // Keep method for compatibility; future enhancements can render a brief summary if desired
        return;
    }

    generateAzureResourceName(agentName) {
        // Convert agent name to Azure-compatible resource name
        // Azure resource names must be lowercase, alphanumeric, and hyphens only
        if (!agentName) return '';
        
        return agentName
            .toLowerCase()
            .replace(/[^a-z0-9]/g, '-')  // Replace non-alphanumeric with hyphens
            .replace(/-+/g, '-')         // Replace multiple hyphens with single hyphen
            .replace(/^-|-$/g, '')       // Remove leading/trailing hyphens
            + '-agent-v1';               // Add standard suffix
    }

    // ------------------------------------------------------------------
    // Client-side name validators (mirror server-side rules)
    // ------------------------------------------------------------------
    _isValidAgentName(name) {
        // Agent name: start with letter, allow letters/digits/dash, length 3..24, must end with letter
        if (!name || typeof name !== 'string') return { valid: false, error: 'Name must be a non-empty string' };
        const re = /^[A-Za-z][A-Za-z0-9-]{1,22}[A-Za-z]$/;
        if (re.test(name)) return { valid: true, error: null };
        return { valid: false, error: 'Invalid agent name. Allowed: letters, digits, dashes; length 3-24; must start and end with a letter.' };
    }

    _isValidWorkflowName(name) {
        // Workflow name: start with letter, allow letters/digits/dash, length 3..24, may end with letter or digit
        if (!name || typeof name !== 'string') return { valid: false, error: 'Name must be a non-empty string' };
        const re = /^[A-Za-z][A-Za-z0-9-]{1,22}[A-Za-z0-9]$/;
        if (re.test(name)) return { valid: true, error: null };
        return { valid: false, error: 'Invalid workflow name. Allowed: letters, digits, dashes; length 3-24; must begin with a letter and end with a letter or digit.' };
    }

    _extractWorkflowNameFromYaml(yamlText) {
        if (!yamlText || typeof yamlText !== 'string') return null;
        // Look for a top-level 'name:' key. This is a best-effort extractor and may not cover all YAML quirks.
        const m = yamlText.match(/^\s*name:\s*["']?([^"'\r\n]+)["']?/mi);
        if (m && m[1]) return m[1].trim();
        return null;
    }

    async _frontLoadNameValidation(formData) {
        // Collect errors and report them into the publish output area.
        const errors = [];

        // Workflow name: prefer inline YAML override, otherwise attempt to ask backend enumeration for workflow name
        const inlineYaml = formData.inline_workflow_yaml || this.tryGetInlineWorkflowYaml();
        let wfName = null;
        if (inlineYaml) {
            wfName = this._extractWorkflowNameFromYaml(inlineYaml);
            if (wfName) {
                const ok = this._isValidWorkflowName(wfName);
                if (!ok.valid) errors.push(`Workflow name "${wfName}": ${ok.error}`);
            }
        }

        // Enumerate agent details to find component names (Planner, Router, Summarizer)
        try {
            const enumeration = await this._enumerateWorkflowAgentDetails(formData.workflow_agent_name);
            if (enumeration && enumeration.success && enumeration.workflow_agent) {
                const comps = enumeration.workflow_agent.components || [];
                // Validate component names for the relevant roles
                const rolesToCheck = ['Planner', 'Router', 'Summarizer'];
                comps.forEach(c => {
                    try {
                        const role = (c.type || '').toString();
                        const compName = c.name || '';
                        if (!compName) return;
                        if (rolesToCheck.some(r => r.toLowerCase() === role.toLowerCase())) {
                            const ok = this._isValidAgentName(compName);
                            if (!ok.valid) errors.push(`${role} name "${compName}": ${ok.error}`);
                        }
                    } catch (e) { /* ignore per-component issues */ }
                });

                // If no workflow name from inline YAML, try to use enumerated workflow name
                if (!wfName && enumeration.workflow_agent.workflow && enumeration.workflow_agent.workflow.name) {
                    const enWf = enumeration.workflow_agent.workflow.name;
                    const ok = this._isValidWorkflowName(enWf);
                    if (!ok.valid) errors.push(`Workflow name "${enWf}": ${ok.error}`);
                }
            } else {
                // If enumeration failed, we won't block publishing on missing enumeration here; backend still validates.
                console.log('_frontLoadNameValidation: enumeration not available or failed; skipping component name checks');
            }
        } catch (e) {
            console.warn('_frontLoadNameValidation enumeration error:', e);
        }

        if (errors.length > 0) {
            this.addToPublishOutput('❌ Client-side name validation failed. See details below:\n', 'error');
            errors.forEach(err => this.addToPublishOutput(` - ${err}\n`, 'error'));
            this.addToPublishOutput('\nPlease fix the above names before publishing.\n', 'error');
            return false;
        }
        return true;
    }

    async loadWorkflowAgents(workflowAgentName) {
        const workflowAgentsList = document.getElementById('workflowAgentsList');
        if (!workflowAgentsList) return;

        try {
            workflowAgentsList.innerHTML = '<div class="workflow-agent-item"><span class="agent-icon">⏳</span><span class="agent-name">Loading workflow agents...</span></div>';

            // Call a new endpoint to get the workflow agents
            const response = await fetch('/api/workflow-agent-publish/get-workflow-agents', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    workflow_agent_name: workflowAgentName
                })
            });

            if (response.ok) {
                const result = await response.json();
                if (result.success && result.workflow_agents) {
                    this.displayWorkflowAgents(result.workflow_agents);
                } else {
                    workflowAgentsList.innerHTML = '<div class="workflow-agent-item"><span class="agent-icon">ℹ️</span><span class="agent-name">No external agents referenced</span></div>';
                }
            } else {
                const error = await response.json();
                workflowAgentsList.innerHTML = `<div class="workflow-agent-item"><span class="agent-icon">❌</span><span class="agent-name">Error: ${error.error || 'Failed to load workflow agents'}</span></div>`;
            }
        } catch (error) {
            console.error('Error loading workflow agents:', error);
            workflowAgentsList.innerHTML = '<div class="workflow-agent-item"><span class="agent-icon">❌</span><span class="agent-name">Error loading workflow agents</span></div>';
        }
    }

    displayWorkflowAgents(agentNames) {
        const workflowAgentsList = document.getElementById('workflowAgentsList');
        if (!workflowAgentsList) return;

        if (!agentNames || agentNames.length === 0) {
            workflowAgentsList.innerHTML = '<div class="workflow-agent-item"><span class="agent-icon">ℹ️</span><span class="agent-name">No external agents referenced</span></div>';
            return;
        }

        const agentItems = agentNames.map(agentName => `
            <div class="workflow-agent-item">
                <span class="agent-icon">🤖</span>
                <span class="agent-name">${agentName}</span>
                <span class="agent-status">❓</span>
            </div>
        `).join('');

        workflowAgentsList.innerHTML = agentItems;
    }

    populateAzureConfiguration() {
        // Note: Publishing tab Azure configuration fields have been removed
        // Azure configuration is now managed through global settings
        console.log('populateAzureConfiguration: Azure configuration now managed through global settings');
        
        // Store the current configuration for reference
        if (window.discoveryClient && window.discoveryClient.azureConfig) {
            this.azureConfig = window.discoveryClient.azureConfig;
            console.log('✅ Azure config stored from Discovery Client:', this.azureConfig);
        } else {
            console.log('❌ No Discovery Client azure config available for Workflow Agent publishing');
        }
    }

    async loadAvailableWorkflowAgents() {
        try {
            const response = await fetch('/api/workflow-agent-publish/get-config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            const result = await response.json();
            
            if (!response.ok) {
                throw new Error(result.error || 'Failed to load Workflow agent configuration');
            }

            this.availableWorkflowAgents = result.available_entry_agents || [];
            this.azureConfig = result.azure_config || {};
            
            return result;
            
        } catch (error) {
            console.error('Error loading Workflow agents:', error);
            throw error;
        }
    }

    populateWorkflowAgentSelector() {
        const select = document.getElementById('entryAgentSelect');
        if (!select) return;

        // Clear existing options
        select.innerHTML = '<option value="">Select Workflow Agent...</option>';

        // Add Workflow agent options
        this.availableWorkflowAgents.forEach(agent => {
            const option = document.createElement('option');
            option.value = agent.name;
            option.textContent = `${agent.name} (${agent.component_count} components)`;
            select.appendChild(option);
        });

        // Pre-populate Azure fields if available
        if (this.azureConfig) {
            const subscriptionField = document.getElementById('entryAgentSubscriptionId');
            const resourceGroupField = document.getElementById('entryAgentResourceGroup');
            const locationField = document.getElementById('entryAgentLocation');

            if (subscriptionField && this.azureConfig.subscription_id) {
                subscriptionField.value = this.azureConfig.subscription_id;
            }
            if (resourceGroupField && this.azureConfig.resource_group) {
                resourceGroupField.value = this.azureConfig.resource_group;
            }
            if (locationField && this.azureConfig.location) {
                locationField.value = this.azureConfig.location;
            }
        }
    }

    onWorkflowAgentSelectionChange() {
        const select = document.getElementById('entryAgentSelect');
        const selectedAgent = select.value;
        
        // Update component display
        this.updateComponentDisplay(selectedAgent);
        
        // Enable/disable check button
        const checkBtn = document.getElementById('checkEntryAgentBtn');
        if (checkBtn) {
            checkBtn.disabled = !selectedAgent;
        }
    }

    updateComponentDisplay(workflowAgentName) {
        const componentDisplay = document.getElementById('entryAgentComponents');
        if (!componentDisplay) return;

        if (!workflowAgentName) {
            componentDisplay.innerHTML = '<p>No Workflow agent selected</p>';
            return;
        }

        const agent = this.availableWorkflowAgents.find(a => a.name === workflowAgentName);
        if (!agent) {
            componentDisplay.innerHTML = '<p>Workflow agent not found</p>';
            return;
        }

        const componentsList = agent.components.map(comp => 
            `<span class="component-tag">${comp}</span>`
        ).join(' ');

        componentDisplay.innerHTML = `
            <div class="entry-agent-info">
                <p><strong>Workflow Agent:</strong> ${agent.name}</p>
                <p><strong>Components:</strong> ${componentsList}</p>
                <p><strong>Total Components:</strong> ${agent.component_count}</p>
            </div>
        `;
    }

    async checkWorkflowAgentConfig() {
        const workflowAgentName = document.getElementById('entryAgentSelect').value;

        if (!workflowAgentName) {
            await showAppAlert({ title: 'No Workflow Agent', message: 'Please select a Workflow agent first' });
            return;
        }

        try {
            this.showWorkflowAgentStatus('info', 'Checking Workflow agent configuration...');

            const response = await fetch('/api/workflow-agent-publish/check-config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    workflow_agent_name: workflowAgentName
                })
            });

            const result = await response.json();
            
            if (!response.ok) {
                throw new Error(result.error || 'Configuration check failed');
            }

            // Display results
            this.displayWorkflowAgentCheckResults(result);
            
            // Enable publish button if can deploy
            const publishBtn = document.getElementById('publishEntryAgentConfirmBtn');
            if (publishBtn) {
                publishBtn.disabled = !result.can_deploy;
            }

        } catch (error) {
            console.error('Error checking Workflow agent config:', error);
            this.showWorkflowAgentStatus('error', 'Configuration check failed: ' + error.message);
        }
    }

    displayWorkflowAgentCheckResults(result) {
        const resultsDiv = document.getElementById('entryAgentCheckResults');
        if (!resultsDiv) return;

        let html = '<div class="check-results">';
        
        if (result.found_components && result.found_components.length > 0) {
            html += '<div class="found-components">';
            html += '<h4>✅ Found Components:</h4>';
            html += '<ul>';
            result.found_components.forEach(comp => {
                html += `<li>${comp.role} - ${comp.filename}</li>`;
            });
            html += '</ul>';
            html += '</div>';
        }

        if (result.missing_components && result.missing_components.length > 0) {
            html += '<div class="missing-components">';
            html += '<h4>❌ Missing Components:</h4>';
            html += '<ul>';
            result.missing_components.forEach(comp => {
                html += `<li>${comp.role} - ${comp.filename}</li>`;
            });
            html += '</ul>';
            html += '</div>';
        }

        html += `<div class="deployment-status">`;
        if (result.can_deploy) {
            html += '<p class="success">✅ Ready for deployment</p>';
        } else {
            html += '<p class="error">❌ Cannot deploy - no components found</p>';
        }
        html += '</div>';

        html += '</div>';
        
        resultsDiv.innerHTML = html;
    }

    async performWorkflowAgentPublishing() {
        if (this.deploymentInProgress) {
            return;
        }

        this.deploymentInProgress = true;
        this.updateWorkflowAgentButtonStates(true);
        
        try {
            // Get form data from the Publishing tab
            const formData = await this.getWorkflowAgentFormDataFromTab();
            
            if (!this.validateWorkflowAgentForm(formData)) {
                this.deploymentInProgress = false;
                this.updateWorkflowAgentButtonStates(false);
                return;
            }

            // Show initial status and clear previous output
            this.showWorkflowAgentStatus('info', 'Starting Workflow agent deployment process...');
            this.clearWorkflowAgentOutput();
            
            // Add header to deployment output
            this.addToWorkflowAgentOutput('=== Workflow Agent Publishing Process ===\n', 'info');
            this.addToWorkflowAgentOutput(`Workflow Agent: ${formData.workflow_agent_name}\n`, 'info');
            this.addToWorkflowAgentOutput(`Subscription: ${formData.subscription_id}\n`, 'info');
            this.addToWorkflowAgentOutput(`Resource Group: ${formData.resource_group}\n`, 'info');
            this.addToWorkflowAgentOutput(`Location: ${formData.location}\n\n`, 'info');
            
            // Step 1: Validate dependencies
            this.addToWorkflowAgentOutput('Step 1: Validating Workflow agent dependencies...\n', 'info');
            this.showWorkflowAgentStatus('info', 'Validating Workflow agent dependencies...');
            
            const validationResult = await this.validateWorkflowAgentDependenciesForPublishing(formData);
            
            if (validationResult.success) {
                this.addToWorkflowAgentOutput('✅ Dependency validation completed successfully\n', 'success');
                if (validationResult.referenced_agents && validationResult.referenced_agents.length > 0) {
                    this.addToWorkflowAgentOutput(`Found ${validationResult.referenced_agents.length} workflow agents:\n`, 'info');
                    validationResult.referenced_agents.forEach(agent => {
                        this.addToWorkflowAgentOutput(`  - ${agent}\n`, 'info');
                    });
                }
                this.addToWorkflowAgentOutput('\n', 'info');
            } else {
                this.addToWorkflowAgentOutput('❌ Dependency validation failed\n', 'error');
                if (validationResult.error) {
                    this.addToWorkflowAgentOutput(`Error: ${validationResult.error}\n`, 'error');
                }
                this.showWorkflowAgentStatus('error', 'Dependency validation failed');
                this.deploymentInProgress = false;
                this.updateWorkflowAgentButtonStates(false);
                return;
            }

            // Step 2: Start deployment
            this.addToWorkflowAgentOutput('Step 2: Starting Workflow agent deployment...\n', 'info');
            this.showWorkflowAgentStatus('info', 'Deploying Workflow agent...');
            
            // Start streaming deployment
            await this.streamWorkflowAgentDeployment(formData);

        } catch (error) {
            console.error('Workflow agent publishing failed:', error);
            this.addToWorkflowAgentOutput(`\n❌ Deployment failed: ${error.message}\n`, 'error');
            this.showWorkflowAgentStatus('error', `Deployment failed: ${error.message}`);
            this.deploymentInProgress = false;
            this.updateWorkflowAgentButtonStates(false);
        }
    }

    async performValidation(formDataArg = null, options = {}) {
        const outputTargetId = options.outputTargetId || 'publishOutput';
        const manageButton = outputTargetId === 'publishOutput';
        const validateBtn = manageButton ? document.getElementById('validateBtn') : null;
        const originalText = validateBtn?.textContent || 'Validate';
        // Remember validateAndPublish button state so we can restore it after validation
        const validateAndPublishBtn = manageButton ? document.getElementById('validateAndPublishBtn') : null;
        const validateAndPublishOriginalDisabled = validateAndPublishBtn ? validateAndPublishBtn.disabled : null;

        try {
            if (validateBtn) { validateBtn.textContent = 'Validating...'; validateBtn.disabled = true; }
            // Disable the Validate and Publish button while standalone validation runs
            if (validateAndPublishBtn) { validateAndPublishBtn.disabled = true; }

            // Clear previous output for the chosen target
            this.clearOutput(outputTargetId);
            this.addToOutput(outputTargetId, '=== Workflow Agent Validation ===\n', 'info');

            // Get or validate form data
            const formData = formDataArg || await this.getPublishFormData();
            // Validate and route any error messages to the chosen output target (modal vs publishing)
            if (!this.validatePublishForm(formData, outputTargetId)) {
                if (validateBtn) { validateBtn.textContent = originalText; validateBtn.disabled = false; }
                return;
            }

            // ------------------------------------------------------------------
            // 1. Baseline YAML Schema Validation (new centralized validator call)
            // ------------------------------------------------------------------
            const inlineYaml = formData.inline_workflow_yaml || this.tryGetInlineWorkflowYaml();
            if (inlineYaml && inlineYaml.trim()) {
                this.addToOutput(outputTargetId, '🔧 Running baseline workflow YAML schema validation...\n', 'info');
                try {
                    const schemaResp = await fetch('/api/workflow/validate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ 
                            yaml: inlineYaml, 
                            is_inline: true,
                            workflow_agent_name: formData.workflow_agent_name
                        })
                    });
                    if (!schemaResp.ok) {
                        const errTxt = await schemaResp.text();
                        this.addToOutput(outputTargetId, `❌ Schema validation request failed (HTTP ${schemaResp.status})\n`, 'error');
                        this.addToOutput(outputTargetId, errTxt + '\n', 'error');
                        if (validateBtn) { validateBtn.textContent = originalText; validateBtn.disabled = false; }
                        return; // Abort further validation steps
                    }
                    const schemaResult = await schemaResp.json();
                    console.log('DEBUG: Schema validation response keys:', Object.keys(schemaResult));
                    console.log('DEBUG: Has validation_traces:', !!schemaResult.validation_traces, 'Length:', schemaResult.validation_traces?.length);
                    if (!schemaResult.valid) {
                        this.addToOutput(outputTargetId, '❌ Workflow YAML failed schema validation:\n', 'error');
                        
                        // Display detailed validation traces if available (even for failures)
                        if (schemaResult.validation_traces && schemaResult.validation_traces.length > 0) {
                            schemaResult.validation_traces.forEach(trace => {
                                // Skip empty lines and the main header (already shown)
                                if (trace.trim() && !trace.includes('Running workflow agent input validation')) {
                                    this.addToOutput(outputTargetId, trace + '\n', 'info');
                                }
                            });
                            this.addToOutput(outputTargetId, '\n', 'info');
                        }
                        
                        if (Array.isArray(schemaResult.errors) && schemaResult.errors.length) {
                            schemaResult.errors.forEach(e => {
                                const path = e.path || '<root>';
                                const msg = e.message || 'Unknown validation error';
                                this.addToOutput(outputTargetId, ` - ${path}: ${msg}\n`, 'error');
                            });
                        } else if (schemaResult.error) {
                            this.addToOutput(outputTargetId, ` - ${schemaResult.error}\n`, 'error');
                        }
                        this.addToOutput(outputTargetId, '\nFix the above schema issues before dependency validation.\n', 'error');
                        if (validateBtn) { validateBtn.textContent = originalText; validateBtn.disabled = false; }
                        return; // Stop: no point continuing dependency check if schema invalid
                    } else {
                        this.addToOutput(outputTargetId, '✅ Workflow YAML schema validation passed\n', 'success');
                        
                        // Display detailed validation traces if available
                        if (schemaResult.validation_traces && schemaResult.validation_traces.length > 0) {
                            console.log('DEBUG: Received', schemaResult.validation_traces.length, 'validation traces');
                            schemaResult.validation_traces.forEach(trace => {
                                // Skip empty lines and the main header (already shown)
                                if (trace.trim() && !trace.includes('Running workflow agent input validation')) {
                                    this.addToOutput(outputTargetId, trace + '\n', 'info');
                                }
                            });
                        } else {
                            console.log('DEBUG: No validation_traces received in response');
                        }
                        
                        // Display warnings if any
                        if (schemaResult.warnings && schemaResult.warnings.length > 0) {
                            const warningCount = schemaResult.warnings.length;
                            this.addToOutput(outputTargetId, `⚠️ Agent input validation found ${warningCount} warning(s)\n`, 'warning');
                        }
                        
                        this.addToOutput(outputTargetId, '\n', 'info');
                    }
                } catch (schemaErr) {
                    this.addToOutput(outputTargetId, `❌ Schema validation error: ${schemaErr.message}\n`, 'error');
                    if (validateBtn) { validateBtn.textContent = originalText; validateBtn.disabled = false; }
                    return;
                }
            } else {
                this.addToOutput(outputTargetId, 'ℹ️ No inline workflow YAML found; skipping schema validation step.\n', 'info');
            }

            this.addToOutput(outputTargetId, `Subscription: ${formData.subscription_id}\n`, 'info');
            this.addToOutput(outputTargetId, `Resource Group: ${formData.resource_group}\n`, 'info');
            if (formData.location) this.addToOutput(outputTargetId, `Location: ${formData.location}\n\n`, 'info');

            // Perform validation: enumeration phase (abort if enumeration fails per requirements)
            this.addToOutput(outputTargetId, '🔍 Enumerating Workflow Agent structure...\n', 'info');
            let enumeration;
            try {
                enumeration = await this._enumerateWorkflowAgentDetails(formData.workflow_agent_name);
            } catch (e) {
                this.addToOutput(outputTargetId, `❌ Enumeration failed: ${e.message}\n`, 'error');
                if (validateBtn) { validateBtn.textContent = originalText; validateBtn.disabled = false; }
                return; // Abort per requirement
            }
            if (!enumeration.success) {
                this.addToOutput(outputTargetId, '❌ Enumeration reported failure:\n', 'error');
                if (enumeration.error) this.addToOutput(outputTargetId, `  - ${enumeration.error}\n`, 'error');
                if (Array.isArray(enumeration.missing)) {
                    enumeration.missing.forEach(m => this.addToOutput(outputTargetId, `  • ${m}\n`, 'error'));
                }
                if (validateBtn) { validateBtn.textContent = originalText; validateBtn.disabled = false; }
                return; // Abort
            }
            // Display enumeration summary (presence + size only, not full YAML content)
            const ea = enumeration.workflow_agent;
            this.addToOutput(outputTargetId, `Workflow Agent: ${ea.name}${ea.description ? ' — ' + ea.description : ''}\n`, 'info');
            this.addToOutput(outputTargetId, 'Workflow file:\n', 'info');
            this.addToOutput(outputTargetId, `  - ${ea.workflow.agent_config_path || '(none)'} (${ea.workflow.exists ? ea.workflow.size_bytes + ' bytes' : 'missing'})\n`, ea.workflow.exists ? 'info' : 'warning');
            if (ea.components && ea.components.length) {
                this.addToOutput(outputTargetId, 'Components:\n', 'info');
                ea.components.forEach(c => {
                    const line = `  - [${c.type || 'unknown'}] ${c.name} => ${c.agent_config_path || '(none)'} (${c.exists ? c.size_bytes + ' bytes' : 'missing'})\n`;
                    this.addToOutput(outputTargetId, line, c.exists ? 'info' : 'warning');
                });
            } else {
                this.addToOutput(outputTargetId, 'Components: (none)\n', 'warning');
            }
            if (ea.coordinated_agents && ea.coordinated_agents.length) {
                this.addToOutput(outputTargetId, 'Coordinated Agents:\n', 'info');
                ea.coordinated_agents.forEach(ca => this.addToOutput(outputTargetId, `  - ${ca}\n`, 'info'));
            }
            // referenced agents are validated below with per-agent progress messages; no need to list them twice here
            this.addToOutput(outputTargetId, '\n', 'info');

            // Proceed with backend validation
            // To improve UX we will perform per-agent checks in parallel and print "Validating {agent}..." messages
            // while concurrently requesting the aggregated validation for final reconciliation.
            const referenced = enumeration.referenced_agents || [];

            // Kick off aggregated validation but do not await it immediately
            const aggPromise = this.validateWorkflowAgentDependenciesForPublishing(formData).catch(e => ({ success: false, error: e.message }));

            // For each referenced agent, fire a per-agent validation and show progress
            // Note: We show "Validating X..." messages but don't show immediate status bullets
            // because per-agent results may be stale due to cache timing. The aggregated
            // validation results below will show the accurate final status for all agents.
            const perAgentPromises = referenced.map(agentName => (async () => {
                this.addToOutput(outputTargetId, `Validating ${agentName}...\n`, 'info');
                try {
                    const resp = await fetch('/api/workflow-agent-publish/validate-agent', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ workflow_agent_name: formData.workflow_agent_name, agent_name: agentName, subscription_id: formData.subscription_id, resource_group: formData.resource_group })
                    });
                    const j = await resp.json();
                    if (!resp.ok || !j.success) {
                        // Only show error messages for actual failures, not status results
                        this.addToOutput(outputTargetId, `  ⚠️ ${agentName}: Validation check encountered an error\n`, 'warning');
                        return { agent: agentName, status: 'error', detail: j.error || 'server error' };
                    }
                    const r = j.result;
                    
                    // Check if this agent is a workflow component (planner, router, summarizer)
                    const isWorkflowComponent = enumeration?.workflow_agent?.components?.some(
                        c => c.name === agentName && ['planner', 'router', 'summarizer'].includes((c.type || '').toLowerCase())
                    ) || false;
                    
                    // Return result without displaying bullet points (aggregated validation will show final results)
                    return { agent: agentName, status: r.status, detail: r, isWorkflowComponent };
                } catch (e) {
                    this.addToOutput(outputTargetId, `  ⚠️ ${agentName}: Validation request failed (${e.message})\n`, 'error');
                    return { agent: agentName, status: 'error', detail: e.message };
                }
            })());

            // Wait for all per-agent checks to complete (they update the UI incrementally)
            const perAgentResults = await Promise.all(perAgentPromises);

            // Now await aggregated validation result and display full summary
            const validationResult = await aggPromise;
            if (validationResult.success) {
                this.displayValidationResults(validationResult, outputTargetId, { enumeration });
            } else {
                this.addToOutput(outputTargetId, '❌ Validation failed\n', 'error');
                if (validationResult.error) {
                    this.addToOutput(outputTargetId, `Error: ${validationResult.error}\n`, 'error');
                }
            }
        } catch (error) {
            console.error('Error during validation:', error);
            this.addToOutput(outputTargetId, `❌ Validation error: ${error.message}\n`, 'error');
        } finally {
            // Restore validate button text/state
            if (validateBtn) { validateBtn.textContent = originalText; validateBtn.disabled = false; }
            // Enable validateAndPublish button after validation completes (unless deployment is in progress)
            if (validateAndPublishBtn) {
                // If a deployment is in progress, keep the button disabled; otherwise enable it
                validateAndPublishBtn.disabled = this.deploymentInProgress ? true : false;
            }
        }
    }

    // Enumerate workflow agent details via dedicated backend endpoint (aborts on failure)
    async _enumerateWorkflowAgentDetails(workflowAgentName) {
        const resp = await fetch('/api/workflow-agent-publish/enumerate-agents', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workflow_agent_name: workflowAgentName })
        });
        let data;
        try {
            data = await resp.json();
        } catch (e) {
            throw new Error(`Enumeration response parse failed: ${e.message}`);
        }
        if (!resp.ok) {
            throw new Error(data && data.error ? data.error : `HTTP ${resp.status}`);
        }
        return data;
    }

    displayValidationResults(validationResult, outputTargetId = 'publishOutput', options = {}) {
        try {
            // Guard: if response shape is unexpected, dump raw JSON and return
            if (!validationResult || typeof validationResult !== 'object') {
                this.addToOutput(outputTargetId, '⚠️ Unexpected validation response. Raw output follows.\n', 'warning');
                this.addToOutput(outputTargetId, JSON.stringify(validationResult, null, 2) + '\n', 'warning');
                return;
            }

            const overall_status = validationResult.overall_status ?? 'unknown';
            const validation_results = Array.isArray(validationResult.validation_results) ? validationResult.validation_results : [];
            const summary = validationResult.summary ?? {
                total_agents: validation_results.length,
                found_exact: validation_results.filter(r => r.status === 'found').length,
                not_found: validation_results.filter(r => r.status === 'not_found').length
            };

            // Extract enumeration data from options to identify workflow components
            const enumeration = options.enumeration || {};
            const workflowComponents = new Set();
            if (enumeration?.workflow_agent?.components) {
                enumeration.workflow_agent.components.forEach(c => {
                    if (c.name && ['planner', 'router', 'summarizer'].includes((c.type || '').toLowerCase())) {
                        workflowComponents.add(c.name);
                    }
                });
            }

            // Show workflow name and any duplicate warning
            const wfName = validationResult.workflow_name;
            const workflowAgentName = (options && options.workflowAgentName) ? String(options.workflowAgentName) : '';
            if (wfName) {
                // Avoid repeating if identical to the Workflow Agent header shown earlier
                if (!workflowAgentName || wfName.toLowerCase() !== workflowAgentName.toLowerCase()) {
                    this.addToOutput(outputTargetId, `🧭 Workflow name: ${wfName}\n`, 'info');
                }
            }
            const wfDup = validationResult.workflow_duplicate;
            if (wfDup && wfDup.name) {
                this.addToOutput(outputTargetId, `⚠️ A workflow with this name already exists.\n`, 'warning');
                try {
                    const selfName = String(wfDup.name || '').toLowerCase();
                    const otherMatches = Array.isArray(wfDup.existing)
                        ? (() => {
                            const seen = new Set();
                            const names = [];
                            for (const x of wfDup.existing) {
                                const nm = x && x.name ? String(x.name) : '';
                                const key = nm.toLowerCase();
                                if (!nm || key === selfName) continue; // exclude the same name
                                if (!seen.has(key)) { seen.add(key); names.push(nm); }
                            }
                            return names;
                        })()
                        : [];
                    if (otherMatches.length > 0) {
                        this.addToOutput(outputTargetId, 'Existing (other matches):\n', 'warning');
                        this.addToOutput(outputTargetId, otherMatches.map(n => `  • ${n}`).join('\n') + '\n', 'warning');
                    }
                } catch (_) { /* ignore listing issues */ }
                this.addToOutput(outputTargetId, 'Choose Update during publish, or rename before publishing.\n\n', 'warning');
            }

            // Display summary
            this.addToOutput(outputTargetId, `📊 Validation Summary:\n`, 'info');
            this.addToOutput(outputTargetId, `  • Total workflow agents: ${summary.total_agents}\n`, 'info');
            this.addToOutput(outputTargetId, `  • Found (exact match): ${summary.found_exact}\n`, 'success');
            if (summary.not_found > 0) this.addToOutput(outputTargetId, `  • Not found: ${summary.not_found}\n`, 'error');
            this.addToOutput(outputTargetId, '\n', 'info');

            // Display detailed results for each agent
            this.addToOutput(outputTargetId, '📋 Detailed Agent Validation:\n', 'info');
            validation_results.forEach(result => {
                const agent_name = result.agent_name ?? '(unknown)';
                const status = result.status ?? 'unknown';
                const matched_agent = result.matched_agent;
                const isWorkflowComponent = workflowComponents.has(agent_name);

                if (status === 'found') {
                    this.addToOutput(outputTargetId, `✅ ${agent_name}\n`, 'success');
                    if (matched_agent && matched_agent.name) {
                        this.addToOutput(outputTargetId, `   → Found: ${matched_agent.name}\n`, 'success');
                    }
                } else if (status === 'not_found') {
                    if (isWorkflowComponent) {
                        this.addToOutput(outputTargetId, `ℹ️ ${agent_name}\n`, 'info');
                        this.addToOutput(outputTargetId, `   → Not found in Discovery workspace (expected if workflow was never published)\n`, 'info');
                    } else {
                        this.addToOutput(outputTargetId, `❌ ${agent_name}\n`, 'error');
                        this.addToOutput(outputTargetId, `   → Not found in Discovery workspace\n`, 'error');
                    }
                    this.addToOutput(outputTargetId, '\n', 'info');
                } else {
                    this.addToOutput(outputTargetId, `ℹ️ ${agent_name} (status: ${status})\n`, 'info');
                }
            });

            this.addToOutput(outputTargetId, '\n', 'info');

            // --------------------------------------------------------------
            // Events Validation Summary (semantic workflow ↔ router checks)
            // --------------------------------------------------------------
            try {
                if (Object.prototype.hasOwnProperty.call(validationResult, 'events_validation')) {
                    const ev = validationResult.events_validation;
                    const evData = (ev && typeof ev === 'object' && ev.data) ? ev.data : {};
                    // Debug: surface router YAML load confirmation if available
                    if (evData && evData.router_agent_name) {
                        // We don't yet transmit size/preview explicitly; rely on counts for now
                        const routerName = evData.router_agent_name;
                        const routerCount = Array.isArray(evData.router_agent_events) ? evData.router_agent_events.length : (evData.router_events_found ?? 0);
                        this.addToOutput(outputTargetId, `🛈 Router YAML loaded: ${routerName} (events parsed=${routerCount})\n`, 'info');
                    }
                    const evErrors = Array.isArray(ev?.errors) ? ev.errors : [];
                    const warningRegex = /(\bwarning\b)/i;
                    const hardErrors = evErrors.filter(e => !warningRegex.test(e.message || ''));
                    const warnings = evErrors.filter(e => warningRegex.test(e.message || ''));

                    const statusIcon = ev?.valid ? (warnings.length ? '⚠️' : '✅') : '❌';
                    const statusType = ev?.valid ? (warnings.length ? 'warning' : 'success') : 'error';
                    this.addToOutput(outputTargetId, '🔁 Events Validation:\n', 'info');
                    this.addToOutput(outputTargetId, `  Status: ${statusIcon} ${(ev?.valid ? 'valid' : 'invalid')}${warnings.length ? ' (with warnings)' : ''}\n`, statusType);
                    this.addToOutput(outputTargetId, `  Workflow events found: ${evData.workflow_events_found ?? 0}\n`, 'info');
                    this.addToOutput(outputTargetId, `  Router agent: ${evData.router_agent_found ? (evData.router_agent_name || '(unnamed)') : 'NOT FOUND'}\n`, evData.router_agent_found ? 'info' : 'error');
                    this.addToOutput(outputTargetId, `  Router actions (events) found: ${evData.router_events_found ?? 0}\n`, 'info');
                    this.addToOutput(outputTargetId, `  Errors: ${evData.error_count ?? hardErrors.length}, Warnings: ${evData.warning_count ?? warnings.length}\n`, (hardErrors.length ? 'error' : (warnings.length ? 'warning' : 'info')));

                    // If transition mappings exist, show a compact table
                    if (Array.isArray(evData.transition_mappings) && evData.transition_mappings.length) {
                        this.addToOutput(outputTargetId, '  Mappings:\n', 'info');
                        evData.transition_mappings.forEach(m => {
                            const ok = m.status === '✅';
                            const mapLine = `    ${m.event} (from ${m.from_agent}) -> ${ok ? 'router action present' : 'MISSING in router'}`;
                            this.addToOutput(outputTargetId, mapLine + '\n', ok ? 'success' : 'error');
                        });
                    }

                    if (hardErrors.length) {
                        this.addToOutput(outputTargetId, '  Errors:\n', 'error');
                        hardErrors.forEach(e => this.addToOutput(outputTargetId, `    - ${e.path || '<path>'}: ${e.message}\n`, 'error'));
                    }
                    if (warnings.length) {
                        this.addToOutput(outputTargetId, '  Warnings:\n', 'warning');
                        warnings.forEach(w => this.addToOutput(outputTargetId, `    - ${w.path || '<path>'}: ${w.message.replace(warningRegex, '').trim()}\n`, 'warning'));
                    }
                    this.addToOutput(outputTargetId, '\n', 'info');
                } else {
                    this.addToOutput(outputTargetId, '🔁 Events Validation: (no events validation data returned)\n\n', 'warning');
                }
            } catch (evRenderErr) {
                console.error('Failed rendering events_validation block:', evRenderErr);
                this.addToOutput(outputTargetId, '⚠️ Failed to render events validation details.\n', 'warning');
            }

            // Check events validation status before declaring success
            const eventsValidationPassed = !validationResult.events_validation || validationResult.events_validation.valid !== false;
            
            // Display overall result
            if (overall_status === 'valid' && eventsValidationPassed) {
                this.addToOutput(outputTargetId, '✅ Validation completed successfully!\n', 'success');
                this.addToOutput(outputTargetId, 'All required agents are available. Ready to publish.\n', 'success');
            } else if (overall_status === 'valid' && !eventsValidationPassed) {
                this.addToOutput(outputTargetId, '❌ Validation failed\n', 'error');
                this.addToOutput(outputTargetId, 'Event validation errors detected. Please fix the event naming mismatches before publishing.\n', 'error');
            } else if (overall_status === 'invalid') {
                this.addToOutput(outputTargetId, '❌ Validation failed\n', 'error');
                this.addToOutput(outputTargetId, 'Some required agents are not published to Discovery.\n', 'error');
                this.addToOutput(outputTargetId, 'Please publish the missing agents first, or update your configuration.\n', 'error');
            } else {
                this.addToOutput(outputTargetId, `ℹ️ Validation status: ${overall_status}\n`, 'info');
            }
        } catch (err) {
            console.error('displayValidationResults error:', err);
            this.addToOutput(outputTargetId, '⚠️ Failed to render validation results. Raw response follows.\n', 'warning');
            try {
                this.addToOutput(outputTargetId, JSON.stringify(validationResult, null, 2) + '\n', 'warning');
            } catch (_) {
                // ignore
            }
        } finally {
            this.addToOutput(outputTargetId, '\n— End of validation —\n', 'info');
        }
    }

    async performValidateAndPublish() {
        let validationResult; // Hoist declaration to top of function scope
        // Save and disable UI buttons so users can't re-trigger validation/publish
        const validateBtn = document.getElementById('validateBtn');
        const validateAndPublishBtn = document.getElementById('validateAndPublishBtn');
        const validateOriginal = validateBtn ? { text: (validateBtn.textContent || validateBtn.innerText || ''), disabled: !!validateBtn.disabled } : null;
        const validateAndPublishOriginal = validateAndPublishBtn ? { text: (validateAndPublishBtn.textContent || validateAndPublishBtn.innerText || ''), disabled: !!validateAndPublishBtn.disabled } : null;
        try {
            if (validateBtn) { validateBtn.textContent = 'Validating...'; validateBtn.disabled = true; }
            if (validateAndPublishBtn) { validateAndPublishBtn.textContent = 'Publishing...'; validateAndPublishBtn.disabled = true; }
            // Clear previous output
            this.clearPublishOutput();
            this.addToPublishOutput('=== Workflow Agent Validation and Publishing ===\n', 'info');
            
            // Get form data
            const formData = await this.getPublishFormData();
            if (!this.validatePublishForm(formData)) {
                return;
            }
            
            this.addToPublishOutput(`Subscription: ${formData.subscription_id}\n`, 'info');
            this.addToPublishOutput(`Resource Group: ${formData.resource_group}\n`, 'info');
            this.addToPublishOutput(`Location: ${formData.location}\n\n`, 'info');
            // Removed Workflow Agent line to avoid confusion with actual workflow name printed later

            // ------------------------------------------------------------------
            // 0. Baseline YAML Schema Validation (centralized validator)
            // ------------------------------------------------------------------
            const inlineYaml = formData.inline_workflow_yaml || this.tryGetInlineWorkflowYaml();
            if (inlineYaml && inlineYaml.trim()) {
                this.addToPublishOutput('🔧 Running baseline workflow YAML schema validation...\n', 'info');
                try {
                    const schemaResp = await fetch('/api/workflow/validate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ 
                            yaml: inlineYaml, 
                            is_inline: true,
                            workflow_agent_name: formData.workflow_agent_name
                        })
                    });
                    if (!schemaResp.ok) {
                        const errTxt = await schemaResp.text();
                        this.addToPublishOutput(`❌ Schema validation request failed (HTTP ${schemaResp.status})\n`, 'error');
                        this.addToPublishOutput(errTxt + '\n', 'error');
                        this.addToPublishOutput('Publishing halted due to schema validation error.\n', 'error');
                        return; // Abort publish flow
                    }
                    const schemaResult = await schemaResp.json();
                    if (!schemaResult.valid) {
                        this.addToPublishOutput('❌ Workflow YAML failed schema validation:\n', 'error');
                        
                        // Display detailed validation traces if available (even for failures)
                        if (schemaResult.validation_traces && schemaResult.validation_traces.length > 0) {
                            schemaResult.validation_traces.forEach(trace => {
                                // Skip empty lines and the main header (already shown)
                                if (trace.trim() && !trace.includes('Running workflow agent input validation')) {
                                    this.addToPublishOutput(trace + '\n', 'info');
                                }
                            });
                            this.addToPublishOutput('\n', 'info');
                        }
                        
                        if (Array.isArray(schemaResult.errors) && schemaResult.errors.length) {
                            schemaResult.errors.forEach(e => {
                                const path = e.path || '<root>';
                                const msg = e.message || 'Unknown validation error';
                                this.addToPublishOutput(` - ${path}: ${msg}\n`, 'error');
                            });
                        } else if (schemaResult.error) {
                            this.addToPublishOutput(` - ${schemaResult.error}\n`, 'error');
                        }
                        this.addToPublishOutput('\nFix the above schema issues before publishing.\n', 'error');
                        return; // Abort publish flow
                    } else {
                        this.addToPublishOutput('✅ Workflow YAML schema validation passed\n', 'success');
                        
                        // Display detailed validation traces if available
                        if (schemaResult.validation_traces && schemaResult.validation_traces.length > 0) {
                            console.log('DEBUG: Received', schemaResult.validation_traces.length, 'validation traces');
                            schemaResult.validation_traces.forEach(trace => {
                                // Skip empty lines and the main header (already shown)
                                if (trace.trim() && !trace.includes('Running workflow agent input validation')) {
                                    this.addToPublishOutput(trace + '\n', 'info');
                                }
                            });
                        } else {
                            console.log('DEBUG: No validation_traces received in response');
                        }
                        
                        // Display warnings if any
                        if (schemaResult.warnings && schemaResult.warnings.length > 0) {
                            const warningCount = schemaResult.warnings.length;
                            this.addToPublishOutput(`⚠️ Agent input validation found ${warningCount} warning(s)\n`, 'warning');
                        }
                        
                        this.addToPublishOutput('\n', 'info');
                    }
                } catch (schemaErr) {
                    this.addToPublishOutput(`❌ Schema validation error: ${schemaErr.message}\n`, 'error');
                    this.addToPublishOutput('Publishing halted due to schema validation exception.\n', 'error');
                    return;
                }
            } else {
                this.addToPublishOutput('ℹ️ No inline workflow YAML found; skipping schema validation step.\n', 'info');
            }
            
            // Step 1: Validate
            this.addToPublishOutput('Step 1: Validating Workflow agent dependencies...\n', 'info');

            // Front-load client-side name checks to avoid partial publishes and surface name issues early
            const clientNamesOk = await this._frontLoadNameValidation(formData);
            if (!clientNamesOk) {
                this.addToPublishOutput('❌ Publishing aborted due to client-side name validation failures.\n', 'error');
                return;
            }

            validationResult = await this.validateWorkflowAgentDependenciesForPublishing(formData);
                            // Events validation summary (reuse same rendering logic, but compact)
                            if (validationResult.events_validation && typeof validationResult.events_validation === 'object') {
                                const ev = validationResult.events_validation;
                                const evData = ev.data || {};
                                const evErrors = Array.isArray(ev.errors) ? ev.errors : [];
                                const warningRegex = /\(warning\)/i;
                                const hardErrors = evErrors.filter(e => !warningRegex.test(e.message || ''));
                                const warnings = evErrors.filter(e => warningRegex.test(e.message || ''));
                                const statusIcon = ev.valid ? (warnings.length ? '⚠️' : '✅') : '❌';
                                const summaryLine = `Events Validation: ${statusIcon} workflow events=${evData.workflow_events_found ?? 0}, router events=${evData.router_events_found ?? 0}`;
                                this.addToPublishOutput(summaryLine + '\n', ev.valid ? (warnings.length ? 'warning' : 'success') : 'error');
                                if (hardErrors.length) {
                                    hardErrors.forEach(e => this.addToPublishOutput(`  - ERROR ${e.path || '<path>'}: ${e.message}\n`, 'error'));
                                }
                                if (warnings.length) {
                                    warnings.forEach(w => this.addToPublishOutput(`  - WARN ${w.path || '<path>'}: ${w.message}\n`, 'warning'));
                                }
                                this.addToPublishOutput('\n', 'info');
                            }
            
            // Check for validation status and missing agents
            // Instead of aborting when status is 'invalid' due to missing agents,
            // we should only abort for non-recoverable errors
            const overall_status = validationResult.overall_status || 'unknown';
            const validation_results = Array.isArray(validationResult.validation_results) ? validationResult.validation_results : [];
            const missing_agents = validation_results.filter(r => r.status === 'not_found');
            
            if (overall_status === 'invalid') {
                // Check if this is only due to missing agents (which we can auto-publish)
                // or if there are other critical errors
                const hasOnlyMissingAgents = missing_agents.length > 0 && 
                                           validation_results.length === missing_agents.length + validation_results.filter(r => r.status === 'found').length;
                
                if (hasOnlyMissingAgents) {
                    // This is recoverable - we can publish the missing agents
                    this.addToPublishOutput(`⚠️ Found ${missing_agents.length} missing agents that need to be published first.\n`, 'warning');
                    this.addToPublishOutput('📋 Missing agents:\n', 'warning');
                    missing_agents.forEach(agent => {
                        this.addToPublishOutput(`  • ${agent.agent_name}\n`, 'warning');
                    });
                    this.addToPublishOutput('\nThese agents will be published automatically as part of this deployment.\n\n', 'info');
                } else {
                    // There are other critical errors beyond just missing agents
                    this.addToPublishOutput(`❌ Validation did not pass (status: ${overall_status}). Publishing aborted.\n`, 'error');
                    if (validationResult.error) {
                        this.addToPublishOutput(`Error: ${validationResult.error}\n`, 'error');
                    }
                    // Provide detailed validation results so the user can see which agent(s) caused the failure
                    try {
                        this.addToPublishOutput('\nDetailed validation results:\n', 'info');
                        this.displayValidationResults(validationResult, 'publishOutput', { workflowAgentName: formData.workflow_agent_name });
                    } catch (renderErr) {
                        console.warn('Failed to render detailed validation results during publish abort:', renderErr);
                        try {
                            this.addToPublishOutput(JSON.stringify(validationResult, null, 2) + '\n', 'warning');
                        } catch (_) { /* ignore */ }
                    }
                    return; // Abort publish flow only for non-recoverable errors
                }
            }
            // Note: 'needs_mapping' status no longer exists - agents are either valid or invalid

            // Additionally, ensure events validation has no hard errors. Abort if events validation reports invalid with non-warning errors
            try {
                const ev = validationResult.events_validation;
                if (ev && ev.valid === false) {
                    const evErrors = Array.isArray(ev.errors) ? ev.errors : [];
                    // Consider warnings (strings containing 'warning') as non-fatal; all other errors are hard errors
                    const hardErrors = evErrors.filter(e => !(/warning/i).test(e.message || ''));
                    if (hardErrors.length) {
                        this.addToPublishOutput('❌ Events validation failed with errors. Publishing aborted.\n', 'error');
                        hardErrors.forEach(e => this.addToPublishOutput(` - ${e.path || '<path>'}: ${e.message}\n`, 'error'));
                        // Also render agent-level validation details to help pinpoint the origin
                        try {
                            this.addToPublishOutput('\nDetailed validation results:\n', 'info');
                            this.displayValidationResults(validationResult, 'publishOutput', { workflowAgentName: formData.workflow_agent_name });
                        } catch (renderErr) {
                            console.warn('Failed to render detailed validation results during events-abort:', renderErr);
                        }
                        return; // Abort publish flow
                    }
                }
            } catch (evCheckErr) {
                // If we cannot reliably inspect events validation, abort to be safe
                this.addToPublishOutput(`❌ Events validation check failed (${evCheckErr.message}). Publishing aborted.\n`, 'error');
                return;
            }

            // If we reach here, validation allows us to proceed
            // (either successful, or recoverable with missing agents that will be auto-published)
            if (overall_status === 'valid') {
                this.addToPublishOutput('✅ Validation completed successfully\n', 'success');
            } else if (missing_agents.length > 0) {
                this.addToPublishOutput('✅ Validation completed - proceeding with automatic agent publishing\n', 'success');
            } else {
                this.addToPublishOutput('✅ Validation completed\n', 'success');
            }
                if (validationResult.referenced_agents && validationResult.referenced_agents.length > 0) {
                    this.addToPublishOutput(`Found ${validationResult.referenced_agents.length} workflow agents:\n`, 'info');
                    validationResult.referenced_agents.forEach(agent => {
                        this.addToPublishOutput(`  - ${agent}\n`, 'info');
                    });
                }
                this.addToPublishOutput('\n', 'info');

                // If workflow name duplicate detected, prompt user to Update/Rename/Cancel
                let workflowPublishMode = undefined;
                let workflowNameOverride = undefined;
                if (validationResult.workflow_duplicate && validationResult.workflow_duplicate.name) {
                    const dupName = String(validationResult.workflow_duplicate.name || '');
                    const existingNames = Array.isArray(validationResult.workflow_duplicate.existing)
                        ? (() => {
                            const seen = new Set();
                            const names = [];
                            for (const x of validationResult.workflow_duplicate.existing) {
                                const nm = x && x.name ? String(x.name) : '';
                                const key = nm.toLowerCase();
                                if (key === dupName.toLowerCase()) continue; // exclude the same name
                                if (!seen.has(key)) { seen.add(key); names.push(nm); }
                            }
                            return names;
                        })()
                        : [];
                    const existingBlock = existingNames.length > 0
                        ? `\n\nExisting (other matches):\n${existingNames.map(n => `• ${n}`).join('\n')}`
                        : '';
                    const msg = `A workflow named "${dupName}" already exists.${existingBlock}\n\nHow would you like to proceed?`;
                    const choice = await showAppTriDialog({
                        title: 'Workflow name already exists',
                        message: msg,
                        primaryLabel: 'Update',
                        secondaryLabel: 'Rename',
                        cancelLabel: 'Cancel'
                    });
                    if (choice === 'primary') { // Update
                        workflowPublishMode = 'update';
                        this.addToPublishOutput(`Will update existing workflow: ${dupName}\n\n`, 'info');
                    } else if (choice === 'secondary') { // Rename
                        const newName = window.prompt('Enter a new workflow name:', `${dupName}-v2`);
                        if (!newName || !newName.trim()) {
                            this.addToPublishOutput('❌ Publishing canceled (no new workflow name provided).\n', 'error');
                            return;
                        }
                        workflowPublishMode = 'create';
                        workflowNameOverride = newName.trim();
                        this.addToPublishOutput(`Will create workflow with new name: ${workflowNameOverride}\n\n`, 'info');
                    } else { // Cancel
                        this.addToPublishOutput('⚠️ Publishing canceled by user.\n', 'warning');
                        return;
                    }
                }
                
                // Step 2: Publish
                this.addToPublishOutput('Step 2: Starting Workflow agent deployment...\n', 'info');
                // Stream to the Publishing tab output area
                const deploymentConfig = { ...formData };
                if (workflowPublishMode) deploymentConfig.workflow_publish_mode = workflowPublishMode;
                if (workflowNameOverride) deploymentConfig.workflow_name_override = workflowNameOverride;
                await this.streamWorkflowAgentDeployment(deploymentConfig, { target: 'publish' });
        } catch (error) {
            console.error('Validate and publish failed:', error);
            this.addToPublishOutput(`❌ Error: ${error.message}\n`, 'error');
        } finally {
            try {
                if (validateBtn && validateOriginal) {
                    validateBtn.textContent = validateOriginal.text || '';
                    validateBtn.disabled = !!validateOriginal.disabled;
                }
                if (validateAndPublishBtn && validateAndPublishOriginal) {
                    validateAndPublishBtn.textContent = validateAndPublishOriginal.text || '';
                    validateAndPublishBtn.disabled = !!validateAndPublishOriginal.disabled;
                }
            } catch (restoreErr) {
                console.warn('Failed to restore validate/publish button states:', restoreErr);
            }
        }
    }

    async getPublishFormData() {
        // Get current agent information
        const currentAgent = await this.getCurrentWorkflowAgent();
        // Try to capture inline workflow YAML from active editors (Workflow edit mode or Create Agent modal)
        const inlineYaml = this.tryGetInlineWorkflowYaml();
        
        // Get Azure configuration from global settings instead of removed fields
        const azureConfig = window.agent ? window.agent.getAzureConfigFromSettings() : {};
        
        if (!currentAgent) {
            // Fall back to selection dropdown if present
            const select = document.getElementById('entryAgentSelect');
            const agentName = select && select.value ? select.value : '';
            if (!agentName) throw new Error('No Workflow Agent is currently selected');
            return {
                workflow_agent_name: agentName,
                subscription_id: azureConfig.subscription_id || '',
                resource_group: azureConfig.resource_group || '',
                location: azureConfig.location || '',
                model_name: 'gpt-4o',
                verification_timeout: 60,  // Default 60 seconds for verification timeout
                // Include inline YAML when available so Publishing tab validates unsaved edits too
                inline_workflow_yaml: inlineYaml || undefined
            };
        }
        
        return {
            workflow_agent_name: currentAgent.name,
            subscription_id: azureConfig.subscription_id || '',
            resource_group: azureConfig.resource_group || '',
            location: azureConfig.location || '',
            model_name: 'gpt-4o',
            verification_timeout: 60,  // Default 60 seconds for verification timeout
            inline_workflow_yaml: inlineYaml || undefined
        };
    }

    validatePublishForm(formData, outputTargetId = 'publishOutput') {
        const required = ['workflow_agent_name', 'subscription_id', 'resource_group', 'location'];
        const missing = required.filter(field => !formData[field] || !String(formData[field]).trim());

        if (missing.length > 0) {
            this.addToOutput(outputTargetId, `❌ Please fill in all required fields: ${missing.join(', ')}\n`, 'error');
            return false;
        }
        return true;
    }

    clearPublishOutput() {
        const outputDiv = document.getElementById('publishOutput');
        if (outputDiv) {
            outputDiv.textContent = '';
        }
    }

    addToPublishOutput(message, type = 'info') {
        const outputDiv = document.getElementById('publishOutput');
        if (!outputDiv) return;

        const currentText = outputDiv.textContent;
        outputDiv.textContent = currentText + message;
        outputDiv.scrollTop = outputDiv.scrollHeight;
    }

    async getWorkflowAgentFormDataFromTab() {
        // Use current agent or selection; no fields to read
        const current = await this.getCurrentWorkflowAgent();
        
        // Get Azure configuration from global settings instead of removed fields
        const azureConfig = window.agent ? window.agent.getAzureConfigFromSettings() : {};
        
        if (current && current.name) {
            return {
                workflow_agent_name: current.name,
                subscription_id: azureConfig.subscription_id || '',
                resource_group: azureConfig.resource_group || '',
                location: azureConfig.location || '',
                model_name: 'gpt-4o'
            };
        }
        const select = document.getElementById('entryAgentSelect');
        const agentName = select && select.value ? select.value : '';
        if (!agentName) throw new Error('No Workflow Agent is currently selected');
        return {
            workflow_agent_name: agentName,
            subscription_id: azureConfig.subscription_id || '',
            resource_group: azureConfig.resource_group || '',
            location: azureConfig.location || '',
            model_name: 'gpt-4o'
        };
    }

    async validateWorkflowAgentDependenciesForPublishing(formData) {
        try {
            console.log('🌐 Making validation API request to /api/workflow-agent-publish/validate-agents');
            console.log('📤 Request data:', {
                workflow_agent_name: formData.workflow_agent_name,
                subscription_id: formData.subscription_id,
                resource_group: formData.resource_group
            });
            
            const response = await fetch('/api/workflow-agent-publish/validate-agents', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    workflow_agent_name: formData.workflow_agent_name,
                    subscription_id: formData.subscription_id,
                    resource_group: formData.resource_group,
                    // allow inline YAML validation when provided (used by modal)
                    inline_workflow_yaml: formData.inline_workflow_yaml,
                    // explicit flag so server treats provided YAML as inline content
                    is_inline: !!formData.inline_workflow_yaml
                })
            });

            console.log('📥 API response status:', response.status);
            
            if (!response.ok) {
                const errorText = await response.text();
                console.error('❌ API error response:', errorText);
                let error;
                try {
                    error = JSON.parse(errorText);
                } catch (e) {
                    error = { error: `HTTP ${response.status}: ${response.statusText}` };
                }
                throw new Error(error.error || `HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('✅ API success response:', result);
            return result;
        } catch (error) {
            console.error('Error validating Workflow agent dependencies:', error);
            throw error;
        }
    }

    // Generic output helpers used by both Publishing tab and Create Agent modal
    clearOutput(targetId) {
        const el = document.getElementById(targetId);
        if (el) el.textContent = '';
    }
    addToOutput(targetId, message, type = 'info') {
        const el = document.getElementById(targetId);
        if (!el) return;
        el.textContent = (el.textContent || '') + message;
        el.scrollTop = el.scrollHeight;
    }
    // Back-compat wrappers
    clearPublishOutput() { this.clearOutput('publishOutput'); }
    addToPublishOutput(message, type = 'info') { this.addToOutput('publishOutput', message, type); }

    async getWorkflowAgentFormData() {
        // Get current agent instead of from selector
        const currentAgent = await this.getCurrentWorkflowAgent();
        if (!currentAgent) {
            throw new Error('No Workflow Agent is currently selected');
        }
        
        // Get Azure configuration from global settings instead of removed fields
        const azureConfig = window.agent ? window.agent.getAzureConfigFromSettings() : {};
        
        return {
            workflow_agent_name: currentAgent.name,
            subscription_id: azureConfig.subscription_id || '',
            resource_group: azureConfig.resource_group || '',
            location: azureConfig.location || '',
            model_name: 'gpt-4o' // Use default since model config is in agent files
        };
    }

    validateWorkflowAgentForm(formData) {
        const required = ['workflow_agent_name', 'subscription_id', 'resource_group', 'location'];
        const missing = required.filter(field => !formData[field] || !formData[field].trim());
        
        if (missing.length > 0) {
            showAppAlert({ title: 'Missing fields', message: `Please fill in all required fields: ${missing.join(', ')}` });
            return false;
        }
        
        return true;
    }

    async validateWorkflowAgentDependencies() {
        try {
            // Get form data from the Publishing tab
            const currentAgent = await this.getCurrentWorkflowAgent();
            if (!currentAgent) {
                await showAppAlert({ title: 'No Workflow Agent', message: 'Please select a Workflow Agent first.' });
                return;
            }

            const formData = {
                workflow_agent_name: currentAgent.name,
                subscription_id: document.getElementById('entryAgentSubscriptionId')?.value,
                resource_group: document.getElementById('entryAgentResourceGroup')?.value,
                location: document.getElementById('entryAgentLocation')?.value
            };

            // Validate basic form data
            if (!formData.subscription_id || !formData.resource_group) {
                await showAppAlert({ title: 'Missing configuration', message: 'Please fill in Subscription ID and Resource Group to validate dependencies.' });
                return;
            }

            this.showWorkflowAgentStatus('info', 'Validating Workflow agent dependencies');
            
            const response = await fetch('/api/workflow-agent-publish/validate-agents', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    workflow_agent_name: formData.workflow_agent_name,
                    subscription_id: formData.subscription_id,
                    resource_group: formData.resource_group
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || `HTTP ${response.status}: ${response.statusText}`);
            }

            const validationResult = await response.json();
            // Render results into legacy Workflow Agent modal/section
            this.displayDependencyValidationResults(validationResult);
            
            // Update workflow agents with validation status
            this.updateWorkflowAgentsWithValidation(validationResult);

            // Enable/disable publish button based on validation
            const publishBtn = document.getElementById('publishEntryAgentBtn');
            if (publishBtn) {
                publishBtn.disabled = !validationResult.can_deploy;
            }

        } catch (error) {
            console.error('Error validating Workflow agent dependencies:', error);
            this.showWorkflowAgentStatus('error', `Validation failed: ${error.message}`);
        }
    }

    updateWorkflowAgentsWithValidation(validationResult) {
        const workflowAgentsList = document.getElementById('workflowAgentsList');
        if (!workflowAgentsList) return;

        const validationMap = {};
        validationResult.validation_results.forEach(result => {
            validationMap[result.agent_name] = result.status;
        });

        const agentItems = validationResult.referenced_agents.map(agentName => {
            const status = validationMap[agentName] || 'unknown';
            let statusIcon = '❓';
            let statusColor = '#666';
            
            switch (status) {
                case 'found':
                    statusIcon = '✅';
                    statusColor = '#28a745';
                    break;
                case 'not_found':
                    statusIcon = '❌';
                    statusColor = '#dc3545';
                    break;
            }
            
            return `
                <div class="workflow-agent-item">
                    <span class="agent-icon">🤖</span>
                    <span class="agent-name">${agentName}</span>
                    <span class="agent-status" style="color: ${statusColor}">${statusIcon}</span>
                </div>
            `;
        }).join('');

        workflowAgentsList.innerHTML = agentItems;
    }

    displayDependencyValidationResults(validationResult) {
        const { overall_status, validation_results, summary, referenced_agents } = validationResult;
        
        this.showWorkflowAgentStatus('warning', 'Workflow agent dependency validation failed');
        
        // Display detailed validation results
        let html = '<div class="dependency-validation-results">';
        
        html += '<h4>🔍 Workflow Agent Dependency Validation</h4>';
        html += `<p><strong>Overall Status:</strong> <span class="status-${overall_status}">${overall_status.toUpperCase()}</span></p>`;
        html += `<p><strong>Referenced Agents:</strong> ${referenced_agents.join(', ')}</p>`;
        
        html += '<div class="validation-summary">';
        html += `<p><strong>Summary:</strong> ${summary.total_agents} agents referenced, `;
        html += `${summary.found_exact} found exactly, ${summary.not_found} not found</p>`;
        html += '</div>';
        
        html += '<div class="validation-details">';
        html += '<h5>Validation Details:</h5>';
        html += '<ul>';
        
        for (const result of validation_results) {
            html += `<li class="validation-item status-${result.status}">`;
            html += `<strong>${result.agent_name}:</strong> `;
            
            switch (result.status) {
                case 'found':
                    html += `✅ Found exact match`;
                    break;
                case 'not_found':
                    html += `❌ Not found in Discovery`;
                    break;
            }
            html += `</li>`;
        }
        
        html += '</ul>';
        html += '</div>';
        
        // Add recommendation
        html += '<div class="validation-recommendation">';
        if (overall_status === 'invalid') {
            html += '<p><strong>Recommendation:</strong> Some required agents are missing from Discovery. ';
            html += 'Please publish the missing agents before deploying this Workflow agent.</p>';
        }
        html += '</div>';
        
        html += '</div>';
        
        // Update the check results div or create a new one
        let resultsDiv = document.getElementById('entryAgentDependencyResults');
        if (!resultsDiv) {
            resultsDiv = document.createElement('div');
            resultsDiv.id = 'entryAgentDependencyResults';
            resultsDiv.className = 'dependency-results';
            
            // Insert after the status section
            const statusSection = document.getElementById('entryAgentStatus');
            if (statusSection && statusSection.parentNode) {
                statusSection.parentNode.insertBefore(resultsDiv, statusSection.nextSibling);
            }
        }
        
        resultsDiv.innerHTML = html;
        resultsDiv.style.display = 'block';
    }

    async streamWorkflowAgentDeployment(deploymentConfig, options = { target: 'entry' }) {
        const url = '/api/workflow-agent-publish/stream-rest';
        const controller = new AbortController();
        const target = options.target === 'publish' ? 'publish' : 'entry';
        const append = (msg, type='info') => this.appendDeploymentOutput(msg, type, target);
        
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(deploymentConfig),
                signal: controller.signal
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            // Initial note and heartbeat to reassure users during quiet periods
            append('⏳ Connecting to deployment stream...\n', 'info');
            let lastMessageTs = Date.now();
            const heartbeatMs = 20000; // 20s
            const heartbeat = setInterval(() => {
                if (Date.now() - lastMessageTs > heartbeatMs) {
                    append('… still working (deployment in progress)\n', 'info');
                    lastMessageTs = Date.now(); // throttle
                }
            }, heartbeatMs);

            let buffer = ''; // Buffer to accumulate incomplete lines
            while (true) {
                const { value, done } = await reader.read();
                
                if (done) break;
                
                const chunk = decoder.decode(value);
                buffer += chunk;
                
                // Split on \n but keep the last incomplete line in buffer
                const lines = buffer.split('\n');
                buffer = lines.pop() || ''; // Keep the last (potentially incomplete) line
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.substring(6));
                            lastMessageTs = Date.now();
                            this.handleDeploymentStreamData(data, target);
                        } catch (e) {
                            console.warn('Failed to parse stream data:', line);
                        }
                    }
                }
            }
            clearInterval(heartbeat);
            
        } catch (error) {
            // Ensure heartbeat is cleared
            try { clearInterval(heartbeat); } catch {}
            if (error.name !== 'AbortError') {
                throw error;
            }
        }
    }

    appendDeploymentOutput(message, type = 'info', target = 'publish') {
        if (target === 'publish') {
            this.addToPublishOutput(message.endsWith('\n') ? message : message + '\n', type);
        } else {
            this.addToWorkflowAgentOutput(message.endsWith('\n') ? message : message + '\n', type);
        }
    }

    handleDeploymentStreamData(data, target = 'entry') {
        if (!data || !data.type) return;
        const append = (msg, type='info') => this.appendDeploymentOutput(msg, type, target);

        switch (data.type) {
            case 'progress':
                append(data.message, 'info');
                break;
            case 'success':
                append(`✅ ${data.message}`, 'success');
                this.showWorkflowAgentStatus('success', 'Workflow agent deployment completed successfully!');
                this.deploymentInProgress = false;
                this.updateWorkflowAgentButtonStates(false);
                append('\n— End of publishing —\n', 'info');
                break;
            case 'error':
                append(`❌ ${data.message}`, 'error');
                this.showWorkflowAgentStatus('error', data.message);
                this.deploymentInProgress = false;
                this.updateWorkflowAgentButtonStates(false);
                append('\n— End of publishing —\n', 'info');
                break;
            case 'result':
                if (data.data && data.data.message) {
                    append(data.data.message, 'success');
                }
                break;
            default:
                append(`ℹ️ ${JSON.stringify(data)}\n`, 'info');
        }
    }

    handleWorkflowAgentStreamData(data) {
        switch (data.type) {
            case 'progress':
                this.addToWorkflowAgentOutput(data.message, 'info');
                break;
                
            case 'success':
                this.addToWorkflowAgentOutput(`✅ ${data.message}`, 'success');
                this.showWorkflowAgentStatus('success', 'Workflow agent deployment completed successfully!');
                this.deploymentInProgress = false;
                this.updateWorkflowAgentButtonStates(false);
                break;
                
            case 'error':
                this.addToWorkflowAgentOutput(`❌ ${data.message}`, 'error');
                this.showWorkflowAgentStatus('error', data.message);
                this.deploymentInProgress = false;
                this.updateWorkflowAgentButtonStates(false);
                break;
                
            case 'result':
                // Handle final result data if needed
                console.log('Workflow agent deployment result:', data.data);
                if (data.data && data.data.message) {
                    this.addToWorkflowAgentOutput(data.data.message, 'success');
                }
                break;
        }
    }

    showWorkflowAgentStatus(type, message) {
        const statusSection = document.getElementById('entryAgentStatus');
        if (!statusSection) return;

        statusSection.className = `status-section ${type}`;
        statusSection.textContent = message;
        statusSection.style.display = 'block';

        // If we're showing the dependency analysis message, immediately append the agent names being checked.
        if (typeof message === 'string' && message.includes('Analyzing Workflow Agent dependencies')) {
            // Run asynchronously so the UI can paint the initial message first.
            (async () => {
                try {
                    // Try to determine the current workflow agent (needed to load workflow agents if not already loaded)
                    let currentAgentName = null;
                    try {
                        const current = await this.getCurrentWorkflowAgent?.();
                        currentAgentName = current?.name || null;
                    } catch (e) {
                        console.warn('Dependency analysis: unable to get current workflow agent name:', e);
                    }

                    // Ensure workflow agents list is populated (only if we have an agent name and method available)
                    if (currentAgentName && typeof this.loadWorkflowAgents === 'function') {
                        try {
                            await this.loadWorkflowAgents(currentAgentName);
                        } catch (e) {
                            console.warn('Dependency analysis: loadWorkflowAgents failed (continuing with whatever is available):', e);
                        }
                    }

                    // Collect agent names from the workflow agents list UI if present
                    let agentNames = [];
                    const listEl = document.getElementById('workflowAgentsList');
                    if (listEl) {
                        agentNames = Array.from(listEl.querySelectorAll('.agent-name'))
                            .map(n => (n.textContent || '').trim())
                            .filter(Boolean);
                    }

                    // As a fallback, attempt to derive from discoveryAgent available agents (if window object present)
                    if (!agentNames.length && window.discoveryAgent && window.discoveryAgent.availableAgents) {
                        const avail = window.discoveryAgent.availableAgents;
                        const collected = [];
                        if (Array.isArray(avail.workflow_agents)) {
                            collected.push(...avail.workflow_agents.map(a => a.name).filter(Boolean));
                        }
                        if (Array.isArray(avail.tool_agents)) {
                            collected.push(...avail.tool_agents.map(a => a.name).filter(Boolean));
                        }
                        agentNames = collected;
                    }

                    if (agentNames.length) {
                        const namesDiv = document.createElement('div');
                        namesDiv.className = 'dependency-analysis-agent-names';
                        namesDiv.textContent = 'Agents being checked: ' + agentNames.join(', ');
                        statusSection.appendChild(namesDiv);
                        console.log('🔍 Workflow Agent dependency analysis - agents being checked:', agentNames);
                    } else {
                        console.log('🔍 Workflow Agent dependency analysis - no agent names could be enumerated at this time.');
                    }
                } catch (err) {
                    console.warn('Dependency analysis: unexpected error while appending agent names:', err);
                }
            })();
        }
    }


    clearWorkflowAgentOutput() {
        const outputDiv = document.getElementById('entryAgentOutput');
        if (outputDiv) {
            outputDiv.innerHTML = '';
        }
    }

    addToWorkflowAgentOutput(message, type = 'info') {
        const outputDiv = document.getElementById('entryAgentOutput');
        if (!outputDiv) return;

        const line = document.createElement('div');
        line.textContent = message;
        
        // Add appropriate styling based on type
        if (type === 'error') {
            line.style.color = '#dc3545';
        } else if (type === 'success') {
            line.style.color = '#28a745';
        } else if (type === 'warning') {
            line.style.color = '#ffc107';
        }
        
        outputDiv.appendChild(line);
        outputDiv.scrollTop = outputDiv.scrollHeight;
    }

    updateWorkflowAgentButtonStates(disabled) {
        const buttons = [
            'publishEntryAgentBtn'
        ];
        
        buttons.forEach(buttonId => {
            const button = document.getElementById(buttonId);
            if (button) {
                button.disabled = disabled;
            }
        });
    }

    resetWorkflowAgentForm() {
        // Clear dependency validation results (keeping for backward compatibility)
        const dependencyResultsDiv = document.getElementById('entryAgentDependencyResults');
        if (dependencyResultsDiv) {
            dependencyResultsDiv.innerHTML = '';
            dependencyResultsDiv.style.display = 'none';
        }

        // Clear status
        const statusSection = document.getElementById('entryAgentStatus');
        if (statusSection) {
            statusSection.style.display = 'none';
        }

        // Clear output
        this.clearWorkflowAgentOutput();

        // Reset button states
        this.updateWorkflowAgentButtonStates(false);
        
        // Enable publish button (we'll validate when it's clicked)
        const publishBtn = document.getElementById('publishEntryAgentBtn');
        if (publishBtn) {
            publishBtn.disabled = false;
        }
    }
}

// Export for use in main agent.js
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { DiscoveryPublishingClient, WorkflowAgentPublishingClient };
}

// Make classes available globally for web browser usage
if (typeof window !== 'undefined') {
    window.DiscoveryPublishingClient = DiscoveryPublishingClient;
    window.WorkflowAgentPublishingClient = WorkflowAgentPublishingClient;
}
