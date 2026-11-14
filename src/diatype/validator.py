"""Mermaid code validation, sanitization and type detection.

Provides defensive, production-grade checks around LLM-generated diagram
syntax. Full validation is impossible without a complete parser; these
functions use heuristics that catch the vast majority of errors while
remaining fast and dependency-free.
"""

import re
from typing import Final

# Recognized Mermaid diagram starters (case-insensitive)
_VALID_DIAGRAM_STARTS: Final[frozenset[str]] = frozenset({
    "flowchart", "graph", "sequencediagram", "classdiagram", "statediagram",
    "erdiagram", "journey", "gantt", "pie", "quadrantchart",
    "requirementdiagram", "mindmap", "timeline", "gitgraph", "c4diagram",
})

# Patterns that indicate meaningful diagram content
_CONTENT_INDICATORS: Final[tuple[str, ...]] = (
    "-->", "->", "==>", ":::",
    "[", "]", "{", "}", "(", ")", "|",
)


def validate_mermaid(code: str) -> bool:
    """Validate that a string appears to be usable Mermaid diagram syntax.

    Performs several fast checks:
      * Non-empty after stripping
      * Begins with a known Mermaid diagram keyword
      * Contains at least one structural element (lenient for some chart types)
      * Contains no obvious dangerous content (XSS vectors)

    Raises:
        TypeError: if code is not a string.
    """
    if not isinstance(code, str):
        raise TypeError("validate_mermaid() expects a str, got " f"{type(code).__name__}")

    stripped = code.strip()
    if not stripped:
        return False

    if len(stripped) < 12:
        return False

    first_token = stripped.split(maxsplit=1)[0].lower()
    if not any(start in first_token for start in _VALID_DIAGRAM_STARTS):
        return False

    # Most diagrams need at least one relationship or container.
    # We are deliberately lenient for pie charts, gantt, etc.
    has_structure = any(ind in stripped for ind in _CONTENT_INDICATORS)
    if not has_structure and not any(t in first_token for t in ("pie", "gantt", "mindmap")):
        return False

    # Security sanity check - never allow script injection that could
    # become dangerous when the SVG is later rendered.
    dangerous = {"<script", "javascript:", "onerror=", "onload=", "eval("}
    lowered = stripped.lower()
    if any(d in lowered for d in dangerous):
        return False

    return True


def sanitize(code: str) -> str:
    """Extract and clean pure Mermaid source from LLM output.

    Removes:
      * Markdown code fences (```mermaid ... ```)
      * Common explanatory prefixes ("Here is the diagram:", etc.)
      * Excessive whitespace

    Returns a clean, ready-to-render Mermaid string.

    Raises:
        TypeError: if code is not a string.
    """
    if not isinstance(code, str):
        raise TypeError("sanitize() expects a str, got " f"{type(code).__name__}")

    if not code.strip():
        return ""

    # Strip markdown code blocks (with or without "mermaid" label)
    code = re.sub(r"```(?:mermaid)?\s*", "", code, flags=re.IGNORECASE)
    code = re.sub(r"\s*```$", "", code, flags=re.IGNORECASE)

    # Remove common LLM framing text
    code = re.sub(
        r"^(?:here|this|below|the|output).*?(?:diagram|code|syntax|is|:)\s*",
        "",
        code,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    # Normalize whitespace: keep intentional indentation but remove empty lines
    lines: list[str] = []
    for line in code.splitlines():
        stripped_line = line.rstrip()
        if stripped_line:
            lines.append(stripped_line)

    cleaned = "\n".join(lines).strip()

    # Final safety: if the result still contains a full JSON object (rare),
    # attempt to pull the mermaid field out.
    if cleaned.startswith("{") and '"mermaid"' in cleaned:
        import json

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and "mermaid" in parsed:
                cleaned = str(parsed["mermaid"])
        except (json.JSONDecodeError, TypeError):
            pass

    return cleaned


def detect_diagram_type(code: str) -> str:
    """Return the standardized Mermaid diagram type from source text.

    Inspects the first line only. Falls back to 'flowchart' for any
    unrecognized or ambiguous diagram.

    Raises:
        TypeError: if code is not a string.
    """
    if not isinstance(code, str):
        raise TypeError("detect_diagram_type() expects a str, got " f"{type(code).__name__}")

    stripped = code.strip()
    if not stripped:
        return "flowchart"

    first_line = stripped.split("\n", 1)[0].lower()

    mapping = {
        "flowchart": "flowchart",
        "graph": "flowchart",
        "sequencediagram": "sequenceDiagram",
        "sequence diagram": "sequenceDiagram",
        "classdiagram": "classDiagram",
        "class diagram": "classDiagram",
        "statediagram": "stateDiagram",
        "state diagram": "stateDiagram",
        "erdiagram": "erDiagram",
        "er diagram": "erDiagram",
        "journey": "journey",
        "gantt": "gantt",
        "pie": "pie",
        "quadrantchart": "quadrantChart",
        "quadrant chart": "quadrantChart",
        "requirementdiagram": "requirementDiagram",
        "mindmap": "mindmap",
        "timeline": "timeline",
        "gitgraph": "gitGraph",
        "git graph": "gitGraph",
        "c4diagram": "c4Diagram",
        "c4 diagram": "c4Diagram",
    }

    for keyword, diagram_type in mapping.items():
        if keyword in first_line:
            return diagram_type

    return "flowchart"
