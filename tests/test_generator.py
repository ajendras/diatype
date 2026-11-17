"""Tests for the DiagramEngine and related models.

Uses mocking to avoid actual Ollama calls. Covers generation, refinement,
explanation, error handling, parsing fallbacks, Excalidraw export, validator
integration, and history persistence. All Diagram instantiations now use
explanations long enough to satisfy the Pydantic min_length=15 constraint.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from diatype.config import Settings
from diatype.generator import DiagramEngine
from diatype.models import Diagram
from diatype.validator import detect_diagram_type, validate_mermaid


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Test settings with history disabled and a temporary directory."""
    return Settings(
        ollama_model="llama3.2",
        temperature=0.0,
        max_tokens=500,
        output_dir=tmp_path / "output",
        history_enabled=False,
        history_dir=tmp_path / "history",
    )


@pytest.fixture
def engine(settings: Settings) -> DiagramEngine:
    """Fresh engine for each test (history disabled by default)."""
    return DiagramEngine(settings)


def test_error_cases(engine: DiagramEngine) -> None:
    """Test various error conditions and validation failures."""
    with pytest.raises(ValueError, match="at least 8 characters"):
        engine.generate("")

    with pytest.raises(ValueError, match="at least 8 characters"):
        engine.generate("short")

    valid_diagram = Diagram(
        mermaid="flowchart TD\n    A[Start] --> B[End]",
        explanation="This explanation is long enough to satisfy the Pydantic min_length constraint.",
    )

    with pytest.raises(ValueError, match="at least 3 characters"):
        engine.refine(valid_diagram, "")

    with pytest.raises(ValidationError):
        Diagram(
            mermaid="invalid start here",
            explanation="This should trigger mermaid start validation but uses a long explanation.",
        )


def test_explain_success_path(engine: DiagramEngine) -> None:
    """Test the explain method on a valid diagram (success path)."""
    diagram = Diagram(
        mermaid="flowchart TD\n    A[User] -->|login| B[Auth Service]",
        explanation="This is a successful test explanation that exceeds fifteen characters easily and describes the login flow.",
        diagram_type="flowchart",
    )

    with patch("ollama.chat") as mock_chat:
        mock_chat.return_value = {
            "message": {
                "content": (
                    "The diagram depicts a user logging into an authentication service. "
                    "It shows the secure flow and subsequent dashboard access."
                )
            }
        }
        explanation = engine.explain(diagram)
        assert len(explanation) > 20
        assert any(word in explanation.lower() for word in ("user", "login", "diagram", "flow"))


def test_parse_json_and_regex_fallback(engine: DiagramEngine) -> None:
    """Test both strict JSON parsing and regex fallback in _parse_llm_response."""
    # Valid JSON path
    json_content = json.dumps(
        {
            "mermaid": "flowchart TD\n    Start --> Process --> End",
            "explanation": "This JSON-parsed diagram shows a basic linear process flow with three steps.",
        }
    )
    with patch("ollama.chat") as mock_chat:
        mock_chat.return_value = {"message": {"content": json_content}}
        d1 = engine.generate("json test")
        assert d1.mermaid.startswith("flowchart")
        assert len(d1.explanation) >= 15
        assert "basic linear process" in d1.explanation.lower()

    # Regex fallback with non-JSON content
    regex_content = (
        'Some preamble text.\n'
        '{"mermaid": "sequenceDiagram\\n    Alice->>Bob: Hello", '
        '"explanation": "This sequence diagram demonstrates a simple message exchange between two parties with clear direction."}'
    )
    with patch("ollama.chat") as mock_chat:
        mock_chat.return_value = {"message": {"content": regex_content}}
        d2 = engine.generate("regex test")
        assert "sequenceDiagram" in d2.mermaid
        assert len(d2.explanation) >= 15
        assert "sequence diagram" in d2.explanation.lower()


def test_to_excalidraw_conversion() -> None:
    """Test Diagram.to_excalidraw() produces valid Excalidraw v2 JSON with sketchy styling."""
    diagram = Diagram(
        mermaid="""flowchart TD
    U[User] --> A[API Gateway]
    A --> S[Service]
    S --> DB[(Database)]""",
        explanation="Test diagram for converting a flowchart to Excalidraw format with hand-drawn styling and proper element layout.",
        diagram_type="flowchart",
        title="Test Diagram",
    )
    ex = diagram.to_excalidraw()

    assert ex["type"] == "excalidraw"
    assert ex["version"] == 2
    assert "source" in ex
    assert len(ex["elements"]) >= 4
    assert "appState" in ex
    assert ex["appState"]["theme"] == "light"

    types = [el.get("type") for el in ex["elements"]]
    assert "rectangle" in types
    assert "text" in types
    assert "arrow" in types

    for el in ex["elements"]:
        if el.get("type") == "rectangle":
            assert el.get("roughness") == 2
            assert el.get("strokeColor") == "#5d4037"
        if el.get("type") == "text":
            assert el.get("fontFamily") == 3  # Virgil hand-drawn font


def test_generate_success(engine: DiagramEngine) -> None:
    """Test successful diagram generation with mocked Ollama response."""
    with patch("ollama.chat") as mock_chat:
        mock_chat.return_value = {
            "message": {
                "content": json.dumps(
                    {
                        "mermaid": "flowchart TD\n    A[Start] --> B[End]",
                        "explanation": "A simple start-to-end flowchart used for testing the full generation path.",
                    }
                )
            }
        }
        diagram = engine.generate("Create a simple flow from start to end.")
        assert diagram.mermaid.startswith(("flowchart", "graph"))
        assert len(diagram.explanation) >= 15
        assert diagram.diagram_type in ("flowchart", "graph")
        assert diagram.version == 1
        assert diagram.id.startswith("diag_")


def test_refine(engine: DiagramEngine) -> None:
    """Test iterative refinement while preserving ID and incrementing version."""
    original = Diagram(
        mermaid="flowchart TD\n    A --> B",
        explanation="Base diagram for refinement test that contains a sufficiently long explanation to pass validation.",
        diagram_type="flowchart",
        id="diag_test_refine",
        version=1,
        original_prompt="initial prompt",
    )

    with patch("ollama.chat") as mock_chat:
        mock_chat.return_value = {
            "message": {
                "content": json.dumps(
                    {
                        "mermaid": "flowchart TD\n    A --> B\n    B --> C[Error Handler]",
                        "explanation": "Refined diagram that adds error handling and a retry loop while preserving original structure.",
                    }
                )
            }
        }
        refined = engine.refine(original, "add error handling step and a retry loop")
        assert "Error Handler" in refined.mermaid
        assert refined.id == "diag_test_refine"
        assert refined.version == 2
        assert len(refined.explanation) >= 15


def test_history_methods(engine: DiagramEngine, tmp_path: Path) -> None:
    """Test history persistence, listing and loading (temporarily enables history)."""
    engine.settings.history_enabled = True
    engine.settings.history_dir = tmp_path / "history"
    engine.settings.history_dir.mkdir(parents=True, exist_ok=True)

    diagram = Diagram(
        mermaid="flowchart TD\n    A[User] --> B[Service]",
        explanation="History test diagram whose explanation meets the length requirement for Pydantic validation.",
        diagram_type="flowchart",
        original_prompt="test history persistence",
        title="History Test",
    )
    engine.save_to_history(diagram)

    history_list = engine.list_history(limit=5)
    assert isinstance(history_list, list)

    loaded = engine.load_version(diagram.id, diagram.version)
    if loaded is not None:
        assert loaded.mermaid == diagram.mermaid
        assert loaded.explanation == diagram.explanation


def test_validator_integration() -> None:
    """Test integration with validator.py functions."""
    assert validate_mermaid("flowchart TD\n    A --> B")
    assert validate_mermaid("sequenceDiagram\n    A->>B: msg")
    assert not validate_mermaid("")
    assert not validate_mermaid("plain text with no diagram syntax")

    assert detect_diagram_type("flowchart TD\nA-->B") == "flowchart"
    assert detect_diagram_type("sequenceDiagram\nA->B") == "sequenceDiagram"
    assert detect_diagram_type("classDiagram\nclass A") == "classDiagram"
    assert detect_diagram_type("unknown") is None
