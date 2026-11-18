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
        raise TypeError(f"validate_mermaid() expects a str, got {type(code).__name__}")

    code = code.strip()
    if len(code) < 5:  # too short for a diagram
        return False

    lowered = code.lower()

    # Must start with a valid diagram type (graph is alias for flowchart)
    if not any(lowered.startswith(start) for start in _VALID_DIAGRAM_STARTS):
        if not lowered.startswith("graph"):
            return False

    # Should contain some content indicators unless it's a very simple chart
    has_content = any(ind in lowered for ind in _CONTENT_INDICATORS)
    if not has_content and not any(
        t in lowered for t in ("pie", "gantt", "mindmap", "timeline")
    ):
        return False

    # Security: block potential XSS or dangerous constructs
    dangerous = re.compile(
        r"(?i)(<script|javascript:|on(load|error|click|mouseover)|"
        r"eval\(|alert\(|document\.|window\.)"
    )
    if dangerous.search(code):
        return False

    return True


def sanitize(code: str) -> str:
    """Remove common artifacts from LLM responses such as markdown code fences,
    JSON wrappers, and excessive whitespace.
    """
    if not isinstance(code, str):
        return ""

    # Remove markdown code blocks
    code = re.sub(r"^```(?:mermaid)?\s*\n?", "", code, flags=re.MULTILINE)
    code = re.sub(r"\n?```\s*$", "", code, flags=re.MULTILINE)

    # Remove any json-like wrappers that sometimes leak from the model
    code = re.sub(r'^\s*\{\s*"mermaid"\s*:\s*["\']', "", code)
    code = re.sub(r'["\']?\s*,\s*"explanation".*$', "", code, flags=re.DOTALL)

    # General cleanup
    code = code.strip().strip('"').strip("'").strip("`")

    # Normalize line endings and trailing spaces
    code = "\n".join(line.rstrip() for line in code.splitlines() if line.strip())

    return code


def detect_diagram_type(code: str) -> str | None:
    """Detect the diagram type from the Mermaid source.

    Returns the canonical name (as used by Mermaid and the rest of the
    codebase) or None if it cannot be determined. This allows callers
    to fall back to a requested_type.
    """
    if not isinstance(code, str) or not code or not code.strip():
        return None

    first_line = code.strip().split("\n")[0].strip().lower()

    if "flowchart" in first_line or first_line.startswith("graph"):
        return "flowchart"

    type_map: dict[str, str] = {
        "sequencediagram": "sequenceDiagram",
        "classdiagram": "classDiagram",
        "statediagram": "stateDiagram",
        "erdiagram": "erDiagram",
        "journey": "journey",
        "gantt": "gantt",
        "pie": "pie",
        "quadrantchart": "quadrantChart",
        "requirementdiagram": "requirementDiagram",
        "mindmap": "mindmap",
        "timeline": "timeline",
        "gitgraph": "gitGraph",
        "c4diagram": "c4Diagram",
    }

    for key, canonical in type_map.items():
        if key in first_line or canonical.lower() in first_line:
            return canonical

    return None
