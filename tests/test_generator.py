"""Tests for DiagramEngine, models, config and validator.

Covers generation, refinement, explanation, parsing fallbacks,
validation, error handling and snapshot-style checks.
Ollama calls are fully mocked so tests run without a live model.
"""

from unittest.mock import patch, MagicMock

import pytest

from diatype.config import Settings
from diatype.generator import DiagramEngine
from diatype.models import Diagram, DiagramRequest
from diatype.validator import validate_mermaid, sanitize, detect_diagram_type


def test_settings_defaults() -> None:
    """Default values match the documented diagram-friendly choices."""
    settings = Settings()
    assert settings.ollama_model == "llama3.2"
    assert settings.temperature == 0.2
    assert settings.default_diagram_type == "flowchart"
    assert settings.max_tokens == 2500
    assert str(settings.output_dir) == "diagrams"


def test_settings_load(tmp_path) -> None:
    """TOML loading merges values and falls back gracefully."""
    config = tmp_path / "config.toml"
    config.write_text(
        'ollama_model = "phi3"\n'
        "temperature = 0.1\n"
        'default_diagram_type = "sequenceDiagram"\n'
    )
    settings = Settings.load(str(config))
    assert settings.ollama_model == "phi3"
    assert settings.temperature == 0.1
    assert settings.default_diagram_type == "sequenceDiagram"


def test_settings_ollama_options() -> None:
    """Options dict is correctly built for ollama.chat."""
    settings = Settings(temperature=0.4, max_tokens=1200)
    opts = settings.get_ollama_options()
    assert opts["temperature"] == 0.4
    assert opts["num_predict"] == 1200
    assert opts["top_p"] == 0.9


def test_diagram_request_validation() -> None:
    """Pydantic validators enforce prompt length and clean whitespace."""
    req = DiagramRequest(
        prompt="   User logs in via OAuth   ",
        diagram_type="flowchart",
    )
    assert req.prompt == "User logs in via OAuth"

    with pytest.raises(ValueError):
        DiagramRequest(prompt="short", diagram_type="flowchart")


def test_diagram_model() -> None:
    """Diagram validates mermaid start, provides markdown and render check."""
    d = Diagram(
        mermaid="flowchart TD\n    A[Start] --> B[End]",
        explanation="A minimal login flow.",
        diagram_type="flowchart",
    )
    assert d.is_renderable()
    assert "```mermaid" in d.to_markdown()
    assert d.diagram_type == "flowchart"

    # Invalid start should raise
    with pytest.raises(ValueError, match="Mermaid code must start with a valid diagram type"):
        Diagram(mermaid="invalid syntax", explanation="bad")


def test_validator_functions() -> None:
    """Sanitize, validate and detect work on typical LLM output."""
    assert validate_mermaid("flowchart TD\n    A --> B")
    assert not validate_mermaid("")
    assert not validate_mermaid("just text with no structure")

    dirty = """```mermaid
flowchart TD
    A --> B
```
Here is the diagram I made.
"""
    clean = sanitize(dirty)
    assert clean.startswith("flowchart")
    assert "A --> B" in clean
    assert "Here is the diagram" not in clean

    assert detect_diagram_type("sequenceDiagram\n    A->>B: hello") == "sequenceDiagram"
    assert detect_diagram_type("graph LR\n    X-->Y") == "flowchart"
    assert detect_diagram_type("unknown") == "flowchart"


@patch("diatype.generator.ollama.chat")
def test_generate_happy_path(mock_chat: MagicMock) -> None:
    """Successful JSON response is parsed, validated and returned as Diagram."""
    mock_chat.return_value = {
        "message": {
            "content": (
                '{"mermaid": "flowchart TD\\n    User --> Login", '
                '"explanation": "User authenticates with the system."}'
            )
        }
    }

    engine = DiagramEngine(Settings(ollama_model="llama3.2"))
    diagram = engine.generate(
        "user login flow with OAuth", diagram_type="flowchart"
    )

    assert isinstance(diagram, Diagram)
    assert "User --> Login" in diagram.mermaid
    assert "User authenticates" in diagram.explanation
    assert diagram.diagram_type == "flowchart"
    mock_chat.assert_called_once()


@patch("diatype.generator.ollama.chat")
def test_refine_preserves_structure(mock_chat: MagicMock) -> None:
    """Refine keeps original SVG if present and returns updated Diagram."""
    mock_chat.return_value = {
        "message": {
            "content": (
                '{"mermaid": "flowchart TD\\n    User --> Login\\n    Login --> Dashboard", '
                '"explanation": "Added dashboard step."}'
            )
        }
    }

    engine = DiagramEngine()
    original = Diagram(
        mermaid="flowchart TD\n    User --> Login",
        explanation="Original flow",
        diagram_type="flowchart",
        svg="<svg>original</svg>",
    )

    refined = engine.refine(original, "add a dashboard after login")

    assert "Dashboard" in refined.mermaid
    assert refined.svg == "<svg>original</svg>"
    assert "Added dashboard step" in refined.explanation


@patch("diatype.generator.ollama.chat")
def test_explain_fallback_on_error(mock_chat: MagicMock) -> None:
    """Explain falls back to a helpful message when the LLM call fails."""
    mock_chat.side_effect = RuntimeError("Ollama unavailable")

    engine = DiagramEngine()
    diagram = Diagram(
        mermaid="flowchart TD\n    A --> B",
        explanation="Original",
        diagram_type="flowchart",
    )
    result = engine.explain(diagram)

    assert "could not generate an explanation" in result.lower()
    assert "Diagram source" in result


def test_parse_llm_response_json_and_fallback() -> None:
    """Internal parser handles both strict JSON and markdown-wrapped output."""
    engine = DiagramEngine()

    # Pure JSON
    json_content = '{"mermaid":"flowchart TD\\nA-->B","explanation":"JSON test"}'
    d1 = engine._parse_llm_response(json_content, "flowchart")  # type: ignore[attr-defined]
    assert "A-->B" in d1.mermaid
    assert "JSON test" in d1.explanation

    # Markdown-like fallback
    md_content = (
        'Here is a diagram:\n'
        '```mermaid\n'
        'sequenceDiagram\n'
        '    Alice->>Bob: hello\n'
        '```\n'
        'Explanation: they are talking.'
    )
    d2 = engine._parse_llm_response(md_content, "sequenceDiagram")  # type: ignore[attr-defined]
    assert "Alice->>Bob" in d2.mermaid
    assert d2.diagram_type == "sequenceDiagram"


def test_error_cases() -> None:
    """Input validation raises clear errors before hitting the LLM."""
    engine = DiagramEngine()

    with pytest.raises(ValueError, match="at least 8 characters"):
        engine.generate("short")

    with pytest.raises(TypeError, match="must be an instance of Diagram"):
        engine.refine("not-a-diagram", "add something")

    with pytest.raises(ValueError, match="at least 3 characters"):
        engine.refine(
            Diagram(mermaid="flowchart TD\nA-->B", explanation="ok"),
            "  ",
        )


def test_validator_integration_in_parse() -> None:
    """Bad mermaid after sanitization raises a user-friendly error."""
    engine = DiagramEngine()
    with pytest.raises(ValueError, match="failed basic validation"):
        # force bad content through the private path
        engine._parse_llm_response(  # type: ignore[attr-defined]
            '{"mermaid":"this is not valid mermaid at all","explanation":"bad"}',
            "flowchart",
        )
