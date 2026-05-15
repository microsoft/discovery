/**
 * Profile Manager
 * Handles profile management operations for the Discovery Agent Workbench
 */

class ProfileManager {
    constructor() {
        this.baseUrl = '/api/profiles';
        this.currentProfile = null;
        this.profiles = [];
        this.listeners = [];
    }

    /**
     * Add a listener for profile change events
     * @param {Function} callback - Called when profile changes
     */
    addProfileChangeListener(callback) {
        this.listeners.push(callback);
    }

    /**
     * Notify all listeners of a profile change
     * @param {string} profileName - Name of the new active profile
     */
    notifyProfileChange(profileName) {
        this.listeners.forEach(listener => {
            try {
                listener(profileName);
            } catch (error) {
                console.error('Error in profile change listener:', error);
            }
        });
    }

    /**
     * List all available profiles
     * @returns {Promise<Array>} Array of profile objects
     */
    async listProfiles() {
        try {
            const response = await fetch(`${this.baseUrl}/list`);
            const data = await response.json();
            
            if (data.success) {
                this.profiles = data.profiles;
                return data.profiles;
            } else {
                throw new Error(data.error || 'Failed to list profiles');
            }
        } catch (error) {
            console.error('Error listing profiles:', error);
            throw error;
        }
    }

    /**
     * Get the currently active profile
     * @returns {Promise<Object>} Active profile object
     */
    async getActiveProfile() {
        try {
            const response = await fetch(`${this.baseUrl}/active`);
            const data = await response.json();
            
            if (data.success) {
                this.currentProfile = {
                    name: data.profile_name,
                    ...data.profile
                };
                return this.currentProfile;
            } else {
                throw new Error(data.error || 'Failed to get active profile');
            }
        } catch (error) {
            console.error('Error getting active profile:', error);
            throw error;
        }
    }

    /**
     * Switch to a different profile
     * @param {string} profileName - Name of the profile to switch to
     * @returns {Promise<Object>} Result object
     */
    async switchProfile(profileName) {
        try {
            const response = await fetch(`${this.baseUrl}/switch`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ profile_name: profileName })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.currentProfile = {
                    name: profileName,
                    ...data.profile
                };
                this.notifyProfileChange(profileName);
                return data;
            } else {
                throw new Error(data.error || 'Failed to switch profile');
            }
        } catch (error) {
            console.error('Error switching profile:', error);
            throw error;
        }
    }

    /**
     * Create a new profile
     * @param {Object} options - Profile creation options
     * @param {string} options.name - Internal name for the profile
     * @param {string} options.displayName - Display name for the profile
     * @param {string} options.description - Profile description
     * @param {string} options.copyFrom - Optional profile to copy settings from
     * @returns {Promise<Object>} Result object with the new profile
     */
    async createProfile({ name, displayName, description = '', copyFrom = null }) {
        try {
            const response = await fetch(`${this.baseUrl}/create`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    name,
                    display_name: displayName,
                    description,
                    copy_from: copyFrom
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                // Refresh the profiles list
                await this.listProfiles();
                return data;
            } else {
                throw new Error(data.error || 'Failed to create profile');
            }
        } catch (error) {
            console.error('Error creating profile:', error);
            throw error;
        }
    }

    /**
     * Update an existing profile
     * @param {string} profileName - Name of the profile to update
     * @param {Object} settings - New settings to apply
     * @returns {Promise<Object>} Result object
     */
    async updateProfile(profileName, settings) {
        try {
            const response = await fetch(`${this.baseUrl}/update`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    profile_name: profileName,
                    settings
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                // If updating the current profile, refresh it
                if (this.currentProfile && this.currentProfile.name === profileName) {
                    await this.getActiveProfile();
                }
                return data;
            } else {
                throw new Error(data.error || 'Failed to update profile');
            }
        } catch (error) {
            console.error('Error updating profile:', error);
            throw error;
        }
    }

    /**
     * Delete a profile
     * @param {string} profileName - Name of the profile to delete
     * @returns {Promise<Object>} Result object
     */
    async deleteProfile(profileName) {
        try {
            const response = await fetch(`${this.baseUrl}/delete`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ profile_name: profileName })
            });
            
            const data = await response.json();
            
            if (data.success) {
                // Refresh the profiles list
                await this.listProfiles();
                return data;
            } else {
                throw new Error(data.error || 'Failed to delete profile');
            }
        } catch (error) {
            console.error('Error deleting profile:', error);
            throw error;
        }
    }

    /**
     * Rename a profile
     * @param {string} profileName - Current name of the profile
     * @param {string} newName - New name for the profile
     * @returns {Promise<Object>} Result object
     */
    async renameProfile(profileName, newName) {
        try {
            const response = await fetch(`${this.baseUrl}/rename`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    profile_name: profileName,
                    new_name: newName
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                // Refresh the profiles list
                await this.listProfiles();
                // If renaming the current profile, update it
                if (this.currentProfile && this.currentProfile.name === profileName) {
                    this.currentProfile.name = newName;
                    this.notifyProfileChange(newName);
                }
                return data;
            } else {
                throw new Error(data.error || 'Failed to rename profile');
            }
        } catch (error) {
            console.error('Error renaming profile:', error);
            throw error;
        }
    }

    /**
     * Duplicate an existing profile
     * @param {Object} options - Duplication options
     * @param {string} options.profileName - Name of the profile to duplicate
     * @param {string} options.newName - Name for the new profile
     * @param {string} options.newDisplayName - Display name for the new profile
     * @returns {Promise<Object>} Result object with the new profile
     */
    async duplicateProfile({ profileName, newName, newDisplayName }) {
        try {
            const response = await fetch(`${this.baseUrl}/duplicate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    profile_name: profileName,
                    new_name: newName,
                    new_display_name: newDisplayName
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                // Refresh the profiles list
                await this.listProfiles();
                return data;
            } else {
                throw new Error(data.error || 'Failed to duplicate profile');
            }
        } catch (error) {
            console.error('Error duplicating profile:', error);
            throw error;
        }
    }

    /**
     * Validate a profile's configuration
     * @param {string} profileName - Name of the profile to validate
     * @returns {Promise<Object>} Validation result with errors and warnings
     */
    async validateProfile(profileName) {
        try {
            const response = await fetch(`${this.baseUrl}/validate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ profile_name: profileName })
            });
            
            const data = await response.json();
            return data;
        } catch (error) {
            console.error('Error validating profile:', error);
            throw error;
        }
    }

    /**
     * Get a formatted profile name for display
     * @param {Object} profile - Profile object
     * @returns {string} Formatted display name
     */
    getDisplayName(profile) {
        return profile.display_name || profile.name;
    }

    /**
     * Check if a profile name is valid
     * @param {string} name - Profile name to check
     * @returns {boolean} True if valid
     */
    isValidProfileName(name) {
        if (!name || typeof name !== 'string') return false;
        const trimmed = name.trim();
        if (trimmed.length === 0) return false;
        // Allow alphanumeric, hyphens, underscores, spaces
        return /^[a-zA-Z0-9_\- ]+$/.test(trimmed);
    }
}

// Create and export a singleton instance
const profileManager = new ProfileManager();
