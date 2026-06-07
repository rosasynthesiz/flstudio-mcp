from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP

KB_ROOT = Path("knowledgebase")


def _resolve_path(sub_path: str) -> Path:
    p = KB_ROOT / sub_path
    return p.resolve()


def _read_file_safe(path: Path) -> str:
    if not path.exists():
        return f"File {path.name} not found in knowledgebase."
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading {path.name}: {e}"


def kb_search(query: str) -> str:
    """Search the Knowledgebase markdown and JSON files for a query."""
    if not KB_ROOT.exists():
        return "Knowledgebase directory not found."

    results = []
    for root_dir, _, files in os.walk(KB_ROOT):
        for file in files:
            if file.endswith((".md", ".json")):
                p = Path(root_dir) / file
                try:
                    content = p.read_text(encoding="utf-8")
                    if query.lower() in content.lower():
                        rel_path = p.relative_to(KB_ROOT)
                        results.append(f"Found in: {rel_path}")
                except Exception:
                    pass
    if not results:
        return f"No results found for '{query}'."
    return "\\n".join(results)


def kb_get(topic_path: str) -> str:
    """Get the content of a specific Knowledgebase file (e.g. 'fl_api/mixer_eq.md')."""
    return _read_file_safe(KB_ROOT / topic_path)


def kb_get_parameter_spec(api_function: str) -> str:
    """Check knowledgebase for parameter specs of an API function."""
    # Specifically check mixer_eq_calibration.json or search globally
    calib = KB_ROOT / "fl_api" / "mixer_eq_calibration.json"
    if calib.exists():
        try:
            data = json.loads(calib.read_text())
            for entry in data:
                if (
                    entry.get("api_setter") == api_function
                    or entry.get("api_getter") == api_function
                ):
                    return json.dumps(entry, indent=2)
        except Exception:
            pass
    return f"No parameter spec found for {api_function} in known calibration files."


def kb_get_conversion(domain: str, parameter: str) -> str:
    """Get conversion mappings for a domain (e.g. 'eq_gain')."""
    calib = KB_ROOT / "fl_api" / "mixer_eq_calibration.json"
    if calib.exists():
        try:
            data = json.loads(calib.read_text())
            for entry in data:
                if entry.get("domain") == domain and entry.get("parameter") == parameter:
                    return json.dumps(entry.get("mapping", []), indent=2)
        except Exception:
            pass
    return f"No conversion found for domain '{domain}' and parameter '{parameter}'."


def kb_record_finding(
    topic: str,
    context: str,
    observation: str,
    tested_values: str,
    result: str,
    confidence: str,
    source_method: str,
    affected_files_tools: str = "N/A",
    open_questions: str = "None",
    next_action: str = "None",
) -> str:
    """Record a finding directly to the learning_log.md (append-only)."""
    log_file = KB_ROOT / "agent_notes" / "learning_log.md"
    if not log_file.exists():
        return "learning_log.md not found."

    date_str = datetime.now().strftime("%Y-%m-%d")
    entry = f"\\n## {date_str} — {topic}\\n\\n"
    entry += "Agent/Source: FL Studio MCP Agent\\n"
    entry += f"Context: {context}\\n"
    entry += f"Observation: {observation}\\n"
    entry += f"Tested values: {tested_values}\\n"
    entry += f"Result: {result}\\n"
    entry += f"Confidence: {confidence}\\n"
    entry += f"Affected files/tools: {affected_files_tools}\\n"
    entry += "Should update machine-readable data: Yes if confidence is high\\n"
    entry += f"Open questions: {open_questions}\\n"
    entry += f"Next action: {next_action}\\n"

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry)
        return "Successfully appended finding to learning_log.md."
    except Exception as e:
        return f"Failed to write to learning_log.md: {e}"


def kb_record_verified_finding(json_path: str, new_mapping_entry: str, confidence: str) -> str:
    """Safely update a structured JSON file (e.g., fl_api/mixer_eq_calibration.json) with a new mapping."""
    if confidence not in [
        "implementation_verified",
        "cross_platform_verified",
        "measured_repeated",
        "measured_once",
    ]:
        return f"Error: Confidence '{confidence}' is too low to update structured machine data directly."

    p = KB_ROOT / json_path
    if not p.exists():
        return f"File {json_path} does not exist."

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        try:
            new_entry = json.loads(new_mapping_entry)
        except json.JSONDecodeError:
            return "Error: new_mapping_entry must be a valid JSON string."

        new_entry["confidence"] = confidence

        # Assumption: We are updating mixer_eq_calibration.json structure
        if isinstance(data, list) and len(data) > 0 and "mapping" in data[0]:
            # Simple check to avoid silent overwrite of existing normalized values
            existing = [m.get("normalized") for m in data[0]["mapping"]]
            if new_entry.get("normalized") in existing:
                return f"Error: Mapping for normalized value {new_entry.get('normalized')} already exists. Manual review required."

            data[0]["mapping"].append(new_entry)
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return f"Successfully added new verified mapping to {json_path}."
        else:
            return "Error: JSON structure not recognized for automatic update."
    except Exception as e:
        return f"Error updating JSON: {e}"


def kb_list_open_questions() -> str:
    """Return the contents of open_questions.md."""
    return _read_file_safe(KB_ROOT / "agent_notes" / "open_questions.md")


def register(mcp: FastMCP) -> None:
    mcp.tool()(kb_search)
    mcp.tool()(kb_get)
    mcp.tool()(kb_get_parameter_spec)
    mcp.tool()(kb_get_conversion)
    mcp.tool()(kb_record_finding)
    mcp.tool()(kb_record_verified_finding)
    mcp.tool()(kb_list_open_questions)
