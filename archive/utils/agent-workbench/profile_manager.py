"""
Profile Manager for Discovery Agent Workbench

Manages configuration profiles for different environments (dev, test, prod, etc.)
allowing users to easily switch between Azure subscriptions, tenants, and settings.
"""

import json
import os
import shutil
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path


class ProfileManager:
    """Manages configuration profiles for the Discovery Agent Workbench"""
    
    def __init__(self, config_path: str = 'discovery_config.json'):
        """
        Initialize the ProfileManager
        
        Args:
            config_path: Path to the configuration file
        """
        self.config_path = config_path
        self.config = None
        self._load_config()
    
    def _load_config(self):
        """Load configuration from file, auto-migrating old format if needed"""
        if not os.path.exists(self.config_path):
            # Create default config with profiles structure
            self.config = {
                'active_profile': 'Default',
                'profiles': {
                    'Default': self._get_default_profile_settings()
                }
            }
            self._save_config()
            return
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            
            # Check if old format (no profiles key)
            if 'profiles' not in self.config:
                print("🔄 Migrating configuration to profiles format...")
                self._migrate_to_profiles()
                print("✅ Configuration migrated successfully")
        except json.JSONDecodeError as e:
            print(f"❌ Error loading config: {e}")
            raise
        except Exception as e:
            print(f"❌ Unexpected error loading config: {e}")
            raise
    
    def _migrate_to_profiles(self):
        """Migrate old flat configuration to profiles format"""
        # Backup original config
        backup_path = f"{self.config_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(self.config_path, backup_path)
        print(f"📋 Backup created: {backup_path}")
        
        # Extract old config
        old_config = self.config.copy()
        
        # Create new profiles structure
        self.config = {
            'active_profile': 'Default',
            'profiles': {
                'Default': old_config
            },
            'migration_info': {
                'migrated_at': datetime.now().isoformat(),
                'backup_file': backup_path,
                'from_version': 'legacy'
            }
        }
        
        self._save_config()
    
    def _get_default_profile_settings(self) -> Dict:
        """Get default profile settings structure"""
        return {
            'azure': {
                'subscription_id': '',
                'resource_group': '',
                'location': '',
                'tenant_id': '',
                'acr_name': '',
                'acr_token_name': '',
                'acr_token_password': '',
                'storage_account': ''
            },
            'azure_openai': {
                'endpoint_url': '',
                'deployment_name': '',
                'auth_type': 'api_key',
                'api_key': '',
                'api_version': '2024-12-01-preview',
                'azure_ad': {
                    'subscription_id': '',
                    'resource_group': '',
                    'tenant_id': None,
                    'scope': 'https://cognitiveservices.azure.com/.default'
                }
            },
            'llm_config': {
                'model_endpoint': '',
                'max_tokens': 64000,
                'target_tokens': 48000,
                'max_output_tokens': 16384,
                'temperature': 0.3,
                'strategy': 'hybrid',
                'max_retries': 3
            },
            'directories': {
                'tool_agents_dir': '../../',
                'kb_agents_dir': '../../',
                'entry_agents_dir': '../../'
            }
        }
    
    def _save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Error saving config: {e}")
            raise
    
    def list_profiles(self) -> List[Dict[str, Any]]:
        """
        List all available profiles
        
        Returns:
            List of profile information (name, is_active)
        """
        profiles = []
        active_profile_name = self.config.get('active_profile', '')
        
        for profile_name, profile_data in self.config.get('profiles', {}).items():
            profiles.append({
                'name': profile_name,
                'display_name': profile_name,
                'is_active': profile_name == active_profile_name
            })
        
        # Sort by active first, then alphabetically
        profiles.sort(key=lambda p: (not p['is_active'], p['name'].lower()))
        return profiles
    
    def get_active_profile_name(self) -> str:
        """Get the name of the currently active profile"""
        return self.config.get('active_profile', 'Default')
    
    def get_active_profile(self) -> Dict[str, Any]:
        """
        Get the currently active profile settings
        
        Returns:
            Active profile configuration
        """
        active_name = self.get_active_profile_name()
        profiles = self.config.get('profiles', {})
        
        if active_name not in profiles:
            # Fallback to first available profile or create default
            if profiles:
                active_name = list(profiles.keys())[0]
                self.config['active_profile'] = active_name
                self._save_config()
            else:
                # Create default profile
                profiles['Default'] = self._get_default_profile_settings()
                self.config['active_profile'] = 'Default'
                self._save_config()
                return profiles['Default']
        
        return profiles[active_name]
    
    def get_profile(self, profile_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific profile by name
        
        Args:
            profile_name: Name of the profile to retrieve
            
        Returns:
            Profile configuration or None if not found
        """
        return self.config.get('profiles', {}).get(profile_name)
    
    def switch_profile(self, profile_name: str) -> Dict[str, Any]:
        """
        Switch to a different profile
        
        Args:
            profile_name: Name of the profile to switch to
            
        Returns:
            Result dict with success status and message
        """
        profiles = self.config.get('profiles', {})
        
        if profile_name not in profiles:
            return {
                'success': False,
                'error': f"Profile '{profile_name}' not found"
            }
        
        old_profile = self.config.get('active_profile')
        self.config['active_profile'] = profile_name
        self._save_config()
        
        return {
            'success': True,
            'message': f"Switched from '{old_profile}' to '{profile_name}'",
            'profile': profiles[profile_name]
        }
    
    def create_profile(self, name: str, display_name: str = None, 
                      description: str = '', copy_from: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new profile
        
        Args:
            name: Internal name for the profile (key)
            display_name: Display name for the profile
            description: Profile description
            copy_from: Optional profile name to copy settings from
            
        Returns:
            Result dict with success status and message
        """
        profiles = self.config.get('profiles', {})
        
        # Check if profile already exists
        if name in profiles:
            return {
                'success': False,
                'error': f"Profile '{name}' already exists"
            }
        
        # Validate name
        if not name or not name.strip():
            return {
                'success': False,
                'error': 'Profile name cannot be empty'
            }
        
        # Create new profile
        if copy_from and copy_from in profiles:
            # Copy from existing profile
            new_profile = json.loads(json.dumps(profiles[copy_from]))  # Deep copy
        else:
            # Create from default template
            new_profile = self._get_default_profile_settings()
        
        profiles[name] = new_profile
        self._save_config()
        
        return {
            'success': True,
            'message': f"Profile '{name}' created successfully",
            'profile': new_profile
        }
    
    def update_profile(self, profile_name: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing profile
        
        Args:
            profile_name: Name of the profile to update
            settings: New settings to apply
            
        Returns:
            Result dict with success status and message
        """
        profiles = self.config.get('profiles', {})
        
        if profile_name not in profiles:
            return {
                'success': False,
                'error': f"Profile '{profile_name}' not found"
            }
        
        # Update profile with new settings
        profiles[profile_name].update(settings)
        
        self._save_config()
        
        return {
            'success': True,
            'message': f"Profile '{profile_name}' updated successfully",
            'profile': profiles[profile_name]
        }
    
    def delete_profile(self, profile_name: str) -> Dict[str, Any]:
        """
        Delete a profile
        
        Args:
            profile_name: Name of the profile to delete
            
        Returns:
            Result dict with success status and message
        """
        profiles = self.config.get('profiles', {})
        
        # Prevent deletion if it's the only profile
        if len(profiles) <= 1:
            return {
                'success': False,
                'error': 'Cannot delete the last profile. At least one profile must exist.'
            }
        
        # Prevent deletion of active profile
        if profile_name == self.config.get('active_profile'):
            return {
                'success': False,
                'error': 'Cannot delete the active profile. Please switch to another profile first.'
            }
        
        if profile_name not in profiles:
            return {
                'success': False,
                'error': f"Profile '{profile_name}' not found"
            }
        
        del profiles[profile_name]
        self._save_config()
        
        return {
            'success': True,
            'message': f"Profile '{profile_name}' deleted successfully"
        }
    
    def rename_profile(self, profile_name: str, new_name: str) -> Dict[str, Any]:
        """
        Rename a profile
        
        Args:
            profile_name: Current name of the profile
            new_name: New name for the profile
            
        Returns:
            Result dict with success status and message
        """
        profiles = self.config.get('profiles', {})
        
        # Validate profile exists
        if profile_name not in profiles:
            return {
                'success': False,
                'error': f"Profile '{profile_name}' not found"
            }
        
        # Validate new name is not empty
        if not new_name or not new_name.strip():
            return {
                'success': False,
                'error': 'New profile name cannot be empty'
            }
        
        # Validate new name doesn't already exist (unless it's the same name)
        if new_name != profile_name and new_name in profiles:
            return {
                'success': False,
                'error': f"Profile '{new_name}' already exists"
            }
        
        # If the name didn't change, no operation needed
        if new_name == profile_name:
            return {
                'success': True,
                'message': 'Profile name unchanged'
            }
        
        # Rename the profile by copying data to new key and deleting old key
        profiles[new_name] = profiles[profile_name]
        del profiles[profile_name]
        
        # If this was the active profile, update active_profile
        if self.config.get('active_profile') == profile_name:
            self.config['active_profile'] = new_name
        
        self._save_config()
        
        return {
            'success': True,
            'message': f"Profile renamed from '{profile_name}' to '{new_name}'",
            'new_name': new_name
        }
    
    def duplicate_profile(self, profile_name: str, new_name: str, 
                         new_display_name: str = None) -> Dict[str, Any]:
        """
        Duplicate an existing profile
        
        Args:
            profile_name: Name of the profile to duplicate
            new_name: Name for the new profile
            new_display_name: Display name for the new profile
            
        Returns:
            Result dict with success status and message
        """
        profiles = self.config.get('profiles', {})
        
        if profile_name not in profiles:
            return {
                'success': False,
                'error': f"Profile '{profile_name}' not found"
            }
        
        if new_name in profiles:
            return {
                'success': False,
                'error': f"Profile '{new_name}' already exists"
            }
        
        # Create duplicate
        return self.create_profile(
            name=new_name,
            display_name=new_display_name or f"{profiles[profile_name].get('name', profile_name)} (Copy)",
            description=profiles[profile_name].get('description', ''),
            copy_from=profile_name
        )
    
    def export_profile(self, profile_name: str, output_path: str) -> Dict[str, Any]:
        """
        Export a profile to a JSON file
        
        Args:
            profile_name: Name of the profile to export
            output_path: Path where to save the exported profile
            
        Returns:
            Result dict with success status and message
        """
        profiles = self.config.get('profiles', {})
        
        if profile_name not in profiles:
            return {
                'success': False,
                'error': f"Profile '{profile_name}' not found"
            }
        
        try:
            profile_data = profiles[profile_name].copy()
            profile_data['exported_at'] = datetime.now().isoformat()
            profile_data['exported_from'] = profile_name
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(profile_data, f, indent=2, ensure_ascii=False)
            
            return {
                'success': True,
                'message': f"Profile '{profile_name}' exported to {output_path}",
                'path': output_path
            }
        except Exception as e:
            return {
                'success': False,
                'error': f"Failed to export profile: {str(e)}"
            }
    
    def import_profile(self, file_path: str, new_name: str, 
                      new_display_name: str = None) -> Dict[str, Any]:
        """
        Import a profile from a JSON file
        
        Args:
            file_path: Path to the profile JSON file
            new_name: Name for the imported profile
            new_display_name: Display name for the imported profile
            
        Returns:
            Result dict with success status and message
        """
        profiles = self.config.get('profiles', {})
        
        if new_name in profiles:
            return {
                'success': False,
                'error': f"Profile '{new_name}' already exists"
            }
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                profile_data = json.load(f)
            
            # Update metadata
            profile_data['name'] = new_display_name or new_name
            profile_data['imported_at'] = datetime.now().isoformat()
            
            # Remove export metadata if present
            profile_data.pop('exported_at', None)
            profile_data.pop('exported_from', None)
            
            profiles[new_name] = profile_data
            self._save_config()
            
            return {
                'success': True,
                'message': f"Profile '{new_name}' imported successfully",
                'profile': profile_data
            }
        except json.JSONDecodeError as e:
            return {
                'success': False,
                'error': f"Invalid JSON file: {str(e)}"
            }
        except Exception as e:
            return {
                'success': False,
                'error': f"Failed to import profile: {str(e)}"
            }
    
    def validate_profile(self, profile_name: str) -> Dict[str, Any]:
        """
        Validate a profile's configuration
        
        Args:
            profile_name: Name of the profile to validate
            
        Returns:
            Validation result with warnings and errors
        """
        profiles = self.config.get('profiles', {})
        
        if profile_name not in profiles:
            return {
                'valid': False,
                'errors': [f"Profile '{profile_name}' not found"]
            }
        
        profile = profiles[profile_name]
        errors = []
        warnings = []
        
        # Check required Azure fields
        azure = profile.get('azure', {})
        if not azure.get('subscription_id'):
            errors.append('Azure subscription_id is required')
        if not azure.get('resource_group'):
            errors.append('Azure resource_group is required')
        if not azure.get('location'):
            warnings.append('Azure location is not set')
        
        # Check Azure OpenAI configuration
        aoai = profile.get('azure_openai', {})
        if not aoai.get('endpoint_url'):
            warnings.append('Azure OpenAI endpoint_url is not set')
        if not aoai.get('deployment_name'):
            warnings.append('Azure OpenAI deployment_name is not set')
        
        auth_type = aoai.get('auth_type', 'api_key')
        if auth_type == 'api_key' and not aoai.get('api_key'):
            warnings.append('Azure OpenAI API key is not set')
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }
