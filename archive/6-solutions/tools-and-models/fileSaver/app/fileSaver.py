#!/usr/bin/env python3
import argparse
import os
import ast
import json
import re
from pathlib import Path
from io_utils import setup_session_logger, log_message, log_error, log_step, log_result

def process_content_string(content):
    """Process content string to handle escaped characters like \\n, \\t, etc. and HTML entities."""
    try:
        # Handle HTML entities first (common when arguments are passed through web systems)
        processed = content.replace('&quot;', '"')
        processed = processed.replace('&apos;', "'")
        processed = processed.replace('&lt;', '<')
        processed = processed.replace('&gt;', '>')
        processed = processed.replace('&amp;', '&')  # This should be last among HTML entities
        
        # Handle common escape sequences in the correct order (most specific first)
        # Handle double backslashes first to avoid conflicts
        processed = processed.replace('\\\\', '\x00TEMP_BACKSLASH\x00')  # Temporary placeholder
        
        # Handle other escape sequences
        processed = processed.replace('\\n', '\n')
        processed = processed.replace('\\t', '\t')
        processed = processed.replace('\\r', '\r')
        processed = processed.replace('\\"', '"')
        processed = processed.replace("\\'", "'")
        processed = processed.replace('\\/', '/')  # For JSON
        processed = processed.replace('\\b', '\b')  # Backspace
        processed = processed.replace('\\f', '\f')  # Form feed
        processed = processed.replace('\\v', '\v')  # Vertical tab
        
        # Handle Unicode escape sequences (common in JSON and other formats)
        import re
        unicode_pattern = r'\\u([0-9a-fA-F]{4})'
        processed = re.sub(unicode_pattern, lambda m: chr(int(m.group(1), 16)), processed)
        
        # Restore actual backslashes
        processed = processed.replace('\x00TEMP_BACKSLASH\x00', '\\')
        
        log_message("Content processed to handle escape sequences and HTML entities")
        return processed
    except Exception as e:
        log_error("Error processing content string", e)
        return content

def format_code_content(content, file_extension):
    """Format code content based on file type."""
    try:
        if file_extension == '.py':
            return format_python_code(content)
        elif file_extension == '.json':
            return format_json_content(content)
        elif file_extension in ['.js', '.ts', '.jsx', '.tsx']:
            return format_javascript_code(content)
        elif file_extension in ['.v', '.verilog', '.vh']:
            return format_verilog_code(content)
        elif file_extension in ['.yaml', '.yml']:
            return format_yaml_content(content)
        elif file_extension in ['.xml', '.html', '.htm']:
            return format_xml_content(content)
        elif file_extension in ['.css', '.scss', '.sass']:
            return format_css_content(content)
        elif file_extension in ['.sql']:
            return format_sql_content(content)
        elif file_extension in ['.c', '.cpp', '.h', '.hpp']:
            return format_c_cpp_content(content)
        elif file_extension in ['.java']:
            return format_java_content(content)
        elif file_extension in ['.md', '.markdown']:
            return format_markdown_content(content)
        else:
            # For other file types, just ensure proper line endings
            result = content.strip()
            if result and not result.endswith('\n'):
                result += '\n'
            return result
    except Exception as e:
        log_error(f"Could not format content for {file_extension}", e)
        return content

def format_python_code(content):
    """Format Python code with proper indentation and syntax validation."""
    try:
        # First, validate Python syntax
        ast.parse(content)
        log_message("Python syntax validation passed")
        
        # Use a simple approach: split by lines and ensure proper indentation
        lines = content.split('\n')
        formatted_lines = []
        indent_level = 0
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                formatted_lines.append('')
                continue
            
            # Handle dedent cases first
            if stripped.startswith(('elif ', 'else:', 'except', 'except:', 'finally:')):
                indent_level = max(0, indent_level - 1)
            elif stripped.startswith(('return', 'break', 'continue', 'pass', 'raise')) and not stripped.endswith(':'):
                # These are typically at the current indent level
                pass
            elif stripped == 'else:' or stripped == 'finally:':
                indent_level = max(0, indent_level - 1)
            
            # Special handling for top-level if __name__ == "__main__":
            if stripped.startswith('if __name__ == ') and indent_level > 0:
                # Check if this should be at the top level
                if i > 0:
                    # Look at previous non-empty lines to determine if we should be at top level
                    prev_lines = [l.strip() for l in lines[:i] if l.strip()]
                    if prev_lines and not any(l.startswith(('    ', '\t')) for l in prev_lines[-3:]):
                        indent_level = 0
            
            # Apply current indentation
            formatted_lines.append('    ' * indent_level + stripped)
            
            # Handle indent cases after adding the line
            if stripped.endswith(':'):
                if any(stripped.startswith(keyword) for keyword in 
                    ['def ', 'class ', 'if ', 'elif ', 'else:', 'for ', 'while ', 'try:', 'except', 'finally:', 'with ']):
                    indent_level += 1
        
        result = '\n'.join(formatted_lines)
        
        # Ensure the file ends with a newline
        if not result.endswith('\n'):
            result += '\n'
            
        log_message("Python code formatted successfully")
        return result
        
    except SyntaxError as e:
        log_error(f"Python syntax error detected: {e}", e)
        # Return the content with minimal formatting
        return content.strip() + '\n'
    except Exception as e:
        log_error(f"Error formatting Python code", e)
        return content.strip() + '\n'

def format_json_content(content):
    """Format JSON content with proper indentation."""
    try:
        # Parse and reformat JSON
        parsed = json.loads(content)
        return json.dumps(parsed, indent=2, ensure_ascii=False) + '\n'
    except json.JSONDecodeError as e:
        log_error(f"Invalid JSON format", e)
        return content.strip() + '\n'

def format_javascript_code(content):
    """Basic formatting for JavaScript/TypeScript code."""
    try:
        # Basic formatting: proper line endings and basic indentation
        lines = content.split('\n')
        formatted_lines = []
        indent_level = 0
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                formatted_lines.append('')
                continue
                
            # Count braces for indentation
            open_braces = stripped.count('{')
            close_braces = stripped.count('}')
            
            # Handle closing braces
            if stripped.startswith('}') or stripped.startswith('})'):
                indent_level = max(0, indent_level - 1)
                
            formatted_lines.append('  ' * indent_level + stripped)
            
            # Adjust indent level for next line
            indent_level += (open_braces - close_braces)
            indent_level = max(0, indent_level)
        
        result = '\n'.join(formatted_lines)
        if not result.endswith('\n'):
            result += '\n'
            
        log_message("JavaScript/TypeScript code formatted successfully")
        return result
        
    except Exception as e:
        log_error("Error formatting JavaScript/TypeScript code", e)
        return content.strip() + '\n'

def format_verilog_code(content):
    """Basic formatting for Verilog code."""
    try:
        lines = content.split('\n')
        formatted_lines = []
        indent_level = 0
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                formatted_lines.append('')
                continue
                
            # Handle dedent for 'end' keywords
            if stripped.startswith(('end', 'endmodule', 'endcase', 'endfunction', 'endtask')):
                indent_level = max(0, indent_level - 1)
                
            formatted_lines.append('  ' * indent_level + stripped)
            
            # Handle indent for Verilog constructs
            if any(stripped.startswith(keyword) for keyword in ['module', 'function', 'task', 'case']):
                indent_level += 1
            elif stripped.startswith('begin') or (stripped.startswith('if') and not stripped.endswith(';')):
                indent_level += 1
            elif any(keyword in stripped for keyword in ['always @', 'initial']):
                if 'begin' in stripped:
                    indent_level += 1
        
        result = '\n'.join(formatted_lines)
        if not result.endswith('\n'):
            result += '\n'
            
        log_message("Verilog code formatted successfully")
        return result
        
    except Exception as e:
        log_error("Error formatting Verilog code", e)
        return content.strip() + '\n'

def format_yaml_content(content):
    """Basic formatting for YAML content."""
    try:
        # Basic YAML formatting
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                formatted_lines.append('')
                continue
            
            # Preserve YAML indentation structure
            # Count leading spaces in original line to preserve YAML structure
            original_indent = len(line) - len(line.lstrip())
            formatted_lines.append(' ' * original_indent + stripped)
        
        result = '\n'.join(formatted_lines)
        if not result.endswith('\n'):
            result += '\n'
            
        log_message("YAML content formatted successfully")
        return result
        
    except Exception as e:
        log_error("Error formatting YAML content", e)
        return content.strip() + '\n'

def format_xml_content(content):
    """Basic formatting for XML/HTML content."""
    try:
        lines = content.split('\n')
        formatted_lines = []
        indent_level = 0
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                formatted_lines.append('')
                continue
            
            # Handle closing tags
            if stripped.startswith('</') and not stripped.startswith('<!--'):
                indent_level = max(0, indent_level - 1)
            
            formatted_lines.append('  ' * indent_level + stripped)
            
            # Handle opening tags (but not self-closing or comments)
            if (stripped.startswith('<') and not stripped.startswith('</') and 
                not stripped.startswith('<!--') and not stripped.endswith('/>')):
                if not any(stripped.startswith(tag) for tag in ['<!DOCTYPE', '<!doctype', '<?']):
                    indent_level += 1
        
        result = '\n'.join(formatted_lines)
        if not result.endswith('\n'):
            result += '\n'
            
        log_message("XML/HTML content formatted successfully")
        return result
        
    except Exception as e:
        log_error("Error formatting XML/HTML content", e)
        return content.strip() + '\n'

def format_css_content(content):
    """Basic formatting for CSS content."""
    try:
        lines = content.split('\n')
        formatted_lines = []
        indent_level = 0
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                formatted_lines.append('')
                continue
            
            # Handle closing braces
            if stripped.startswith('}'):
                indent_level = max(0, indent_level - 1)
            
            formatted_lines.append('  ' * indent_level + stripped)
            
            # Handle opening braces
            if stripped.endswith('{'):
                indent_level += 1
        
        result = '\n'.join(formatted_lines)
        if not result.endswith('\n'):
            result += '\n'
            
        log_message("CSS content formatted successfully")
        return result
        
    except Exception as e:
        log_error("Error formatting CSS content", e)
        return content.strip() + '\n'

def format_sql_content(content):
    """Basic formatting for SQL content."""
    try:
        # Basic SQL formatting: uppercase keywords and proper indentation
        import re
        
        # List of common SQL keywords to uppercase
        sql_keywords = [
            'select', 'from', 'where', 'join', 'inner', 'left', 'right', 'outer',
            'on', 'and', 'or', 'not', 'in', 'exists', 'insert', 'into', 'values',
            'update', 'set', 'delete', 'create', 'table', 'alter', 'drop',
            'primary', 'key', 'foreign', 'references', 'constraint', 'index',
            'order', 'by', 'group', 'having', 'limit', 'offset', 'union',
            'case', 'when', 'then', 'else', 'end', 'as', 'distinct', 'count',
            'sum', 'avg', 'max', 'min', 'cast', 'convert'
        ]
        
        formatted = content
        for keyword in sql_keywords:
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(keyword) + r'\b'
            formatted = re.sub(pattern, keyword.upper(), formatted, flags=re.IGNORECASE)
        
        # Ensure proper line endings
        if not formatted.endswith('\n'):
            formatted += '\n'
            
        log_message("SQL content formatted successfully")
        return formatted
        
    except Exception as e:
        log_error("Error formatting SQL content", e)
        return content.strip() + '\n'

def format_c_cpp_content(content):
    """Basic formatting for C/C++ content."""
    try:
        lines = content.split('\n')
        formatted_lines = []
        indent_level = 0
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                formatted_lines.append('')
                continue
            
            # Handle preprocessor directives
            if stripped.startswith('#'):
                formatted_lines.append(stripped)
                continue
            
            # Handle closing braces
            if stripped.startswith('}'):
                indent_level = max(0, indent_level - 1)
            
            formatted_lines.append('    ' * indent_level + stripped)
            
            # Handle opening braces
            if stripped.endswith('{'):
                indent_level += 1
        
        result = '\n'.join(formatted_lines)
        if not result.endswith('\n'):
            result += '\n'
            
        log_message("C/C++ content formatted successfully")
        return result
        
    except Exception as e:
        log_error("Error formatting C/C++ content", e)
        return content.strip() + '\n'

def format_java_content(content):
    """Basic formatting for Java content."""
    try:
        lines = content.split('\n')
        formatted_lines = []
        indent_level = 0
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                formatted_lines.append('')
                continue
            
            # Handle closing braces
            if stripped.startswith('}'):
                indent_level = max(0, indent_level - 1)
            
            formatted_lines.append('    ' * indent_level + stripped)
            
            # Handle opening braces
            if stripped.endswith('{'):
                indent_level += 1
        
        result = '\n'.join(formatted_lines)
        if not result.endswith('\n'):
            result += '\n'
            
        log_message("Java content formatted successfully")
        return result
        
    except Exception as e:
        log_error("Error formatting Java content", e)
        return content.strip() + '\n'

def format_markdown_content(content):
    """Basic formatting for Markdown content."""
    try:
        # Preserve Markdown structure, just ensure proper line endings
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            # Preserve original spacing for Markdown
            formatted_lines.append(line.rstrip())  # Remove trailing whitespace only
        
        result = '\n'.join(formatted_lines)
        if not result.endswith('\n'):
            result += '\n'
            
        log_message("Markdown content formatted successfully")
        return result
        
    except Exception as e:
        log_error("Error formatting Markdown content", e)
        return content.strip() + '\n'


def save_result_to_file(result, output_path):
    """Save result to file with proper formatting based on file type."""
    try:
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Process the result content to handle escaped characters
        processed_content = process_content_string(result)

        # Write processed content to file directly (no validation or formatting)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(processed_content)

        log_result("File saved", output_path)
        log_result("File type", Path(output_path).suffix.lower())
        log_result("Content length", f"{len(processed_content)} characters")
        log_result("Content valid", "Not checked")

    except Exception as e:
        log_error(f"Error saving result to {output_path}", e)
        # Fallback: save without formatting
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result)
            log_message(f"Saved without formatting to {output_path}")
        except Exception as fallback_error:
            log_error("Critical error: Could not save file at all", fallback_error)

def validate_file_name(file_name):
    """Validate and sanitize file name."""
    # Remove any path separators and invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', file_name)
    
    # Ensure file has an extension
    if '.' not in sanitized:
        log_message(f"File name '{file_name}' has no extension. Adding .txt", "WARNING")
        sanitized += '.txt'
    
    return sanitized

def parse_arguments():
    """Parse command-line arguments for results and file name with error handling and validation."""
    parser = argparse.ArgumentParser(description="Save Agent generated results to a file with proper formatting")
    
    parser.add_argument('--file_name', type=str, required=True, help='The name of the file to save the results to')
    parser.add_argument('--results', type=str, required=True, help='The results generated by the Agent (as command line argument)')
    
    log_message("Parsing command line arguments")
    
    try:
        args = parser.parse_args()
        
        # Log the parsed values after successful parsing
        log_message("Successfully parsed arguments")
        log_message(f"File name: {args.file_name}")
        log_message(f"Results length: {len(args.results)} characters")
        log_message(f"Results preview: {args.results[:100]}{'...' if len(args.results) > 100 else ''}")
        
        return args
    except SystemExit as e:
        # This is raised by argparse when it can't parse arguments
        log_error("Failed to parse command line arguments", None)
        log_message("This usually happens when arguments contain unescaped quotes or special characters")
        log_message("Examples:")
        log_message("  python fileio.py --file_name output.txt --results 'content'")
        parser.print_help()
        exit(1)
    except Exception as e:
        log_error("Unexpected error parsing arguments", e)
        parser.print_help()
        exit(1)

def main():
    # Initialize logger for the file I/O session
    setup_session_logger("fileio")
    
    log_step("Starting File I/O Operation")
    
    args = parse_arguments()
    
    # Get the results and file name from command line arguments
    results = args.results
    file_name = args.file_name
    
    # Validate and sanitize file name
    sanitized_file_name = validate_file_name(file_name)
    if sanitized_file_name != file_name:
        log_message(f"File name sanitized from '{file_name}' to '{sanitized_file_name}'", "WARNING")
    
    log_message(f"Saving results to file: {sanitized_file_name}")
    
    # Save results to /app/outputs directory as specified in YAML
    output_dir = "/app/outputs"
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, sanitized_file_name)
    save_result_to_file(results, output_file)
    
    log_step("File I/O Operation Completed")

if __name__ == "__main__":
    main()
