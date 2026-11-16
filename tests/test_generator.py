"""Unit tests for DiaType diagram generator."""

import json
from unittest.mock import patch, MagicMock

import pytest
from pydantic import ValidationError

from diatype.config import Settings
from diatype.generator import DiagramEngine
from diatype.models import Diagram
from diatype.validator import validate_mermaid, sanitize, detect_diagram_type


def test_settings_load():
    """Test loading settings matches current defaults (updated from phi3)."""
    settings = Settings.load()
    assert settings.ollama_model == "llama3.2"
    assert settings.temperature == 0.2
    assert settings.default_diagram_type == "flowchart"
    assert settings.max_tokens == 2500

    settings2 = Settings.load("config.example.toml")
    assert settings2.ollama_model == "llama3.2"


@patch("ollama.chat")
def test_refine_preserves_structure(mock_chat):
    """Test that refinement preserves original diagram structure."""
    mock_response = MagicMock()
    mock_response.__getitem__.return_value = {
        "message": {
            "content": json.dumps({
                "mermaid": "flowchart TD\n    A[Start] --> B[Process] --> C[End]",
                "explanation": "Refined diagram that keeps the core structure while applying the requested changes."
            })
        }
    }
    mock_chat.return_value = mock_response

    engine = DiagramEngine()
    original = Diagram(
        mermaid="flowchart TD\n    A[Start] --> B[Process] --> C[End]",
        explanation="Original linear process flow from start through processing to completion.",
        diagram_type="flowchart",
    )

    refined = engine.refine(original, "add detailed labels")
    assert "Start" in refined.mermaid
    assert "Process" in refined.mermaid
    assert len(refined.explanation) >= 15


@patch("ollama.chat")
def test_explain_fallback_on_error(mock_chat):
    """Test explanation falls back on LLM error."""
    mock_chat.side_effect = Exception("Simulated LLM failure")

    engine = DiagramEngine()
    diagram = Diagram(
        mermaid="flowchart TD\n    A --> B --> C",
        explanation="This is a basic flowchart used to test the fallback explanation mechanism when the LLM is unavailable.",
        diagram_type="flowchart",
    )

    explanation = engine.explain(diagram)
    assert "could not generate an explanation at this time" in explanation
    assert "basic flowchart" in explanation.lower()


def test_parse_llm_response_json_and_fallback():
    """Test parsing of LLM responses in both JSON and text fallback modes."""
    engine = DiagramEngine(Settings(ollama_model="llama3.2"))

    # JSON case
    json_content = json.dumps({
        "mermaid": "flowchart TD\n    Start --> End",
        "explanation": "This test case checks that JSON responses from the LLM are correctly parsed into Diagram objects."
    })
    d1 = engine._parse_llm_response(json_content, "flowchart")
    assert d1.mermaid.startswith("flowchart")
    assert "JSON responses" in d1.explanation
    assert len(d1.explanation) >= 15

    # Fallback non-JSON case
    fallback_content = 'Here is a diagram:\nflowchart TD\n    P --> Q\nExplanation: fallback parsing test.'
    with patch("diatype.generator.sanitize", return_value="flowchart TD\n    P --> Q"), \
         patch("diatype.generator.validate_mermaid", return_value=True), \
         patch("diatype.generator.detect_diagram_type", return_value="flowchart"):
        d2 = engine._parse_llm_response(fallback_content, "flowchart")
        assert d2.mermaid.startswith("flowchart")


def test_error_cases():
    """Test error handling for invalid inputs (updated for pydantic validation)."""
    engine = DiagramEngine()

    # Short prompt for generate()
    with pytest.raises(ValueError, match="at least 8 characters"):
        engine.generate("hi")

    # Short instruction for refine()
    diagram = Diagram(
        mermaid="flowchart TD\nA-->B",
        explanation="This explanation meets the minimum length requirement of fifteen characters.",
        diagram_type="flowchart"
    )
    with pytest.raises(ValueError, match="at least 3 characters"):
        engine.refine(diagram, "no")

    # Model validation for short explanation (now uses pydantic)
    with pytest.raises(ValidationError, match="at least 15 characters"):
        Diagram(
            mermaid="flowchart TD\nA-->B",
            explanation="ok",
        )


def test_validator_functions():
    """Test the validator utilities."""
    assert validate_mermaid("flowchart TD\n    A --> B")
    assert not validate_mermaid("invalid code")
    assert not validate_mermaid("")
    assert sanitize("```mermaid\nflowchart TD\nA-->B\n```") == "flowchart TD\nA-->B"
    assert detect_diagram_type("sequenceDiagram\nA->>B: msg") == "sequenceDiagram"


@patch("ollama.chat")
def test_generate_with_mock(mock_chat):
    """Basic generation test with mocked response."""
    mock_response = {
        "message": {"content": json.dumps({
            "mermaid": "flowchart TD\n    P --> Q",
            "explanation": "A simple test diagram for the generator."
        })}
    }
    mock_chat.return_value = mock_response
    engine = DiagramEngine()
    diagram = engine.generate("simple process")
    assert diagram.diagram_type == "flowchart"
    assert len(diagram.mermaid) > 10
    assert len(diagram.explanation) >= 15


def test_diagram_to_excalidraw():
    """Test Excalidraw export produces valid scene."""
    diagram = Diagram(
        mermaid="flowchart TD\n    A[Start] --> B[End]",
        explanation="Test diagram for Excalidraw export with hand-drawn styling.",
        diagram_type="flowchart"
    )
    ex = diagram.to_excalidraw()
    assert ex["type"] == "excalidraw"
    assert len(ex["elements"]) > 0
    assert any(e.get("type") == "rectangle" for e in ex["elements"])
