"""
Workflow Pattern Validation for Workflow Agents

This module provides utilities to validate workflow patterns and detect
problematic transitions that bypass proper router coordination.
"""

import yaml
import re
from typing import Dict, List, Tuple, Optional


def validate_messageid_requirements(workflow_yaml_content: str) -> Tuple[bool, List[str], List[str]]:
    """
    Validate that messageId is properly defined in workflow variables and included
    in all state actor inputs.
    
    Args:
        workflow_yaml_content: YAML content of the workflow
        
    Returns:
        Tuple of (is_valid, errors, warnings)
        - is_valid: True if messageId requirements are met
        - errors: List of critical errors that must be fixed
        - warnings: List of warnings about potential issues
    """
    errors = []
    warnings = []
    
    try:
        workflow_data = yaml.safe_load(workflow_yaml_content)
    except yaml.YAMLError as e:
        errors.append(f"Invalid YAML format: {e}")
        return False, errors, warnings
    
    if not isinstance(workflow_data, dict):
        errors.append("Workflow must be a dictionary")
        return False, errors, warnings
    
    # Check 1: Verify messageId is defined in variables
    variables = workflow_data.get('variables', [])
    has_messageid_variable = False
    
    for var in variables:
        if isinstance(var, dict) and var.get('name') == 'messageId':
            has_messageid_variable = True
            break
    
    if not has_messageid_variable:
        errors.append(
            "❌ CRITICAL: Required workflow variable 'messageId' is missing from the workflow definition. "
            "Add this to the variables section:\n"
            "  - Type: userDefined\n"
            "    name: messageId"
        )
    
    # Check 2: Verify messageId is included in all state actor inputs
    states = workflow_data.get('states', [])
    states_missing_messageid = []
    
    for state in states:
        if not isinstance(state, dict):
            continue
            
        state_name = state.get('name', '')
        actors = state.get('actors', [])
        
        # Skip states with no actors (like End states)
        if not actors:
            continue
        
        for actor in actors:
            if isinstance(actor, dict):
                inputs = actor.get('inputs', {})
                
                # Check if messageId is in the inputs
                if 'messageId' not in inputs:
                    agent_name = actor.get('agent', '(unknown agent)')
                    states_missing_messageid.append(f"State '{state_name}' (agent: {agent_name})")
    
    if states_missing_messageid:
        errors.append(
            f"❌ CRITICAL: Required state input 'messageId' is missing from {len(states_missing_messageid)} state(s). "
            "Each actor must include 'messageId: messageId' in its inputs section. "
            f"Missing in: {', '.join(states_missing_messageid[:5])}"  # Show first 5
        )
        if len(states_missing_messageid) > 5:
            errors.append(f"   ... and {len(states_missing_messageid) - 5} more state(s)")
    
    is_valid = len(errors) == 0

    return is_valid, errors, warnings


def validate_thread_variable_references(workflow_yaml_content: str) -> Tuple[bool, List[str], List[str]]:
    """
    Validate that every thread value referenced by state actors has a matching
    variable definition with Type: thread in the variables section.

    Args:
        workflow_yaml_content: YAML content of the workflow

    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    errors = []
    warnings = []

    try:
        workflow_data = yaml.safe_load(workflow_yaml_content)
    except yaml.YAMLError as e:
        errors.append(f"Invalid YAML format: {e}")
        return False, errors, warnings

    if not isinstance(workflow_data, dict):
        errors.append("Workflow must be a dictionary")
        return False, errors, warnings

    # Collect all thread variable definitions from the variables section
    variables = workflow_data.get('variables', [])
    defined_threads = set()
    for var in variables:
        if isinstance(var, dict) and var.get('Type') == 'thread':
            name = var.get('name')
            if name:
                defined_threads.add(name)

    # Collect all thread references from state actors
    states = workflow_data.get('states', [])
    referenced_threads: Dict[str, List[str]] = {}  # thread_name -> [state_names]

    for state in states:
        if not isinstance(state, dict):
            continue
        state_name = state.get('name', '')
        actors = state.get('actors', [])
        if not actors:
            continue
        for actor in actors:
            if isinstance(actor, dict):
                thread_ref = actor.get('thread')
                if thread_ref:
                    referenced_threads.setdefault(thread_ref, []).append(state_name)

    # Check for referenced threads that have no matching variable definition
    for thread_name, state_names in referenced_threads.items():
        if thread_name not in defined_threads:
            states_str = ', '.join(f"'{s}'" for s in state_names[:5])
            if len(state_names) > 5:
                states_str += f' ... and {len(state_names) - 5} more'
            errors.append(
                f"❌ CRITICAL: Thread '{thread_name}' is referenced by state(s) {states_str} "
                f"but has no matching variable definition. "
                f"Add this to the variables section:\n"
                f"  - Type: thread\n"
                f"    name: {thread_name}"
            )

    # Check for defined threads that are never referenced (informational)
    for thread_name in defined_threads:
        if thread_name not in referenced_threads:
            warnings.append(
                f"⚠️ Thread variable '{thread_name}' is defined but never referenced by any state actor."
            )

    is_valid = len(errors) == 0
    return is_valid, errors, warnings


def validate_workflow_transitions(workflow_yaml_content: str) -> Tuple[bool, List[str], List[str]]:
    """
    Validate workflow transitions to ensure proper router coordination patterns.
    
    Args:
        workflow_yaml_content: YAML content of the workflow
        
    Returns:
        Tuple of (is_valid, errors, warnings)
        - is_valid: True if no critical violations found
        - errors: List of critical errors that must be fixed
        - warnings: List of warnings about potential issues
    """
    errors = []
    warnings = []
    
    try:
        workflow_data = yaml.safe_load(workflow_yaml_content)
    except yaml.YAMLError as e:
        errors.append(f"Invalid YAML format: {e}")
        return False, errors, warnings
    
    if not isinstance(workflow_data, dict):
        errors.append("Workflow must be a dictionary")
        return False, errors, warnings
    
    # Extract states and transitions
    states = workflow_data.get('states', [])
    transitions = workflow_data.get('transitions', [])
    
    # Build state and agent information
    state_info = {}
    router_states = []
    specialized_agent_states = []
    summary_states = []
    
    for state in states:
        if not isinstance(state, dict):
            continue
            
        state_name = state.get('name', '')
        actors = state.get('actors', [])
        
        state_info[state_name] = {
            'actors': actors,
            'is_router': False,
            'is_specialized': False,
            'is_summary': False
        }
        
        # Classify state types based on naming conventions and actor patterns
        for actor in actors:
            if isinstance(actor, dict):
                agent_name = actor.get('agent', '').lower()
                
                # Router patterns
                if ('router' in agent_name or 'route' in agent_name or 
                    state_name.lower() in ['agentrouter', 'router']):
                    state_info[state_name]['is_router'] = True
                    router_states.append(state_name)
                
                # Summary patterns  
                elif ('summar' in agent_name or 'summary' in state_name.lower()):
                    state_info[state_name]['is_summary'] = True
                    summary_states.append(state_name)
                
                # Specialized agent patterns (not router, not summary, not planning/end)
                elif (agent_name and state_name.lower() not in ['planning', 'end', 'start'] and
                      'router' not in agent_name and 'summar' not in agent_name):
                    state_info[state_name]['is_specialized'] = True
                    specialized_agent_states.append(state_name)
    
    # Validate transition patterns
    problematic_transitions = []
    good_patterns = []
    
    for transition in transitions:
        if not isinstance(transition, dict):
            continue
            
        from_state = transition.get('from', '')
        to_state = transition.get('to', '')
        event = transition.get('event', '')
        
        if not from_state or not to_state:
            continue
        
        from_info = state_info.get(from_state, {})
        to_info = state_info.get(to_state, {})
        
        # Check for problematic pattern: Specialized Agent → Summary
        if from_info.get('is_specialized') and to_info.get('is_summary'):
            problematic_transitions.append({
                'from': from_state,
                'to': to_state,
                'event': event,
                'issue': 'Specialized agent transitioning directly to Summary (bypasses router)'
            })
            errors.append(
                f"❌ CRITICAL VIOLATION: '{from_state} → {to_state}' is FORBIDDEN. "
                f"Specialized agents must NEVER transition directly to Summary. "
                f"REQUIRED: {from_state} → Router → Summary. "
                f"Fix: Remove this transition and ensure {from_state} returns to router."
            )
        
        # Check for good patterns
        elif from_info.get('is_specialized') and from_info.get('is_router'):
            good_patterns.append(f"✅ {from_state} → {to_state}")
        elif from_info.get('is_router') and to_info.get('is_summary'):
            good_patterns.append(f"✅ {from_state} → {to_state} (proper router-to-summary)")
    
    # Additional validations
    
    # Check if there's at least one router state
    if not router_states:
        warnings.append("⚠️ No router state detected. Workflow should have a router for coordination.")
    
    # Check if specialized agents have proper return paths to router
    for spec_state in specialized_agent_states:
        has_return_to_router = False
        for transition in transitions:
            if (transition.get('from') == spec_state and 
                transition.get('to') in router_states):
                has_return_to_router = True
                break
        
        if not has_return_to_router:
            warnings.append(
                f"⚠️ Specialized agent state '{spec_state}' has no transition back to router. "
                f"This may lead to workflow dead-ends."
            )
    
    # Generate summary
    if good_patterns:
        warnings.insert(0, f"Good patterns found: {len(good_patterns)}")
        for pattern in good_patterns[:3]:  # Show first 3 examples
            warnings.insert(1, f"  {pattern}")
    
    is_valid = len(errors) == 0
    
    return is_valid, errors, warnings


if __name__ == "__main__":
    # Example usage for testing
    sample_workflow = """
name: test_workflow
states:
  - name: AgentRouter
    actors:
      - agent: router_agent
  - name: SpecializedAgent
    actors:
      - agent: specialized_agent  
  - name: Summary
    actors:
      - agent: summary_agent
transitions:
  - from: SpecializedAgent
    to: Summary
    event: GenerateSummary
  - from: AgentRouter  
    to: SpecializedAgent
    event: RunSpecialized
"""
    
    is_valid, errors, warnings = validate_workflow_transitions(sample_workflow)
    print(f"Valid: {is_valid}")
    print(f"Errors: {errors}")
    print(f"Warnings: {warnings}")