/**
 * File and Language Utilities
 * Utilities for file content formatting, language detection, and related operations
 */

class FileUtils {
    /**
     * Simple delay utility
     * @param {number} ms - Milliseconds to delay
     * @returns {Promise} - Promise that resolves after the delay
     */
    static delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * Format file content with appropriate syntax highlighting and structure
     * @param {string} content - The file content to format
     * @param {string} filename - The filename to determine formatting
     * @returns {string} - HTML formatted content
     */
    static formatFileContent(content, filename) {
        const extension = filename.split('.').pop().toLowerCase();
        
        // Determine if this file should have syntax highlighting
        const codeExtensions = {
            'qs': 'qsharp',
            'py': 'python',
            'js': 'javascript',
            'ts': 'typescript',
            'json': 'json',
            'yaml': 'yaml',
            'yml': 'yaml',
            'sh': 'bash',
            'bash': 'bash',
            'css': 'css',
            'html': 'html',
            'xml': 'xml',
            'sql': 'sql',
            'md': 'markdown'
        };
        
        const language = codeExtensions[extension] || FileUtils.detectLanguage(content);
        
        // For code files with syntax highlighting
        if (language) {
            let formattedContent = content;
            
            // Special formatting for JSON files
            if (language === 'json') {
                try {
                    const jsonObj = JSON.parse(content);
                    formattedContent = JSON.stringify(jsonObj, null, 2);
                } catch (e) {
                    // If JSON parsing fails, use original content
                    formattedContent = content;
                }
            }
            
            const pre = document.createElement('pre');
            const code = document.createElement('code');
            if (language && language !== 'plaintext') {
                code.className = `language-${language}`;
            }
            code.textContent = formattedContent;
            pre.appendChild(code);
            
            // Apply syntax highlighting
            if (typeof Prism !== 'undefined') {
                Prism.highlightElement(code);
            }
            
            return pre.outerHTML;
        }
        
        // For common text-based formats (excluding JSON which is handled above)
        if (['txt', 'log', 'out', 'xyz', 'pdb', 'mol', 'sdf', 'fcidump', 'dat', 'inp', 'cfg'].includes(extension)) {
            return `<pre>${content}</pre>`;
        }
        
        // For other formats, show first few lines with a note (preserve line breaks)
        const lines = content.split('\n');
        if (lines.length > 50) {
            return `<pre>${lines.slice(0, 50).join('\n')}\n\n... (truncated, download file to see full content)</pre>`;
        }
        
        return `<pre>${content}</pre>`;
    }
    
    /**
     * Detect programming language from code content
     * @param {string} code - The code content to analyze
     * @returns {string} - Detected language identifier
     */
    static detectLanguage(code) {
        // Trim whitespace and get first few lines for analysis
        const trimmedCode = code.trim();
        const lines = trimmedCode.split('\n');
        const firstLine = lines[0]?.trim() || '';
        const codeStart = lines.slice(0, 5).join('\n');
        const codeStartLower = codeStart.toLowerCase();
        
        // Python detection patterns - check first for higher priority
        if (
            firstLine.startsWith('#!') && firstLine.includes('python') ||
            /^#!/.test(firstLine) && /python/.test(firstLine) ||
            /^from\s+\w+\s+import/.test(firstLine) ||
            /^import\s+\w+/.test(firstLine) ||
            /def\s+\w+\s*\(/.test(codeStart) ||
            /class\s+\w+\s*[\(:]/.test(codeStart) ||
            /if\s+__name__\s*==\s*['"']__main__['"]/.test(codeStart) ||
            /print\s*\(/.test(codeStart) ||
            /^\s*#.*python/i.test(firstLine) ||
            /import\s+(numpy|pandas|matplotlib|scipy|sklearn|torch|tensorflow)/.test(codeStart) ||
            /from\s+(numpy|pandas|matplotlib|scipy|sklearn|torch|tensorflow|pyscf)/.test(codeStart)
        ) {
            return 'python';
        }
        
        // Q# detection patterns - more specific patterns to avoid conflicts
        if (
            /^qsharp\s*$/.test(firstLine) ||
            /namespace\s+\w+(\.\w+)*\s*\{/.test(codeStart) ||
            /operation\s+\w+\s*\(/.test(codeStart) ||
            /function\s+\w+\s*\(.*\)\s*:\s*\w+/.test(codeStart) ||
            /open\s+microsoft\.quantum/.test(codeStartLower) ||
            /qubit\[\]/.test(codeStart) ||
            /using\s*\(.*qubit/.test(codeStartLower) ||
            /controlled\s+\w+\s*\(/.test(codeStartLower) ||
            /adjoint\s+\w+\s*\(/.test(codeStartLower) ||
            /is\s+adj\s*\+\s*ctl/.test(codeStartLower) ||
            /result\[\]/.test(codeStart) ||
            /use\s+\w+\s*=\s*qubit/.test(codeStartLower) ||
            /within\s*\{/.test(codeStart) ||
            (/let\s+\w+\s*=/.test(codeStart) && /qubit|result|pauli/i.test(codeStart)) ||
            // More specific quantum gate patterns
            (/h\s*\(/.test(codeStartLower) && /qubit/.test(codeStartLower)) ||
            (/m\s*\(/.test(codeStartLower) && /qubit/.test(codeStartLower)) ||
            (/x\s*\(/.test(codeStartLower) && /qubit/.test(codeStartLower)) ||
            (/z\s*\(/.test(codeStartLower) && /qubit/.test(codeStartLower)) ||
            /cnot\s*\(/.test(codeStartLower)
        ) {
            return 'qsharp';
        }
        
        // JavaScript detection
        if (
            /^const\s+\w+/.test(firstLine) ||
            /^let\s+\w+/.test(firstLine) ||
            /^var\s+\w+/.test(firstLine) ||
            /function\s+\w+\s*\(/.test(codeStart) ||
            /=>\s*{/.test(codeStart) ||
            /console\.log\s*\(/.test(codeStart) ||
            /require\s*\(/.test(codeStart)
               ) {
            return 'javascript';
        }
        
        // Bash/Shell detection
        // IMPORTANT: Do NOT match strings starting with flags (--name, -f) as those are
        // incomplete commands likely missing their interpreter (python3, bash, etc.)
        const startsWithFlag = firstLine.startsWith('-');

        if (
            firstLine.startsWith('#!/bin/bash') ||
            firstLine.startsWith('#!/bin/sh') ||
            /^\$\s+/.test(firstLine) ||
            /^echo\s+/.test(firstLine) ||
            // Detect common command-line tools
            /^(python3?|node|npm|pip|conda|docker|kubectl|bash|sh|curl|wget|git|make|cmake|gcc|g\+\+|javac|java|mvn|gradle)\s+/.test(firstLine) ||
            // Detect commands with flags (but command must not itself be a flag)
            (!startsWithFlag && /^[\w\/]+\s+--/.test(firstLine)) ||
            // Detect single-line CLI commands: word followed by quoted string or flags
            // Pattern: command "args" or command 'args' or command --flag
            // But NOT if it starts with a flag (--name, -f)
            (lines.length === 1 && !startsWithFlag && /^[a-zA-Z][\w-]*\s+["']/.test(firstLine)) ||
            (lines.length === 1 && !startsWithFlag && /^[a-zA-Z][\w-]*\s+-/.test(firstLine)) ||
            // Shell operators in single line (but not if starts with flag)
            (lines.length === 1 && !startsWithFlag && (/\|/.test(firstLine) || /&&/.test(firstLine) || />>?/.test(firstLine)))
        ) {
            return 'bash';
        }

        // Check if code starts with a flag (--name, -f) - this indicates an incomplete command
        // that's likely missing its interpreter (python3, bash, etc.)
        if (startsWithFlag) {
            // This looks like command-line arguments without the command itself
            // Return plaintext so server-side detection handles it (defaults to python)
            return 'plaintext';
        }

        // YAML detection
        if (
            /^---/.test(firstLine) ||
            /^\w+:\s*/.test(firstLine) ||
            /^\s*-\s+\w+/.test(firstLine)
        ) {
            return 'yaml';
        }

        // For single-line code that doesn't match any known language pattern,
        // treat it as a shell command (CLI invocation) rather than plaintext
        // But only if it looks like a command (starts with a word, not a flag)
        if (lines.length === 1 && /^[a-zA-Z][\w-]*\s+/.test(firstLine)) {
            return 'bash';
        }

        // Default to plaintext for unknown types
        return 'plaintext';
    }
    
    /**
     * Normalize language aliases to standard identifiers
     * @param {string} language - The language string to normalize
     * @returns {string} - Normalized language identifier
     */
    static normalizeLanguage(language) {
        // Normalize language aliases to standard language identifiers
        const languageAliases = {
            'py': 'python',
            'js': 'javascript',
            'ts': 'typescript',
            'sh': 'bash',
            'shell': 'bash',
            'qs': 'qsharp',
            'qsharp': 'qsharp',
            'yml': 'yaml',
            'md': 'markdown',
            'htm': 'html'
        };
        
        const normalizedLang = language.toLowerCase();
        return languageAliases[normalizedLang] || normalizedLang;
    }
    
    /**
     * Get display name for a programming language
     * @param {string} language - The language identifier
     * @returns {string} - Human-readable language name
     */
    static getLanguageDisplayName(language) {
        const languageMap = {
            'qsharp': 'Q#',
            'python': 'Python',
            'javascript': 'JavaScript',
            'typescript': 'TypeScript',
            'bash': 'Bash',
            'shell': 'Shell',
            'yaml': 'YAML',
            'json': 'JSON',
            'html': 'HTML',
            'css': 'CSS',
            'sql': 'SQL',
            'xml': 'XML',
            'markdown': 'Markdown',
            'plaintext': 'Text',
            'c': 'C',
            'cpp': 'C++',
            'csharp': 'C#',
            'java': 'Java',
            'go': 'Go',
            'rust': 'Rust',
            'php': 'PHP',
            'ruby': 'Ruby',
            'swift': 'Swift',
            'kotlin': 'Kotlin',
            'r': 'R',
            'matlab': 'MATLAB',
            'perl': 'Perl',
            'powershell': 'PowerShell',
            'dockerfile': 'Dockerfile'
        };
        
        return languageMap[language] || (language ? language.charAt(0).toUpperCase() + language.slice(1) : 'Code');
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = FileUtils;
}
