"""Standard Library: Export session state.

Provides utilities for dumping the `.jsonl` audit trail into a human-readable markdown file.
"""

import json
from pathlib import Path

def export_session(events_path: Path, output_path: Path) -> bool:
    """Exports the events.jsonl into a readable Markdown file."""
    if not events_path.exists():
        return False
        
    try:
        lines = []
        lines.append("# Kinox Session Export\n")
        
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    kind = event.get("kind", "unknown")
                    task_id = event.get("task_id", "unknown")
                    tier = event.get("tier", "unknown")
                    tokens = event.get("tokens_used", "unknown")
                    latency = event.get("latency_ms", "unknown")
                    
                    lines.append(f"## Event: {kind} ({task_id})")
                    lines.append(f"- **Tier**: {tier}")
                    lines.append(f"- **Tokens**: {tokens}")
                    lines.append(f"- **Latency**: {latency}ms")
                    lines.append("")
                    
                    # If there are context lines or messages, we can dump them here
                    if "lines" in event and event["lines"]:
                        lines.append("```text")
                        lines.append("\n".join(event["lines"]))
                        lines.append("```\n")
                        
                except json.JSONDecodeError:
                    lines.append("*(Failed to parse event line)*\n")
                    
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return True
    except Exception:
        return False
