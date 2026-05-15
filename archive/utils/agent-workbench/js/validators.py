"""Utility validators for Discovery templates.

Provides validate_yaml(json_schema, yaml_data) to validate a YAML document
against a JSON Schema. This centralizes validation logic so other scripts
don't have to duplicate custom code.

Usage examples (programmatic):

    from Utils.validators import validate_yaml

    result = validate_yaml('agent_definition_schema.json', 'PubChem/PubChemAgent.yaml')
    if result.valid:
        print('YAML is valid')
    else:
        print('Invalid YAML:')
        for err in result.errors:
            print(f" - {err.path}: {err.message}")

Command line quick test:

    pwsh> python js/validators.py --schema agent_definition_schema.json --yaml PubChem/PubChemAgent.yaml

Return object fields:
    valid (bool)      - True if schema validation passed.
    errors (list)     - List of ErrorDetail objects (path, message, validator, validator_value).
    data (Any)        - Parsed YAML data structure (dict/list) or None if parse failed.
    schema (dict)     - The loaded JSON schema (for caller reuse / debug).

The function is intentionally permissive in accepted input types for convenience:
 - json_schema may be: dict (already loaded) OR path to JSON schema file (str | Path)
 - yaml_data may be: dict/list (already parsed), YAML text string, or path to YAML file

Raises no exceptions on validation failure; instead captures and returns errors
so callers can decide how to surface them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Union, Optional, Dict
import json
import sys

import yaml  # PyYAML

# Import emoji detection utilities
try:
    # Try relative import first (when running as part of agent-workbench)
    import os
    _parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _parent_dir not in sys.path:
        sys.path.insert(0, _parent_dir)
    from file_utils import detect_emojis, detect_emojis_in_yaml_fields, EmojiDetectionResult
    HAS_EMOJI_DETECTION = True
except ImportError:
    HAS_EMOJI_DETECTION = False
    EmojiDetectionResult = None  # type: ignore

try:
    import jsonschema
    from jsonschema import Draft202012Validator  # modern draft; falls back if unavailable
except Exception:  # pragma: no cover - if jsonschema missing we give a clear error at runtime
    jsonschema = None  # type: ignore
    Draft202012Validator = None  # type: ignore


@dataclass
class ErrorDetail:
    """Represents a single schema validation error."""
    path: str
    message: str
    validator: str | None = None
    validator_value: Any | None = None


@dataclass
class EmojiWarning:
    """Represents an emoji warning found during validation."""
    path: str
    field: str
    emoji: str
    line: int
    column: int
    suggested_replacement: Optional[str] = None
    message: str = ""

    def __post_init__(self):
        if not self.message:
            replacement_hint = f" (suggested: '{self.suggested_replacement}')" if self.suggested_replacement else ""
            self.message = f"Emoji '{self.emoji}' found at line {self.line}, column {self.column}{replacement_hint}"


@dataclass
class EmojiValidationResult:
    """Result of emoji validation for YAML content."""
    has_emojis: bool
    warnings: List[EmojiWarning]
    emoji_count: int
    unique_emojis: List[str]
    fields_with_emojis: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'has_emojis': self.has_emojis,
            'emoji_count': self.emoji_count,
            'unique_emojis': self.unique_emojis,
            'fields_with_emojis': self.fields_with_emojis,
            'warnings': [
                {
                    'path': w.path,
                    'field': w.field,
                    'emoji': w.emoji,
                    'line': w.line,
                    'column': w.column,
                    'suggested_replacement': w.suggested_replacement,
                    'message': w.message
                }
                for w in self.warnings
            ]
        }


@dataclass
class ValidationResult:
    """Structured result returned by validate_yaml."""
    valid: bool
    errors: List[ErrorDetail]
    data: Any | None
    schema: dict | None
    emoji_validation: Optional[EmojiValidationResult] = None

    def raise_for_errors(self) -> None:
        """Convenience helper: raise ValueError if not valid with combined messages."""
        if not self.valid:
            msgs = '\n'.join(f"{e.path}: {e.message}" for e in self.errors)
            raise ValueError(f"YAML validation failed:\n{msgs}")

    def has_emoji_warnings(self) -> bool:
        """Check if there are emoji warnings."""
        return self.emoji_validation is not None and self.emoji_validation.has_emojis


def _load_json_schema(schema_input: Union[str, Path, dict]) -> dict:
    if isinstance(schema_input, dict):
        return schema_input
    path = Path(schema_input)
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def _load_yaml(yaml_input: Union[str, Path, dict, list]) -> Any:
    if isinstance(yaml_input, (dict, list)):
        return yaml_input
    # If the input is a string that looks like YAML/JSON content, treat it as content
    # rather than probing the filesystem. This avoids OSError on very long strings
    # or accidentally treating YAML text as a filename.
    str_input = str(yaml_input)
    # Heuristics indicating this is raw YAML/JSON content:
    looks_like_yaml = (
        '\n' in str_input or                 # multi-line likely YAML
        str_input.strip().startswith('---') or
        str_input.strip().startswith('{') or  # JSON-like
        str_input.strip().startswith('[') or  # JSON list
        '\n  ' in str_input or               # indented block
        ': ' in str_input or                 # key: value pattern
        str_input.strip().startswith('- ') or
        '\n|' in str_input or               # block scalar
        '\n>' in str_input
    )

    if looks_like_yaml:
        return yaml.safe_load(str_input)

    # Distinguish between a path and raw YAML by checking for existing file
    potential_path = Path(str_input)
    # Guard against pathological inputs (very long strings / invalid path characters)
    try:
        is_file = potential_path.exists() and potential_path.is_file()
    except (OSError, ValueError) as e:
        # Could be 'File name too long' or other OS-level error when probing the path.
        # Treat the input as raw YAML text in that case.
        is_file = False

    if is_file:
        with potential_path.open('r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    # Treat as raw YAML text
    # yaml.safe_load expects a string (content) or a stream; ensure cast to str
    return yaml.safe_load(str(yaml_input))


def _format_error_path(relative_path: Iterable[Union[str, int]]) -> str:
    parts: List[str] = []
    for p in relative_path:
        if isinstance(p, int):
            parts.append(f"[{p}]")
        else:
            if parts:
                parts.append(f".{p}")
            else:
                parts.append(str(p))
    return ''.join(parts) if parts else '<root>'


def validate_emojis_in_yaml(yaml_data: Any, yaml_text: Optional[str] = None) -> EmojiValidationResult:
    """
    Validate YAML content for emojis and return warnings.

    Scans through parsed YAML data structure to find emojis in field values
    and keys, returning detailed information about each occurrence.

    Args:
        yaml_data: Parsed YAML data (dict, list, or scalar)
        yaml_text: Optional raw YAML text for more accurate line numbers

    Returns:
        EmojiValidationResult with warnings for each emoji found
    """
    if not HAS_EMOJI_DETECTION:
        return EmojiValidationResult(
            has_emojis=False,
            warnings=[],
            emoji_count=0,
            unique_emojis=[],
            fields_with_emojis=[]
        )

    warnings: List[EmojiWarning] = []
    unique_emojis: set = set()
    fields_with_emojis: List[str] = []

    # Use the YAML structure detection for field-level information
    emoji_fields = detect_emojis_in_yaml_fields(yaml_data)

    for field_info in emoji_fields:
        path = field_info['path']
        field_name = field_info['field']
        emoji_result = field_info['emoji_result']

        fields_with_emojis.append(f"{path}.{field_name}" if path != '<root>' else field_name)

        for emoji_data in emoji_result.get('emojis', []):
            unique_emojis.add(emoji_data['emoji'])
            warnings.append(EmojiWarning(
                path=path,
                field=field_name,
                emoji=emoji_data['emoji'],
                line=emoji_data['line'],
                column=emoji_data['column'],
                suggested_replacement=emoji_data.get('suggested_replacement')
            ))

    return EmojiValidationResult(
        has_emojis=len(warnings) > 0,
        warnings=warnings,
        emoji_count=len(warnings),
        unique_emojis=list(unique_emojis),
        fields_with_emojis=fields_with_emojis
    )


def validate_yaml(json_schema: Union[str, Path, dict], yaml_data: Union[str, Path, dict, list]) -> ValidationResult:
    """Validate YAML content against a JSON schema.

    Parameters
    ----------
    json_schema : str | Path | dict
        JSON schema (already loaded dict OR path to a .json file).
    yaml_data : str | Path | dict | list
        YAML content (already parsed structure, raw YAML text, or path to .yaml file).

    Returns
    -------
    ValidationResult
        Object containing validity flag, list of errors, parsed data, and schema.
    """
    if jsonschema is None:
        return ValidationResult(
            valid=False,
            errors=[ErrorDetail(path='<import>', message='jsonschema package not installed; run "pip install jsonschema"')],
            data=None,
            schema=None,
        )

    try:
        schema = _load_json_schema(json_schema)
    except Exception as e:  # pragma: no cover
        return ValidationResult(
            valid=False,
            errors=[ErrorDetail(path='<schema>', message=f'Failed loading schema: {e}')],
            data=None,
            schema=None,
        )

    try:
        data = _load_yaml(yaml_data)
    except Exception as e:
        return ValidationResult(
            valid=False,
            errors=[ErrorDetail(path='<yaml>', message=f'Failed parsing YAML: {e}')],
            data=None,
            schema=schema,
        )

    # Choose validator (support future drafts if available)
    ValidatorClass = Draft202012Validator or jsonschema.Draft7Validator
    validator = ValidatorClass(schema)  # type: ignore[arg-type]

    errors: List[ErrorDetail] = []
    for err in sorted(validator.iter_errors(data), key=lambda e: e.path):
        errors.append(
            ErrorDetail(
                path=_format_error_path(err.path),
                message=err.message,
                validator=getattr(err, 'validator', None),
                validator_value=getattr(err, 'validator_value', None),
            )
        )

    # Additional rule: ensure uniqueness of variable 'name' fields in workflow variables
    try:
        vars_list = None
        if isinstance(data, dict):
            # top-level 'variables' or nested under 'workflow.variables'
            vars_list = data.get('variables') or (data.get('workflow') or {}).get('variables')

        if isinstance(vars_list, list):
            seen = {}
            for idx, item in enumerate(vars_list):
                if isinstance(item, dict):
                    vname = item.get('name')
                    if vname:
                        if vname in seen:
                            first_idx = seen[vname]
                            errors.append(ErrorDetail(
                                path='variables',
                                message=f"Duplicate variable name '{vname}' found at indices {first_idx} and {idx}. Variable names must be unique."
                            ))
                        else:
                            seen[vname] = idx
    except Exception:
        # Non-fatal: if duplicate detection fails, leave schema errors as-is
        pass

    # Emoji validation - check for emojis in YAML content
    emoji_validation = None
    try:
        # Get the raw YAML text if it was provided as string
        yaml_text = None
        if isinstance(yaml_data, str):
            yaml_text = yaml_data
        emoji_validation = validate_emojis_in_yaml(data, yaml_text)
    except Exception:
        # Non-fatal: if emoji detection fails, continue without it
        pass

    return ValidationResult(valid=not errors, errors=errors, data=data, schema=schema, emoji_validation=emoji_validation)


def events_validation(agents_data: List[dict]) -> ValidationResult:
    """
    Validates bidirectional consistency between workflow transition events and agent-declared events.
    
    Args:
        agents_data (list): List of dictionaries with structure:
            [
                {
                    'name': 'agent_name',
                    'type': 'workflow' | 'agent',
                    'yaml_content': 'yaml_string'
                },
                ...
            ]
    
    Returns:
        ValidationResult: Validation results with errors and warnings in the errors list
    """
    def parse_yaml_content(yaml_string: str) -> Any:
        """Helper to safely parse YAML strings"""
        try:
            return yaml.safe_load(yaml_string)
        except Exception:
            return None

    # Step 1: Create a list of 'event' under transitions with their corresponding 'from' agent
    workflow_events = {}  # {event_name: from_agent}
    workflow_found = False
    
    for agent_data in agents_data:
        if agent_data.get('type') == 'workflow':
            workflow_found = True
            workflow_content = parse_yaml_content(agent_data.get('yaml_content', ''))
            
            if not workflow_content:
                return ValidationResult(
                    valid=False,
                    errors=[ErrorDetail(path='<workflow>', message=f"Invalid YAML format in workflow '{agent_data.get('name', 'unknown')}'")],
                    data=None,
                    schema=None
                )
            
            # Only handle new format - direct top-level transitions
            if 'transitions' not in workflow_content:
                return ValidationResult(
                    valid=False,
                    errors=[ErrorDetail(path='<workflow>', message=f"Workflow '{agent_data.get('name', 'unknown')}' missing 'transitions' - legacy format not supported")],
                    data=None,
                    schema=None
                )
            
            transitions = workflow_content.get('transitions', [])
            for i, transition in enumerate(transitions):
                if isinstance(transition, dict):
                    event = transition.get('event')
                    from_agent = transition.get('from')
                    if event and from_agent:
                        workflow_events[event] = from_agent
            break  # Process only the first workflow found

    if not workflow_found:
        return ValidationResult(
            valid=False,
            errors=[ErrorDetail(path='<agents_data>', message="No workflow definition found in provided agents data")],
            data=None,
            schema=None
        )

    # Step 2: For each agent, create a list of events from actions
    agent_events = {}  # {agent_name: [event_names]}
    
    for agent_data in agents_data:
        if agent_data.get('type') in ('agent', 'router'):
            agent_name = agent_data.get('name', 'unknown')
            agent_content = parse_yaml_content(agent_data.get('yaml_content', ''))
            
            if not agent_content:
                return ValidationResult(
                    valid=False,
                    errors=[ErrorDetail(path=f'<agent:{agent_name}>', message=f"Invalid YAML format in agent '{agent_name}'")],
                    data=None,
                    schema=None
                )
            
            # Extract events from multiple possible definitions
            events = []
            # 1. Top-level actions
            if 'actions' in agent_content and isinstance(agent_content['actions'], list):
                for action in agent_content['actions']:
                    if isinstance(action, dict) and 'name' in action:
                        events.append(action['name'])
            # 2. Nested agent.actions
            if 'agent' in agent_content and isinstance(agent_content['agent'], dict):
                nested = agent_content['agent']
                if 'actions' in nested and isinstance(nested['actions'], list):
                    for action in nested['actions']:
                        if isinstance(action, dict) and 'name' in action and action['name'] not in events:
                            events.append(action['name'])
            # 3. extension.events list
            if 'extension' in agent_content and isinstance(agent_content['extension'], dict):
                ext = agent_content['extension']
                if 'events' in ext and isinstance(ext['events'], list):
                    for ev_spec in ext['events']:
                        if isinstance(ev_spec, dict) and 'name' in ev_spec:
                            ev_name = ev_spec['name']
                            if ev_name not in events:
                                events.append(ev_name)
            
            if events or agent_data.get('type') == 'router':  # store router even if zero (so presence is recognized)
                agent_events[agent_name] = events

    # Step 3: Check that for each event transition declared in the workflow 
    # there is a corresponding event in the router agent (error if not)
    errors = []
    router_agent_events = None
    router_agent_name = None

    # Step 3a: Validate event name format and length (15 characters max, ^[A-Za-z_-]+$ pattern)
    import re
    event_name_pattern = re.compile(r'^[A-Za-z_-]+$')
    for event_name, from_agent in workflow_events.items():
        if len(event_name) > 15:
            errors.append(ErrorDetail(
                path=f'transitions[event={event_name}]',
                message=f"Event name '{event_name}' exceeds 15 character limit (length: {len(event_name)}). Use abbreviations for longer agent names."
            ))
        if not event_name_pattern.match(event_name):
            errors.append(ErrorDetail(
                path=f'transitions[event={event_name}]',
                message=f"Event name '{event_name}' contains invalid characters. Only letters, underscores, and hyphens are allowed (pattern: ^[A-Za-z_-]+$). Numbers are NOT allowed."
            ))

    # Prefer explicit type marker from incoming agents_data (backend now sets type='router')
    explicit_router_entries = [a for a in agents_data if isinstance(a, dict) and a.get('type') == 'router']
    if explicit_router_entries:
        # Use the first explicit router entry's name
        router_agent_name = explicit_router_entries[0].get('name')
        # If we already parsed actions for that name, pull them; else leave empty list
        router_agent_events = agent_events.get(router_agent_name, [])
    else:
        # Fallback: retain legacy name-based heuristic (only if explicit type not supplied)
        for agent_name, agent_event_list in agent_events.items():
            if 'router' in agent_name.lower():
                router_agent_events = agent_event_list
                router_agent_name = agent_name
                break

    if router_agent_name is None:
        errors.append(ErrorDetail(
            path='<agents_data>',
            message="No router agent provided (expected entry with type 'router')"
        ))
    else:
        # Validate router event name format and length
        if router_agent_events:
            for event_name in router_agent_events:
                if len(event_name) > 15:
                    errors.append(ErrorDetail(
                        path=f'agent[{router_agent_name}].actions[{event_name}]',
                        message=f"Router event name '{event_name}' exceeds 15 character limit (length: {len(event_name)}). Use abbreviations for longer agent names."
                    ))
                if not event_name_pattern.match(event_name):
                    errors.append(ErrorDetail(
                        path=f'agent[{router_agent_name}].actions[{event_name}]',
                        message=f"Router event name '{event_name}' contains invalid characters. Only letters, underscores, and hyphens are allowed (pattern: ^[A-Za-z_-]+$). Numbers are NOT allowed."
                    ))
        
        # Check each workflow event exists in router agent actions
        for event_name, from_agent in workflow_events.items():
            if event_name not in router_agent_events:
                errors.append(ErrorDetail(
                    path=f'transitions[event={event_name}]',
                    message=f"Event '{event_name}' declared in workflow transition from '{from_agent}' but not found in router agent '{router_agent_name}' actions"
                ))

    # Step 4: Check that for each event declared in router agent, 
    # there is an event transition declared (warning if not)
    warnings = []
    all_workflow_events = set(workflow_events.keys())
    
    if router_agent_events:
        for event_name in router_agent_events:
            if event_name not in all_workflow_events:
                warnings.append(ErrorDetail(
                    path=f'agent[{router_agent_name}].actions[{event_name}]',
                    message=f"Event '{event_name}' declared in router agent '{router_agent_name}' but not used in any workflow transition (warning)"
                ))

    # Combine errors and warnings into the errors list (warnings marked as such in message)
    all_errors = errors + warnings

    return ValidationResult(
        valid=len(errors) == 0,  # Only errors affect validity, not warnings
        errors=all_errors,
        data={
            'workflow_events_found': len(workflow_events),
            'router_agent_found': router_agent_name is not None,
            'router_agent_name': router_agent_name,
            'router_events_found': len(router_agent_events) if router_agent_events else 0,
            'error_count': len(errors),
            'warning_count': len(warnings),
            'workflow_events': workflow_events,  # {event_name: from_agent}
            'router_agent_events': router_agent_events or [],  # [event_names]
            'transition_mappings': [
                {
                    'event': event_name,
                    'from_agent': from_agent,
                    'target_agent': router_agent_name if router_agent_events and event_name in router_agent_events else 'NOT FOUND',
                    'status': '✅' if router_agent_events and event_name in router_agent_events else '❌'
                }
                for event_name, from_agent in workflow_events.items()
            ]
        },
        schema=None
    )


def _cli(argv: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(description='Validate YAML against a JSON schema.')
    p.add_argument('--schema', required=True, help='Path to JSON schema file')
    p.add_argument('--yaml', required=True, help='Path to YAML file to validate')
    p.add_argument('--print-data', action='store_true', help='Print parsed YAML data on success')
    args = p.parse_args(argv)

    result = validate_yaml(args.schema, args.yaml)
    if result.valid:
        print('YAML is valid ✅')
        if args.print_data:
            import pprint
            pprint.pprint(result.data)
        return 0
    else:
        print('YAML is invalid ❌')
        for e in result.errors:
            print(f" - {e.path}: {e.message}")
        return 1


if __name__ == '__main__':  # pragma: no cover
    sys.exit(_cli(sys.argv[1:]))
