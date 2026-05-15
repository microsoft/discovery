"""
Script chunking utilities for handling large scripts in tool agent creation.
Provides intelligent chunking that preserves code structure and enables complete API documentation.
"""

import re
from typing import List, Dict, Tuple, Optional, Callable


def estimate_tokens(text: str, encoder=None) -> int:
    """
    Estimate tokens for text using encoder or fallback.
    
    Args:
        text: Text to estimate tokens for
        encoder: Optional encoder object (from conversation_manager)
        
    Returns:
        Estimated token count
    """
    try:
        if encoder:
            if hasattr(encoder, 'encode'):
                return max(1, len(encoder.encode(text)))
            elif hasattr(encoder, 'encode_ordinary'):
                return max(1, len(encoder.encode_ordinary(text)))
    except Exception:
        pass
    
    # Fallback: rough estimate (4 chars per token)
    return max(1, int(len(text) / 4))


def chunk_script_by_structure(script_content: str, max_chunk_tokens: int = 15000, 
                              encoder=None) -> List[Dict]:
    """
    Chunk a script intelligently based on code structure (functions, classes).
    
    Args:
        script_content: The full script content to chunk
        max_chunk_tokens: Maximum tokens per chunk (default 15k to leave room for prompt overhead)
        encoder: Optional encoder for accurate token counting
        
    Returns:
        List of chunk dicts with 'content', 'start_line', 'end_line', 'type', 'tokens'
    """
    # Check if script needs chunking
    total_tokens = estimate_tokens(script_content, encoder)
    if total_tokens <= max_chunk_tokens:
        return [{
            'content': script_content,
            'start_line': 1,
            'end_line': len(script_content.split('\n')),
            'type': 'full',
            'tokens': total_tokens,
            'description': 'Complete script (no chunking needed)'
        }]
    
    lines = script_content.split('\n')
    chunks = []
    
    # Detect language
    is_python = _is_python_script(script_content)
    is_shell = _is_shell_script(script_content)
    
    if is_python:
        chunks = _chunk_python_by_functions(lines, max_chunk_tokens, encoder)
    elif is_shell:
        chunks = _chunk_shell_by_functions(lines, max_chunk_tokens, encoder)
    else:
        # Generic chunking for other languages (JS, TS, etc.)
        chunks = _chunk_by_line_blocks(lines, max_chunk_tokens, encoder)
    
    return chunks


def _is_python_script(content: str) -> bool:
    """Check if script is Python based on content patterns"""
    python_patterns = [
        r'^\s*def\s+\w+\s*\(',
        r'^\s*class\s+\w+',
        r'^\s*import\s+\w+',
        r'^\s*from\s+\w+\s+import',
        r'if\s+__name__\s*==\s*["\']__main__["\']'
    ]
    for pattern in python_patterns:
        if re.search(pattern, content, re.MULTILINE):
            return True
    return False


def _is_shell_script(content: str) -> bool:
    """Check if script is shell/bash based on content patterns"""
    shell_patterns = [
        r'^#!.*(bash|sh|zsh)',
        r'^\s*function\s+\w+',
        r'^\s*\w+\(\)\s*{',
        r'^\s*(if|while|for)\s*\[',
    ]
    for pattern in shell_patterns:
        if re.search(pattern, content, re.MULTILINE):
            return True
    return False


def _chunk_python_by_functions(lines: List[str], max_tokens: int, encoder) -> List[Dict]:
    """Chunk Python code by function/class definitions"""
    chunks = []
    current_chunk_lines = []
    current_chunk_start = 1
    current_tokens = 0
    header_lines = []
    
    # Collect imports and module-level comments as header
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
            header_lines.append(line)
        elif stripped.startswith('import ') or stripped.startswith('from '):
            header_lines.append(line)
        elif not stripped:
            header_lines.append(line)
        else:
            break
        i += 1
    
    header_content = '\n'.join(header_lines)
    header_tokens = estimate_tokens(header_content, encoder)
    
    # Process remaining lines
    function_start = None
    indentation_level = 0
    
    for line_num in range(i, len(lines)):
        line = lines[line_num]
        stripped = line.strip()
        
        # Detect function/class definition
        if re.match(r'^(def|class)\s+\w+', stripped):
            # Save previous chunk if it exists and would exceed limit
            if current_chunk_lines:
                chunk_content = '\n'.join(current_chunk_lines)
                chunk_tokens = estimate_tokens(chunk_content, encoder)
                
                if current_tokens + chunk_tokens + header_tokens > max_tokens and current_chunk_lines:
                    # Flush current chunk
                    full_content = header_content + '\n\n' + chunk_content if header_lines else chunk_content
                    chunks.append({
                        'content': full_content,
                        'start_line': current_chunk_start,
                        'end_line': line_num,
                        'type': 'function_group',
                        'tokens': estimate_tokens(full_content, encoder),
                        'description': f'Lines {current_chunk_start}-{line_num}'
                    })
                    current_chunk_lines = []
                    current_tokens = 0
                    current_chunk_start = line_num + 1
            
            function_start = line_num
            indentation_level = len(line) - len(line.lstrip())
        
        current_chunk_lines.append(line)
    
    # Add final chunk
    if current_chunk_lines:
        chunk_content = '\n'.join(current_chunk_lines)
        full_content = header_content + '\n\n' + chunk_content if header_lines else chunk_content
        chunks.append({
            'content': full_content,
            'start_line': current_chunk_start,
            'end_line': len(lines),
            'type': 'function_group',
            'tokens': estimate_tokens(full_content, encoder),
            'description': f'Lines {current_chunk_start}-{len(lines)}'
        })
    
    # If we only got one chunk and it's still too large, fall back to line-based chunking
    if len(chunks) == 1 and chunks[0]['tokens'] > max_tokens:
        return _chunk_by_line_blocks(lines, max_tokens, encoder)
    
    return chunks


def _chunk_shell_by_functions(lines: List[str], max_tokens: int, encoder) -> List[Dict]:
    """Chunk shell script by function definitions"""
    chunks = []
    current_chunk_lines = []
    current_chunk_start = 1
    current_tokens = 0
    header_lines = []
    
    # Collect shebang and initial comments as header
    i = 0
    while i < len(lines) and i < 20:  # Only check first 20 lines for header
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith('#') or not stripped:
            header_lines.append(line)
        else:
            break
        i += 1
    
    header_content = '\n'.join(header_lines)
    header_tokens = estimate_tokens(header_content, encoder)
    
    # Process remaining lines, looking for function definitions
    in_function = False
    brace_count = 0
    
    for line_num in range(i, len(lines)):
        line = lines[line_num]
        stripped = line.strip()
        
        # Detect function definition (function name() { or name() {)
        if re.match(r'^(function\s+)?\w+\s*\(\s*\)\s*{', stripped):
            # Check if we should start a new chunk
            if current_chunk_lines:
                chunk_content = '\n'.join(current_chunk_lines)
                chunk_tokens = estimate_tokens(chunk_content, encoder)
                
                if current_tokens + chunk_tokens + header_tokens > max_tokens:
                    full_content = header_content + '\n\n' + chunk_content if header_lines else chunk_content
                    chunks.append({
                        'content': full_content,
                        'start_line': current_chunk_start,
                        'end_line': line_num,
                        'type': 'function_group',
                        'tokens': estimate_tokens(full_content, encoder),
                        'description': f'Lines {current_chunk_start}-{line_num}'
                    })
                    current_chunk_lines = []
                    current_tokens = 0
                    current_chunk_start = line_num + 1
            
            in_function = True
            brace_count = line.count('{') - line.count('}')
        elif in_function:
            brace_count += line.count('{') - line.count('}')
            if brace_count <= 0:
                in_function = False
        
        current_chunk_lines.append(line)
    
    # Add final chunk
    if current_chunk_lines:
        chunk_content = '\n'.join(current_chunk_lines)
        full_content = header_content + '\n\n' + chunk_content if header_lines else chunk_content
        chunks.append({
            'content': full_content,
            'start_line': current_chunk_start,
            'end_line': len(lines),
            'type': 'function_group',
            'tokens': estimate_tokens(full_content, encoder),
            'description': f'Lines {current_chunk_start}-{len(lines)}'
        })
    
    # Fallback to line-based if single chunk is too large
    if len(chunks) == 1 and chunks[0]['tokens'] > max_tokens:
        return _chunk_by_line_blocks(lines, max_tokens, encoder)
    
    return chunks


def _chunk_by_line_blocks(lines: List[str], max_tokens: int, encoder) -> List[Dict]:
    """Fallback: chunk by line blocks when structure-based chunking isn't possible"""
    chunks = []
    current_lines = []
    current_tokens = 0
    start_line = 1
    
    for i, line in enumerate(lines, 1):
        line_tokens = estimate_tokens(line, encoder)
        
        if current_tokens + line_tokens > max_tokens and current_lines:
            # Save current chunk
            content = '\n'.join(current_lines)
            chunks.append({
                'content': content,
                'start_line': start_line,
                'end_line': i - 1,
                'type': 'line_block',
                'tokens': current_tokens,
                'description': f'Lines {start_line}-{i-1}'
            })
            current_lines = []
            current_tokens = 0
            start_line = i
        
        current_lines.append(line)
        current_tokens += line_tokens
    
    # Add final chunk
    if current_lines:
        content = '\n'.join(current_lines)
        chunks.append({
            'content': content,
            'start_line': start_line,
            'end_line': len(lines),
            'type': 'line_block',
            'tokens': current_tokens,
            'description': f'Lines {start_line}-{len(lines)}'
        })
    
    return chunks


def merge_chunk_analyses(chunk_results: List[str], script_path: str) -> str:
    """
    Merge multiple chunk analyses into a single comprehensive documentation.
    
    Args:
        chunk_results: List of documentation strings from analyzing each chunk
        script_path: Path of the script being analyzed
        
    Returns:
        Merged documentation string
    """
    if not chunk_results:
        return f"# {script_path}\n\nNo documentation generated."
    
    if len(chunk_results) == 1:
        return chunk_results[0]
    
    # Merge multiple chunks
    merged = [f"# {script_path} (Comprehensive Analysis from {len(chunk_results)} chunks)\n"]
    
    # Try to intelligently merge sections
    all_functions = []
    all_classes = []
    overview_sections = []
    usage_sections = []
    
    for i, result in enumerate(chunk_results, 1):
        # Add chunk marker for debugging
        merged.append(f"\n## Chunk {i} Analysis\n")
        merged.append(result)
        merged.append("\n")
    
    return '\n'.join(merged)
