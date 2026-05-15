#!/usr/bin/env python3
import argparse
import os
import ast
import json
import re
import glob
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
        elif file_extension in ['.sv']:
            return format_systemverilog_code(content)
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

def format_systemverilog_code(content):
    """Basic formatting for SystemVerilog code."""
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
            
        log_message("SystemVerilog code formatted successfully")
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

def read_file_content(file_path, output_format='raw'):
    """Read file content and process it based on the requested output format."""
    try:
        if not os.path.exists(file_path):
            log_error(f"File not found: {file_path}", None)
            return None
        
        log_message(f"Reading file: {file_path}")
        
        # Read the file content
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        file_extension = Path(file_path).suffix.lower()
        file_size = len(content)
        
        log_result("File read", file_path)
        log_result("File type", file_extension if file_extension else "no extension")
        log_result("Content length", f"{file_size} characters")
        
        # Process content based on output format
        if output_format == 'raw':
            # Return content as-is
            processed_content = content
            log_message("Content returned in raw format")
        elif output_format == 'processed':
            # Apply reverse processing (unescape sequences)
            processed_content = reverse_process_content_string(content)
            log_message("Content processed to unescape sequences")
        elif output_format == 'escaped':
            # Escape special characters for safe output
            processed_content = escape_content_for_output(content)
            log_message("Content escaped for safe output")
        else:
            processed_content = content
            log_message("Using raw format (invalid format specified)")
        
        log_result("Output format", output_format)
        log_result("Processed length", f"{len(processed_content)} characters")
        
        return processed_content
        
    except UnicodeDecodeError as e:
        log_error(f"Unicode decode error reading {file_path}. File may be binary or use different encoding.", e)
        return None
    except Exception as e:
        log_error(f"Error reading file {file_path}", e)
        return None

def reverse_process_content_string(content):
    """Reverse the content processing - useful for displaying processed content."""
    try:
        # This function reverses some of the escape sequence processing
        # Handle newlines and tabs for display purposes
        processed = content.replace('\n', '\\n')
        processed = processed.replace('\t', '\\t')
        processed = processed.replace('\r', '\\r')
        processed = processed.replace('"', '\\"')
        processed = processed.replace("'", "\\'")
        
        return processed
    except Exception as e:
        log_error("Error reverse processing content string", e)
        return content

def escape_content_for_output(content):
    """Escape content for safe command-line output."""
    try:
        # Escape characters that might cause issues in command-line output
        escaped = content.replace('\\', '\\\\')
        escaped = escaped.replace('"', '\\"')
        escaped = escaped.replace("'", "\\'")
        escaped = escaped.replace('\n', '\\n')
        escaped = escaped.replace('\t', '\\t')
        escaped = escaped.replace('\r', '\\r')
        
        return escaped
    except Exception as e:
        log_error("Error escaping content for output", e)
        return content

def list_available_files(directory_path, pattern='*'):
    """List available files in the directory matching the pattern."""
    try:
        if not os.path.exists(directory_path):
            log_error(f"Directory not found: {directory_path}", None)
            return []
        
        log_message(f"Listing files in: {directory_path}")
        log_message(f"Pattern: {pattern}")
        
        # Handle different patterns
        if pattern == '*' or pattern == '':
            search_pattern = os.path.join(directory_path, '*')
        else:
            search_pattern = os.path.join(directory_path, pattern)
        
        # Get matching files
        files = glob.glob(search_pattern)
        
        # Filter to only include files (not directories)
        file_list = []
        for file_path in files:
            if os.path.isfile(file_path):
                file_info = {
                    'name': os.path.basename(file_path),
                    'path': file_path,
                    'size': os.path.getsize(file_path),
                    'extension': Path(file_path).suffix.lower()
                }
                file_list.append(file_info)
        
        # Sort by name
        file_list.sort(key=lambda x: x['name'])
        
        log_result("Files found", len(file_list))
        
        # Log file information
        for file_info in file_list:
            log_message(f"  {file_info['name']} ({file_info['size']} bytes, {file_info['extension'] or 'no ext'})")
        
        return file_list
        
    except Exception as e:
        log_error(f"Error listing files in {directory_path}", e)
        return []

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
    """Parse command-line arguments for file operations with error handling and validation."""
    parser = argparse.ArgumentParser(description="File I/O tool for saving and reading files with proper formatting")
    
    # Add operation mode
    parser.add_argument('--operation', type=str, choices=['save', 'read', 'list'], default='save',
                       help='Operation to perform: save (write file), read (read file), or list (list available files)')
    
    # File name is always required
    parser.add_argument('--file_name', type=str, required=True, 
                       help='The name of the file to save/read')
    
    # Results are only required for save operation
    parser.add_argument('--results', type=str, required=False, 
                       help='The results generated by the Agent (required for save operation)')
    
    # Optional arguments for read operations
    parser.add_argument('--output_format', type=str, choices=['raw', 'processed', 'escaped'], default='raw',
                       help='Output format for read operation: raw (as-is), processed (unescape), or escaped (escape special chars)')
    
    log_message("Parsing command line arguments")
    
    try:
        args = parser.parse_args()
        
        # Validate arguments based on operation
        if args.operation == 'save' and not args.results:
            log_error("--results argument is required for save operation", None)
            parser.print_help()
            exit(1)
        
        # Log the parsed values after successful parsing
        log_message("Successfully parsed arguments")
        log_message(f"Operation: {args.operation}")
        log_message(f"File name: {args.file_name}")
        if args.operation == 'save':
            log_message(f"Results length: {len(args.results)} characters")
            log_message(f"Results preview: {args.results[:100]}{'...' if len(args.results) > 100 else ''}")
        elif args.operation == 'read':
            log_message(f"Output format: {args.output_format}")
        
        return args
    except SystemExit as e:
        # This is raised by argparse when it can't parse arguments
        log_error("Failed to parse command line arguments", None)
        log_message("This usually happens when arguments contain unescaped quotes or special characters")
        log_message("Examples:")
        log_message("  Save: python fileSaver.py --operation save --file_name output.txt --results 'content'")
        log_message("  Read: python fileSaver.py --operation read --file_name input.txt")
        log_message("  List: python fileSaver.py --operation list --file_name '*' ")
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
    
    # Set up the working directory
    output_dir = "/app/outputs"
    os.makedirs(output_dir, exist_ok=True)
    
    if args.operation == 'save':
        # Handle save operation
        results = args.results
        file_name = args.file_name
        
        # Validate and sanitize file name
        sanitized_file_name = validate_file_name(file_name)
        if sanitized_file_name != file_name:
            log_message(f"File name sanitized from '{file_name}' to '{sanitized_file_name}'", "WARNING")
        
        log_message(f"Saving results to file: {sanitized_file_name}")
        
        output_file = os.path.join(output_dir, sanitized_file_name)
        save_result_to_file(results, output_file)
        
        log_step("Save Operation Completed")
        
    elif args.operation == 'read':
        # Handle read operation
        file_name = args.file_name
        output_format = args.output_format
        
        # Sanitize file name for reading
        sanitized_file_name = validate_file_name(file_name)
        if sanitized_file_name != file_name:
            log_message(f"File name sanitized from '{file_name}' to '{sanitized_file_name}'", "WARNING")
        
        log_message(f"Reading file: {sanitized_file_name}")
        
        input_file = os.path.join(output_dir, sanitized_file_name)
        content = read_file_content(input_file, output_format)
        
        if content is not None:
            # Output the content (in a real tool, this might be returned to the calling system)
            print("=" * 50)
            print(f"CONTENT OF {sanitized_file_name}")
            print("=" * 50)
            print(content)
            print("=" * 50)
            log_result("Read successful", "Content displayed above")
        else:
            log_error("Failed to read file content", None)
            exit(1)
        
        log_step("Read Operation Completed")
        
    elif args.operation == 'list':
        # Handle list operation
        pattern = args.file_name if args.file_name != '*' else '*'
        
        log_message(f"Listing files with pattern: {pattern}")
        
        files = list_available_files(output_dir, pattern)
        
        if files:
            print("=" * 60)
            print("AVAILABLE FILES")
            print("=" * 60)
            print(f"{'Name':<30} {'Size':<10} {'Extension':<10}")
            print("-" * 60)
            for file_info in files:
                print(f"{file_info['name']:<30} {file_info['size']:<10} {file_info['extension'] or 'none':<10}")
            print("=" * 60)
            log_result("Files listed", len(files))
        else:
            print("No files found matching the pattern.")
            log_result("Files found", 0)
        
        log_step("List Operation Completed")
    
    else:
        log_error(f"Unknown operation: {args.operation}", None)
        exit(1)

if __name__ == "__main__":
    main()