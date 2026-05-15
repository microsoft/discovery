"""
Shared combiner utilities extracted from web_server.combine_script_docs_into_api_doc
Provides a single implementation for both serial and parallel combine flows so outputs match.
"""
import os
import time
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from prompt_loader import get_combine_docs_prompts
from discovery_config_manager import get_global_config_manager
from llm_client import get_llm_completion


def combine_script_docs_shared(script_docs: List[Dict], folder_structure: Dict, conversation_manager: Optional[object], dockerfile_content: str = "") -> str:
    """Combine individual script docs into comprehensive API documentation with folder awareness.
    This is the shared implementation used by both the serial and parallel flows.
    """
    # Load system prompt from prompts/tool-creation/combine_script_docs_into_api_doc.md
    prompts_dir = os.path.join(os.path.dirname(__file__), 'prompts', 'tool-creation')
    combine_prompt_file = os.path.join(prompts_dir, 'combine_script_docs_into_api_doc.md')
    if not os.path.exists(combine_prompt_file):
        raise FileNotFoundError(f"Required prompt file not found: {combine_prompt_file}")
    with open(combine_prompt_file, 'r', encoding='utf-8') as cpf:
        system_prompt = cpf.read()

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
    organized_summary = f"**Project Structure Overview:**\n{folder_summary}\n\n"

    for folder, docs in scripts_by_folder.items():
        organized_summary += f"**{folder.upper()} Folder ({len(docs)} scripts):**\n"
        for doc in docs:
            organized_summary += f"- {doc['script_path']} ({doc['size']} chars):\n{doc['documentation']}\n\n"

    user_prompt = f"""Combine these {len(script_docs)} script documentations into a comprehensive API guide:

**Total Scripts**: {len(script_docs)} across {len(scripts_by_folder)} folders
**Project Structure**: {folder_structure.get('total_files', 0)} total script files

{organized_summary}

Dockerfile (if provided):
```
{dockerfile_content}
```

Create a unified API documentation that:
1. **Project Overview**: What this complete project/tool provides
2. **Folder Organization**: How the project is structured and why
3. **APIs**: Describes ALL public functions and their relationships across folders
4. **Cross-Folder Workflows**: How scripts in different folders work together
5. **Input/Output Specifications**: File formats, data structures, and paths
6. **Usage Examples**: Common patterns and complete workflows
7. **Integration Guide**: How an AI agent should orchestrate these tools

Make it comprehensive yet concise - suitable for generating AI agent instructions that understand the complete project structure."""

    # Determine budgets using conversation_manager
    try:
        if not (conversation_manager and hasattr(conversation_manager, 'max_tokens') and conversation_manager.max_tokens):
            raise RuntimeError('conversation_manager.max_tokens not configured')
        if not (conversation_manager and hasattr(conversation_manager, 'max_output_tokens') and conversation_manager.max_output_tokens):
            raise RuntimeError('conversation_manager.max_output_tokens must be set (no fallback)')

        chosen_max = int(conversation_manager.max_tokens)
        max_output_tokens = int(conversation_manager.max_output_tokens)
    except Exception:
        raise

    # Helper token estimator that prefers conversation_manager.encoder
    def estimate_tokens(text: str) -> int:
        try:
            if conversation_manager and hasattr(conversation_manager, 'encoder') and getattr(conversation_manager, 'encoder'):
                enc = conversation_manager.encoder
                if hasattr(enc, 'encode'):
                    return max(1, len(enc.encode(text)))
                if hasattr(enc, 'encode_ordinary'):
                    return max(1, len(enc.encode_ordinary(text)))
        except Exception:
            pass
        try:
            return max(1, int(len(text) / 4))
        except Exception:
            return 1000

    # Build per-doc text
    per_doc_texts = []
    for d in script_docs:
        header = f"#DOC: {d.get('script_path','unknown')} | folder: {d.get('folder_context','.') } | size: {d.get('size',0)}\n"
        body = d.get('documentation','') or ''
        per_doc_texts.append({'path': d.get('script_path',''), 'folder': d.get('folder_context','.'), 'text': header + body, 'size': len(body)})

    # chunking
    available_input_budget = chosen_max - max_output_tokens
    if available_input_budget <= 0:
        raise RuntimeError(f'Invalid budgets: chosen_max={chosen_max} <= max_output_tokens={max_output_tokens}')

    # Apply a safety fraction to the available input budget.
    # Previously this was hard-coded to 0.95 which leaves only 5% headroom.
    # Prefer a configurable value supplied by conversation_manager (e.g. conversation_manager.safety_fraction)
    # Fall back to a conservative default and clamp to a sensible range to avoid accidental extremes.
    try:
        default_safety = 0.85
        safety_fraction = default_safety
        if conversation_manager is not None:
            # Accept either `safety_fraction` or `SAFETY_FRACTION` attribute if provided
            sf = getattr(conversation_manager, 'safety_fraction', None)
            if sf is None:
                sf = getattr(conversation_manager, 'SAFETY_FRACTION', None)
            if sf is not None:
                safety_fraction = float(sf)
        # Clamp to avoid pathological values (min 0.5 => 50% of input budget, max 0.99)
        safety_fraction = max(0.5, min(0.99, safety_fraction))
    except Exception:
        safety_fraction = 0.85

    chunk_token_limit = int(available_input_budget * safety_fraction)

    total_estimated = estimate_tokens(user_prompt)
    if total_estimated < chunk_token_limit:
        # Single LLM call path
        # Use configured output budget for generation (not the model's total token capacity)
        response = get_llm_completion(system_prompt, user_prompt, session_id="api_doc_generation", max_tokens=max_output_tokens)
        # minimal diagnostics
        try:
            diagnostics = {
                'created_at': datetime.now(timezone.utc).isoformat(),
                'total_docs': len(script_docs),
                'total_chunks': 1,
                'chunking_skipped': True,
                'single_call_estimated_tokens': total_estimated,
                'response_chars': len(response) if response else 0
            }
            diag_dir = os.path.join(os.path.dirname(__file__), 'diagnostics')
            os.makedirs(diag_dir, exist_ok=True)
            diag_file = os.path.join(diag_dir, f"chunk_diag_{int(time.time())}.json")
            with open(diag_file, 'w', encoding='utf-8') as df:
                json.dump(diagnostics, df, indent=2)
        except Exception:
            pass
        return response

    # chunk and merge fallback (structured JSON path)
    chunks = []
    current_chunk = {'items': [], 'text': '' , 'tokens': 0}
    for d in per_doc_texts:
        t = estimate_tokens(d['text'])
        if t > chunk_token_limit:
            if current_chunk['items']:
                chunks.append(current_chunk)
                current_chunk = {'items': [], 'text': '', 'tokens': 0}
            chunks.append({'items':[d], 'text': d['text'], 'tokens': t})
            continue
        if current_chunk['tokens'] + t > chunk_token_limit and current_chunk['items']:
            chunks.append(current_chunk)
            current_chunk = {'items': [], 'text': '', 'tokens': 0}
        current_chunk['items'].append(d)
        current_chunk['text'] += "\n\n" + d['text']
        current_chunk['tokens'] += t
    if current_chunk['items']:
        chunks.append(current_chunk)

    # Structured per-chunk processing - reuse the get_llm_completion function defined above
    parsed_chunks = []

    import json as _json
    chunk_idx = 0
    for c in chunks:
        chunk_idx += 1
        chunk_text = f"Combine the following script documentations and extract all public functions as structured JSON. Only return JSON.\n\n{c['text']}\n\n" + "Dockerfile:\n" + (dockerfile_content or "")
        # Allow a generous per-chunk output up to a reasonable cap; do not starve chunks by dividing strictly by count
        per_chunk_max = min(max_output_tokens, 2048)
        try:
            chunk_resp = get_llm_completion(system_prompt, chunk_text, session_id=f"api_doc_chunk_{chunk_idx}", max_tokens=per_chunk_max)
            parsed = None
            try:
                parsed = _json.loads(chunk_resp)
            except Exception:
                # try to extract JSON candidate
                parsed = None
            parsed_chunks.append({'chunk_index': chunk_idx, 'raw': chunk_resp, 'parsed': parsed, 'error': None, 'duration_seconds': 0, 'docs': [it.get('path') for it in c.get('items', [])], 'est_tokens': c.get('tokens', 0), 'response_chars': len(chunk_resp) if chunk_resp else 0, 'per_chunk_max': per_chunk_max})
        except Exception as e:
            parsed_chunks.append({'chunk_index': chunk_idx, 'raw': '', 'parsed': None, 'error': str(e), 'duration_seconds': 0, 'docs': [it.get('path') for it in c.get('items', [])], 'est_tokens': c.get('tokens', 0), 'per_chunk_max': per_chunk_max})

    # Merge parsed chunks
    merged = {}
    for pc in parsed_chunks:
        p = pc.get('parsed')
        if not p:
            continue
        funcs = p.get('functions') if isinstance(p, dict) and 'functions' in p else (p if isinstance(p, list) else None)
        if not funcs:
            continue
        for f in funcs:
            sig = f.get('signature') or f.get('name')
            if not sig:
                sig = f"{f.get('script','')}::{f.get('name','<unknown>')}"
            key = sig.strip()
            existing = merged.get(key)
            if not existing or len(f.get('description','') or '') > len(existing.get('description','') or ''):
                merged[key] = f

    # Build human-readable merged doc
    merged_doc = []
    merged_doc.append("# API Reference (merged from chunked analysis)\n")
    folder_group = {}
    for k, v in merged.items():
        folder = v.get('folder') or v.get('script','').split('/')[-2] if v.get('script') and '/' in v.get('script') else v.get('folder') or '.'
        folder_group.setdefault(folder, []).append((k, v))

    for folder, items in folder_group.items():
        merged_doc.append(f"## Folder: {folder}\n")
        for k, v in items:
            name = v.get('name') or k
            signature = v.get('signature') or k
            desc = v.get('description') or ''
            examples = v.get('examples') or []
            merged_doc.append(f"""### {name}
```
{signature}
```""")
            if desc:
                merged_doc.append(f"{desc}\n")
            if examples:
                merged_doc.append("Examples:\n")
                for ex in examples:
                    merged_doc.append(f"""```
{ex}
```""")
            merged_doc.append('\n')

    final_merged_text = '\n'.join(merged_doc)

    # Optional organizer pass
    try:
        # Give the organizer a meaningful budget from configured output tokens (cap to 2048)
        organizer_budget = min(2048, max_output_tokens) if max_output_tokens else 1024
        organizer_system = system_prompt
        organizer_user_prompt = f"Organize the following merged API reference into a compact, actionable documentation:\n\n{final_merged_text}"
        org_resp = get_llm_completion(organizer_system, organizer_user_prompt, session_id="api_doc_organize_after_merge", max_tokens=organizer_budget)
        if org_resp and len(org_resp) > 100:
            return org_resp
    except Exception:
        pass

    return final_merged_text
