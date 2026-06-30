"""Standard Library: Compact text and context.

Provides utilities for compressing strings, code, and JSON to reduce token bloat.
"""

import re

def compact_text(text: str) -> str:
    """Removes empty lines and reduces whitespace to save context window tokens."""
    # Remove multiple blank lines
    text = re.sub(r'\n\s*\n', '\n', text)
    # Remove leading/trailing whitespace
    text = text.strip()
    return text

def compact_json(text: str) -> str:
    """Minifies JSON strings."""
    import json
    try:
        data = json.loads(text)
        return json.dumps(data, separators=(',', ':'))
    except json.JSONDecodeError:
        return text
