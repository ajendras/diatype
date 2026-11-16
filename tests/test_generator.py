"""Tests for the DiagramEngine.

Covers generation, refinement, explanation (including fallback), error handling,
parsing strategies, validator integration, and Excalidraw export. Ollama calls
are fully mocked so tests run without a live model.
"""

from __future__ import annotations

import json

import pytest
from unittest.mock import patch

from diatype.config import Settings
from diatype.generator import DiagramEngine
from diatype.models import Diagram
from diatype.validator import validate_mermaid, sanitize, detect_diagram_type


@pytest.fixture
def settings() -> Settings:
    """Test settings with deterministic values."""
    return Settings(
        ollama_model="llama3.2",
        temperature=0.0,
        max_tokens=500,
        default_diagram_type="flowchart",
    )


@pytest.fixture
def engine(settings: Settings) -> DiagramEngine:
    """Engine fixture using test settings."""
    return DiagramEngine(settings)


def test_generate_basic_flowchart(engine: DiagramEngine) -> None:
    """Basic generation produces a validated Diagram."""
    with patch("ollama.chat") as mock_chat:
        mock_chat.return_value = {
            "message": {
                "content": json.dumps({
                    "mermaid": "flowchart TD\n    A[User] --> B[Login]",
                    "explanation": "Simple user login flow."
                })
            }
        }
        diagram = engine.generate("user logs in")
        assert diagram.diagram_type == "flowchart"
        assert "A[User]" in diagram.mermaid
        assert "login" in diagram.explanation.lower()
        assert validate_mermaid(diagram.mermaid)


def test_refine_preserves_structure(engine: DiagramEngine) -> None:
    """Refinement keeps diagram_type and SVG while updating content."""
    with patch("ollama.chat") as mock_chat:
        mock_chat.return_value = {
            "message": {
                "content": json.dumps({
                    "mermaid": "flowchart TD\n    A[Start] --> B[Process with label]",
                    "explanation": "Refined with clearer labels."
                })
            }
        }
        original = Diagram(
            mermaid="flowchart TD\n    A --> B --> C",
            explanation="Original simple flow.",
            diagram_type="flowchart",
            svg="<svg>original-render</svg>",
        )
        refined = engine.refine(original, "add detailed labels")
        assert refined.diagram_type == original.diagram_type
        assert refined.svg == original.svg
        assert "label" in refined.mermaid.lower()
        assert "Refined with clearer" in refined.explanation


def test_explain_fallback_on_error(engine: DiagramEngine) -> None:
    """On LLM error we return a safe fallback that still contains useful info."""
    with patch("ollama.chat", side_effect=RuntimeError("Ollama unavailable")):
        diagram = Diagram(
            mermaid="flowchart TD\n    A --> B --> C",
            explanation="This is a basic flowchart.",
            diagram_type="flowchart",
        )
        explanation = engine.explain(diagram)
        assert "could not generate an explanation at this time" in explanation.lower()
        assert "basic flowchart" in explanation.lower()
        assert "flowchart td" in explanation.lower()


def test_error_cases(engine: DiagramEngine) -> None:
    """Validate error messages and early validation."""
    diagram = Diagram(
        mermaid="flowchart TD\n    A --> B",
        explanation="Simple flow.",
        diagram_type="flowchart",
    )

    with pytest.raises(ValueError, match="at least 3 characters"):
        engine.refine(diagram, "xy")

    with pytest.raises(ValueError, match="at least 8 characters long"):
        engine.generate("short")


def test_explain_success_path(engine: DiagramEngine) -> None:
    """Successful explanation call returns model text."""
    with patch("ollama.chat") as mock_chat:
        mock_chat.return_value = {
            "message": {"content": "This diagram illustrates a basic three-step process."}
        }
        diagram = Diagram(
            mermaid="flowchart TD\n    A --> B --> C",
            explanation="orig",
            diagram_type="flowchart",
        )
        explanation = engine.explain(diagram)
        assert "three-step process" in explanation.lower()


def test_parse_json_and_regex_fallback(engine: DiagramEngine) -> None:
    """_parse_llm_response handles both clean JSON and markdown-wrapped output."""
    with patch("ollama.chat") as mock_chat:
        # JSON response
        mock_chat.return_value = {
            "message": {
                "content": '{"mermaid": "flowchart TD\\n    X --> Y", "explanation": "JSON path"}'
            }
        }
        d1 = engine.generate("json test")
        assert "X --> Y" in d1.mermaid
        assert "JSON path" in d1.explanation

    with patch("ollama.chat") as mock_chat:
        # Regex fallback (non-JSON text)
        mock_chat.return_value = {
            "message": {
                "content": 'Here is the diagram:\n```mermaid\nflowchart TD\n    P --> Q\n```'
            }
        }
        d2 = engine.generate("regex test")
        assert "P --> Q" in d2.mermaid


def test_validator_and_sanitize_integration(engine: DiagramEngine) -> None:
    """Generated diagrams always pass validation and sanitization."""
    with patch("ollama.chat") as mock_chat:
        mock_chat.return_value = {
            "message": {
                "content": json.dumps({
                    "mermaid": "```mermaid\nflowchart TD\n    A --> B\n```",
                    "explanation": "Sanitized diagram."
                })
            }
        }
        diagram = engine.generate("clean me")
        assert validate_mermaid(diagram.mermaid)
        assert not diagram.mermaid.startswith("```")
        assert "flowchart" in diagram.mermaid


def test_to_excalidraw_conversion(engine: DiagramEngine) -> None:
    """Diagram can be exported to Excalidraw JSON with hand-drawn style."""
    diagram = Diagram(
        mermaid="flowchart TD\n    A[Hello] --> B[World]",
        explanation="Test diagram",
        diagram_type="flowchart",
    )
    ex = diagram.to_excalidraw()
    assert ex["type"] == "excalidraw"
    assert ex["version"] == 2
    assert len(ex["elements"]) >= 3
    element_types = {el["type"] for el in ex["elements"]}
    assert "rectangle" in element_types
    assert "text" in element_types
    assert "arrow" in element_types or any("arrow" in str(el) for el in ex["elements"])
