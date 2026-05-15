"""
File Utilities for Robust Encoding Handling

Provides utilities for loading YAML and other text files with:
- Automatic encoding detection with fallback
- Character normalization (smart quotes, special symbols)
- Detailed error messages with encoding information
- Validation of loaded content

This module helps prevent encoding errors like 'charmap' codec errors
that occur when files contain UTF-8 characters but are read with default encoding.
"""

import yaml
import unicodedata
import os
import re
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass
import logging

# Try to import chardet for encoding detection
try:
    import chardet
    HAS_CHARDET = True
except ImportError:
    HAS_CHARDET = False

logger = logging.getLogger(__name__)


class FileEncodingError(Exception):
    """Exception raised when file cannot be loaded with any encoding"""
    pass


def normalize_smart_quotes(text: str) -> str:
    """
    Normalize smart quotes and special characters to ASCII equivalents.
    
    Replaces:
    - Smart quotes (" " ' ') with straight quotes (" ')
    - Em/en dashes (— –) with hyphens (-)
    - Ellipsis (…) with three dots (...)
    - Other common typographic characters
    
    Args:
        text: Input text with potential smart characters
        
    Returns:
        Text with ASCII equivalents
    """
    replacements = {
        # Smart quotes
        '\u201c': '"',  # Left double quote
        '\u201d': '"',  # Right double quote
        '\u2018': "'",  # Left single quote
        '\u2019': "'",  # Right single quote
        '\u201a': "'",  # Single low quote
        '\u201e': '"',  # Double low quote
        
        # Dashes
        '\u2013': '-',  # En dash
        '\u2014': '-',  # Em dash
        '\u2015': '-',  # Horizontal bar
        
        # Other punctuation
        '\u2026': '...',  # Ellipsis
        '\u2022': '*',    # Bullet
        '\u00b7': '*',    # Middle dot
        
        # Math symbols
        '\u2212': '-',    # Minus sign
        '\u00d7': 'x',    # Multiplication sign
        '\u00f7': '/',    # Division sign
        '\u2260': '!=',   # Not equal
        '\u2264': '<=',   # Less than or equal
        '\u2265': '>=',   # Greater than or equal
        '\u00b1': '+/-',  # Plus-minus
        
        # Arrows
        '\u2190': '<-',   # Left arrow
        '\u2192': '->',   # Right arrow
        '\u2194': '<->',  # Left-right arrow
    }
    
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    
    return text


# =============================================================================
# Emoji Detection and Handling
# =============================================================================

@dataclass
class EmojiMatch:
    """Represents a single emoji found in text."""
    emoji: str
    position: int
    line: int
    column: int
    suggested_replacement: Optional[str] = None


@dataclass
class EmojiDetectionResult:
    """Result of emoji detection in text."""
    has_emojis: bool
    emojis: List[EmojiMatch]
    emoji_count: int
    unique_emojis: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'has_emojis': self.has_emojis,
            'emoji_count': self.emoji_count,
            'unique_emojis': self.unique_emojis,
            'emojis': [
                {
                    'emoji': e.emoji,
                    'position': e.position,
                    'line': e.line,
                    'column': e.column,
                    'suggested_replacement': e.suggested_replacement
                }
                for e in self.emojis
            ]
        }


# Common emoji to ASCII replacement mapping
# Only includes direct ASCII equivalents; most emojis are removed (empty string)
EMOJI_ASCII_REPLACEMENTS: Dict[str, str] = {
    # ==========================================================================
    # DIRECT ASCII EQUIVALENTS (keep these)
    # ==========================================================================

    # Arrows - have clear ASCII representations
    '\u27a1': '->',             # ➡ right arrow
    '\u2b05': '<-',             # ⬅ left arrow
    '\u2b06': '^',              # ⬆ up arrow
    '\u2b07': 'v',              # ⬇ down arrow
    '\u21a9': '<-',             # ↩ return arrow
    '\u21aa': '->',             # ↪ forward arrow
    '\u2192': '->',             # → right arrow
    '\u2190': '<-',             # ← left arrow
    '\u2191': '^',              # ↑ up arrow
    '\u2193': 'v',              # ↓ down arrow
    '\u2194': '<->',            # ↔ left-right arrow

    # Numbers in circles - clear ASCII equivalent
    '\u2460': '(1)',            # ①
    '\u2461': '(2)',            # ②
    '\u2462': '(3)',            # ③
    '\u2463': '(4)',            # ④
    '\u2464': '(5)',            # ⑤
    '\u2465': '(6)',            # ⑥
    '\u2466': '(7)',            # ⑦
    '\u2467': '(8)',            # ⑧
    '\u2468': '(9)',            # ⑨
    '\u2469': '(10)',           # ⑩

    # Basic punctuation/symbols with ASCII equivalents
    '\u2022': '-',              # • bullet -> dash
    '\u00b7': '-',              # · middle dot -> dash
    '\u2713': '*',              # ✓ check mark -> asterisk
    '\u2714': '*',              # ✔ heavy check mark -> asterisk
    '\u2717': 'x',              # ✗ ballot x -> x
    '\u2718': 'x',              # ✘ heavy ballot x -> x
    '\u2212': '-',              # − minus sign -> hyphen
    '\u00d7': 'x',              # × multiplication -> x
    '\u00f7': '/',              # ÷ division -> slash

    # ==========================================================================
    # REMOVE (no direct ASCII equivalent) - map to empty string
    # ==========================================================================

    # Status indicators - remove
    '\u2705': '',               # ✅ check mark button
    '\u274c': '',               # ❌ cross mark
    '\u26a0': '',               # ⚠ warning
    '\u2757': '',               # ❗ exclamation
    '\u2753': '',               # ❓ question
    '\u2139': '',               # ℹ info
    '\u23f3': '',               # ⏳ hourglass
    '\u231b': '',               # ⌛ hourglass done

    # Common pictographic symbols - remove
    '\u2728': '',               # ✨ sparkles
    '\u26a1': '',               # ⚡ lightning
    '\u2764': '',               # ❤ heart
    '\U0001F4A1': '',           # 💡 lightbulb
    '\U0001F50D': '',           # 🔍 magnifying glass
    '\U0001F4DD': '',           # 📝 memo
    '\U0001F4E6': '',           # 📦 package
    '\U0001F527': '',           # 🔧 wrench
    '\U0001F6E0': '',           # 🛠 tools
    '\U0001F4C1': '',           # 📁 folder
    '\U0001F4C4': '',           # 📄 document
    '\U0001F517': '',           # 🔗 link
    '\U0001F512': '',           # 🔒 lock
    '\U0001F513': '',           # 🔓 unlock
    '\U0001F510': '',           # 🔐 locked with key

    # Science/chemistry - remove
    '\u2697': '',               # ⚗ alembic
    '\U0001F9EA': '',           # 🧪 test tube
    '\U0001F9EC': '',           # 🧬 DNA
    '\U0001F52C': '',           # 🔬 microscope
    '\U0001F52D': '',           # 🔭 telescope
    '\u2699': '',               # ⚙ gear
    '\u269b': '',               # ⚛ atom

    # Computing - remove
    '\U0001F4BB': '',           # 💻 laptop
    '\U0001F5A5': '',           # 🖥 desktop
    '\u2328': '',               # ⌨ keyboard
    '\U0001F4BE': '',           # 💾 floppy disk
    '\U0001F4BF': '',           # 💿 CD
    '\U0001F310': '',           # 🌐 globe
    '\u2601': '',               # ☁ cloud

    # Misc pictographic - remove
    '\U0001F389': '',           # 🎉 party popper
    '\U0001F680': '',           # 🚀 rocket
    '\U0001F3C1': '',           # 🏁 checkered flag
    '\U0001F4A5': '',           # 💥 collision
    '\U0001F4AF': '',           # 💯 hundred points
    '\U0001F44D': '',           # 👍 thumbs up
    '\U0001F44E': '',           # 👎 thumbs down
    '\U0001F64F': '',           # 🙏 folded hands
    '\u270d': '',               # ✍ writing hand
}


def _is_emoji(char: str) -> bool:
    """
    Check if a character is an emoji.

    Uses Unicode categories and specific emoji ranges to detect emojis.

    Args:
        char: Single character to check

    Returns:
        True if character is an emoji
    """
    if not char:
        return False

    # Get the Unicode codepoint
    codepoint = ord(char[0]) if len(char) > 0 else 0

    # Check Unicode category - 'So' is "Symbol, Other" which includes many emojis
    category = unicodedata.category(char[0]) if len(char) > 0 else ''

    # Emoji and special character ranges to detect
    emoji_ranges = [
        (0x1F300, 0x1F9FF),   # Miscellaneous Symbols and Pictographs, Emoticons, etc.
        (0x2600, 0x26FF),     # Miscellaneous Symbols
        (0x2700, 0x27BF),     # Dingbats
        (0x1F600, 0x1F64F),   # Emoticons
        (0x1F680, 0x1F6FF),   # Transport and Map Symbols
        (0x1F1E0, 0x1F1FF),   # Regional Indicator Symbols (flags)
        (0x2300, 0x23FF),     # Miscellaneous Technical
        (0x2B50, 0x2B55),     # Stars and circles
        (0x3030, 0x3030),     # Wavy dash
        (0x303D, 0x303D),     # Part alternation mark
        (0x3297, 0x3299),     # Circled Ideographs
        (0x1FA00, 0x1FAFF),   # Chess, symbols, etc.
        (0x2460, 0x24FF),     # Enclosed Alphanumerics (circled numbers)
        (0xFE00, 0xFE0F),     # Variation Selectors
        (0x200D, 0x200D),     # Zero Width Joiner (used in compound emojis)
        (0x2190, 0x21FF),     # Arrows (← → ↑ ↓ etc.)
        (0x2010, 0x2027),     # General punctuation (dashes, bullets)
        (0x00D7, 0x00D7),     # × multiplication sign
        (0x00F7, 0x00F7),     # ÷ division sign
        (0x2212, 0x2212),     # − minus sign
    ]

    for start, end in emoji_ranges:
        if start <= codepoint <= end:
            return True

    # Also check for Symbol categories that might be emojis
    if category in ('So', 'Sk') and codepoint > 0x2000:
        return True

    return False


def detect_emojis(text: str) -> EmojiDetectionResult:
    """
    Detect emojis in text and return their locations.

    Scans through text to find all emoji characters and returns detailed
    information about each occurrence including line/column positions and
    suggested ASCII replacements.

    Args:
        text: Text to scan for emojis

    Returns:
        EmojiDetectionResult with details about found emojis
    """
    emojis: List[EmojiMatch] = []
    unique_set: set = set()

    line = 1
    column = 1

    # Handle multi-codepoint emojis (like flags, skin tones, ZWJ sequences)
    # by using a regex pattern for extended emoji sequences
    # This pattern matches most emoji including compound ones
    emoji_pattern = re.compile(
        r'[\U0001F300-\U0001F9FF]'  # Misc symbols, emoticons, etc.
        r'|[\U00002600-\U000026FF]'  # Misc symbols
        r'|[\U00002700-\U000027BF]'  # Dingbats
        r'|[\U0001F600-\U0001F64F]'  # Emoticons
        r'|[\U0001F680-\U0001F6FF]'  # Transport
        r'|[\U0001F1E0-\U0001F1FF]'  # Flags
        r'|[\U00002300-\U000023FF]'  # Misc technical
        r'|[\U00002460-\U000024FF]'  # Enclosed alphanumerics
        r'|[\U0001FA00-\U0001FAFF]'  # Extended symbols
        r'|[\U00002B50-\U00002B55]'  # Stars
    )

    # Track position while iterating
    pos = 0
    for i, char in enumerate(text):
        if char == '\n':
            line += 1
            column = 1
        else:
            # Check if this character is an emoji
            if _is_emoji(char):
                replacement = EMOJI_ASCII_REPLACEMENTS.get(char)
                emojis.append(EmojiMatch(
                    emoji=char,
                    position=i,
                    line=line,
                    column=column,
                    suggested_replacement=replacement
                ))
                unique_set.add(char)
            column += 1

    return EmojiDetectionResult(
        has_emojis=len(emojis) > 0,
        emojis=emojis,
        emoji_count=len(emojis),
        unique_emojis=list(unique_set)
    )


def detect_emojis_in_yaml_fields(yaml_data: Any, path: str = '') -> List[Dict[str, Any]]:
    """
    Recursively detect emojis in YAML data structure fields.

    Walks through a parsed YAML structure and detects emojis in string values,
    returning the field path where each emoji was found.

    Args:
        yaml_data: Parsed YAML data (dict, list, or scalar)
        path: Current path in the YAML structure (for nested fields)

    Returns:
        List of dicts with 'path', 'field', 'emoji_result' for each field containing emojis
    """
    results = []

    if isinstance(yaml_data, dict):
        for key, value in yaml_data.items():
            current_path = f"{path}.{key}" if path else key

            # Check the key itself for emojis
            key_result = detect_emojis(str(key))
            if key_result.has_emojis:
                results.append({
                    'path': path or '<root>',
                    'field': f'key: {key}',
                    'emoji_result': key_result.to_dict()
                })

            # Recursively check value
            if isinstance(value, str):
                value_result = detect_emojis(value)
                if value_result.has_emojis:
                    results.append({
                        'path': current_path,
                        'field': key,
                        'emoji_result': value_result.to_dict()
                    })
            else:
                results.extend(detect_emojis_in_yaml_fields(value, current_path))

    elif isinstance(yaml_data, list):
        for i, item in enumerate(yaml_data):
            current_path = f"{path}[{i}]"
            if isinstance(item, str):
                item_result = detect_emojis(item)
                if item_result.has_emojis:
                    results.append({
                        'path': current_path,
                        'field': f'item[{i}]',
                        'emoji_result': item_result.to_dict()
                    })
            else:
                results.extend(detect_emojis_in_yaml_fields(item, current_path))

    return results


def replace_emojis_with_ascii(text: str, unknown_replacement: str = '') -> Tuple[str, int]:
    """
    Replace emojis in text with ASCII equivalents or remove them.

    Uses the EMOJI_ASCII_REPLACEMENTS mapping for known emojis.
    Emojis with direct ASCII equivalents (arrows, circled numbers) are replaced.
    Pictographic emojis without direct equivalents are removed by default.

    Args:
        text: Text containing emojis
        unknown_replacement: Replacement for emojis not in the mapping (default: remove)

    Returns:
        Tuple of (replaced_text, replacement_count)
    """
    result = []
    replacement_count = 0

    for char in text:
        if _is_emoji(char):
            replacement = EMOJI_ASCII_REPLACEMENTS.get(char, unknown_replacement)
            result.append(replacement)
            replacement_count += 1
        else:
            result.append(char)

    return ''.join(result), replacement_count


def detect_encoding(file_path: str) -> Tuple[str, float]:
    """
    Detect file encoding using chardet library (if available).
    
    Args:
        file_path: Path to the file
        
    Returns:
        Tuple of (encoding, confidence) where confidence is 0.0-1.0
    """
    if not HAS_CHARDET:
        logger.debug("chardet not available, skipping encoding detection")
        return 'utf-8', 0.0
    
    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read()
        
        result = chardet.detect(raw_data)
        encoding = result.get('encoding', 'utf-8')
        confidence = result.get('confidence', 0.0)
        
        logger.debug(f"Detected encoding for {file_path}: {encoding} (confidence: {confidence:.2f})")
        
        return encoding, confidence
    except Exception as e:
        logger.warning(f"Failed to detect encoding for {file_path}: {e}")
        return 'utf-8', 0.0


def load_text_file_robust(
    file_path: str,
    encodings: Optional[list] = None,
    normalize_chars: bool = False,
    errors: str = 'strict'
) -> str:
    """
    Load a text file with robust encoding handling.
    
    Tries multiple encodings in order:
    1. UTF-8 (most common)
    2. Detected encoding (via chardet)
    3. UTF-8 with BOM
    4. Latin-1 (fallback that never fails)
    5. CP1252 (Windows default)
    6. Additional encodings if provided
    
    Args:
        file_path: Path to the file to load
        encodings: Optional list of additional encodings to try
        normalize_chars: If True, normalize smart quotes and special chars to ASCII
        errors: How to handle encoding errors ('strict', 'replace', 'ignore')
        
    Returns:
        File content as string
        
    Raises:
        FileEncodingError: If file cannot be loaded with any encoding
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    # Build list of encodings to try
    detected_encoding, confidence = detect_encoding(file_path)
    
    encodings_to_try = [
        'utf-8',
        'utf-8-sig',  # UTF-8 with BOM
    ]
    
    # Add detected encoding if confidence is reasonable
    if detected_encoding and confidence > 0.7 and detected_encoding not in encodings_to_try:
        encodings_to_try.insert(1, detected_encoding)
    
    # Add common fallbacks
    encodings_to_try.extend([
        'cp1252',  # Windows default
        'latin-1',  # ISO-8859-1 (never fails for any byte sequence)
    ])
    
    # Add any user-specified encodings
    if encodings:
        for enc in encodings:
            if enc not in encodings_to_try:
                encodings_to_try.append(enc)
    
    # Try each encoding
    last_error = None
    for encoding in encodings_to_try:
        try:
            with open(file_path, 'r', encoding=encoding, errors=errors) as f:
                content = f.read()
            
            logger.debug(f"Successfully loaded {file_path} with encoding: {encoding}")
            
            # Normalize characters if requested
            if normalize_chars:
                content = normalize_smart_quotes(content)
                logger.debug(f"Normalized special characters in {file_path}")
            
            return content
            
        except (UnicodeDecodeError, UnicodeError) as e:
            last_error = e
            logger.debug(f"Failed to load {file_path} with {encoding}: {e}")
            continue
        except Exception as e:
            last_error = e
            logger.warning(f"Unexpected error loading {file_path} with {encoding}: {e}")
            continue
    
    # If we get here, all encodings failed
    error_msg = (
        f"Failed to load file with any encoding: {file_path}\n"
        f"Tried encodings: {', '.join(encodings_to_try)}\n"
        f"Last error: {last_error}\n"
        f"Detected encoding: {detected_encoding} (confidence: {confidence:.2f})\n"
        f"Suggestion: Try opening the file in a text editor and re-saving as UTF-8"
    )
    raise FileEncodingError(error_msg)


def load_yaml_robust(
    file_path: str,
    encodings: Optional[list] = None,
    normalize_chars: bool = False
) -> Dict[str, Any]:
    """
    Load a YAML file with robust encoding handling.
    
    Args:
        file_path: Path to the YAML file
        encodings: Optional list of additional encodings to try
        normalize_chars: If True, normalize smart quotes and special chars before parsing
        
    Returns:
        Parsed YAML content as dictionary
        
    Raises:
        FileEncodingError: If file cannot be loaded with any encoding
        yaml.YAMLError: If file cannot be parsed as valid YAML
    """
    try:
        # Load with robust encoding
        content = load_text_file_robust(
            file_path,
            encodings=encodings,
            normalize_chars=normalize_chars
        )
        
        # Parse YAML
        try:
            data = yaml.safe_load(content)
            return data if data is not None else {}
        except yaml.YAMLError as e:
            # Provide helpful error message with line/column info
            error_msg = f"Failed to parse YAML file: {file_path}\n{str(e)}"
            logger.error(error_msg)
            raise yaml.YAMLError(error_msg) from e
            
    except FileEncodingError:
        raise
    except Exception as e:
        error_msg = f"Unexpected error loading YAML file: {file_path}\n{str(e)}"
        logger.error(error_msg)
        raise


def save_yaml_utf8(
    file_path: str,
    data: Dict[str, Any],
    normalize_chars: bool = False
) -> None:
    """
    Save a dictionary as YAML with UTF-8 encoding.
    
    Args:
        file_path: Path where to save the YAML file
        data: Dictionary to save
        normalize_chars: If True, normalize smart quotes in string values before saving
        
    Raises:
        IOError: If file cannot be written
    """
    try:
        # Normalize characters if requested
        if normalize_chars:
            data = _normalize_dict_strings(data)
        
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)
        
        # Write with explicit UTF-8 encoding
        with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        
        logger.debug(f"Saved YAML file with UTF-8 encoding: {file_path}")
        
    except Exception as e:
        error_msg = f"Failed to save YAML file: {file_path}\n{str(e)}"
        logger.error(error_msg)
        raise IOError(error_msg) from e


def _normalize_dict_strings(obj: Any) -> Any:
    """Recursively normalize strings in a dictionary/list structure"""
    if isinstance(obj, dict):
        return {k: _normalize_dict_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_normalize_dict_strings(item) for item in obj]
    elif isinstance(obj, str):
        return normalize_smart_quotes(obj)
    else:
        return obj


def validate_yaml_file(file_path: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that a file can be loaded and parsed as YAML.
    
    Args:
        file_path: Path to the YAML file
        
    Returns:
        Tuple of (is_valid, error_message)
        where error_message is None if valid
    """
    try:
        load_yaml_robust(file_path, normalize_chars=False)
        return True, None
    except FileEncodingError as e:
        return False, f"Encoding error: {str(e)}"
    except yaml.YAMLError as e:
        return False, f"YAML parsing error: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def get_file_encoding_info(file_path: str) -> Dict[str, Any]:
    """
    Get detailed encoding information about a file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Dictionary with encoding details
    """
    if not os.path.exists(file_path):
        return {
            'exists': False,
            'error': 'File not found'
        }
    
    try:
        # Detect encoding
        detected_encoding, confidence = detect_encoding(file_path)
        
        # Check for BOM
        with open(file_path, 'rb') as f:
            start_bytes = f.read(4)
        
        has_utf8_bom = start_bytes.startswith(b'\xef\xbb\xbf')
        has_utf16_bom = start_bytes.startswith(b'\xff\xfe') or start_bytes.startswith(b'\xfe\xff')
        
        # Try to load with different encodings
        load_results = {}
        for encoding in ['utf-8', 'utf-8-sig', 'cp1252', 'latin-1']:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    f.read()
                load_results[encoding] = 'success'
            except Exception as e:
                load_results[encoding] = str(e)
        
        return {
            'exists': True,
            'detected_encoding': detected_encoding,
            'confidence': confidence,
            'has_utf8_bom': has_utf8_bom,
            'has_utf16_bom': has_utf16_bom,
            'load_results': load_results,
            'size_bytes': os.path.getsize(file_path)
        }
        
    except Exception as e:
        return {
            'exists': True,
            'error': str(e)
        }
