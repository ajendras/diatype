"""Tests for the DiagramEngine.

Uses pytest and unittest.mock to simulate Ollama responses without
requiring a running LLM instance. Covers happy paths, error handling,
validation, refinement and snapshot-style output checks.
"""

from unittest.mock import patch, MagicMock

import pytest
from pydantic import ValidationError

from src.diatype.config import Settings
from src.diatype.generator import DiagramEngine
from src.diatype.models import Diagram
from src.diatype.validator import validate_mermaid, sanitize


@pytest.fixture
def settings():
    return Settings(
        ollama_model="llama3.2",
        temperature=0.0,
        default_diagram_type="flowchart",
        max_tokens=1200,
    )


@pytest.fixture
def engine(settings):
    return DiagramEngine(settings=settings)


def test_init_default_settings():
    engine = DiagramEngine()
    assert engine.settings.ollama_model == "llama3.2"
    assert engine.settings.temperature == 0.2
    assert "You are an expert Mermaid.js diagramming assistant" in engine._system_prompt


def test_generate_valid_response(engine):
    mock_response = {
        "message": {
            "content": (
                '{"mermaid": "flowchart TD\\n    A[Start] --> B[Process]", '
                '"explanation": "A simple two-step process."}'
            )
        }
    }

    with patch("ollama.chat", return_value=mock_response) as mock_chat:
        diagram = engine.generate("a simple process", "flowchart")

        assert isinstance(diagram, Diagram)
        assert diagram.mermaid.startswith("flowchart")
        assert "Start" in diagram.mermaid
        assert "simple two-step process" in diagram.explanation.lower()
        assert diagram.diagram_type == "flowchart"
        mock_chat.assert_called_once()


def test_generate_with_invalid_prompt(engine):
    with pytest.raises(ValueError, match="at least 8 characters"):
        engine.generate("short")


def test_generate_handles_ollama_error(engine):
    with patch("ollama.chat", side_effect=Exception("Ollama is not running")):
        with pytest.raises(RuntimeError, match="Ollama request failed"):
            engine.generate("anything")


def test_generate_fallback_parsing(engine):
    # Simulate a response that is not strict JSON but contains the fields
    mock_response = {
        "message": {
            "content": (
                'Here is the diagram:\n'
                '```mermaid\n'
                'sequenceDiagram\n'
                '    participant U as User\n'
                '    U->>API: request\n'
                '```\n'
                'Explanation: This shows a user calling an API.'
            )
        }
    }

    with patch("ollama.chat", return_value=mock_response):
        diagram = engine.generate("user calls api", "sequenceDiagram")
        assert diagram.diagram_type == "sequenceDiagram"
        assert "participant U" in diagram.mermaid
        assert "user calling an API" in diagram.explanation.lower()


def test_refine_preserves_structure(engine):
    original = Diagram(
        mermaid="flowchart TD\n    A --> B",
        explanation="Original diagram",
        diagram_type="flowchart",
        svg="<svg>original</svg>",
    )

    mock_response = {
        "message": {
            "content": (
                '{"mermaid": "flowchart TD\\n    A --> B\\n    B --> C[New step]", '
                '"explanation": "Added a new step after B."}'
            )
        }
    }

    with patch("ollama.chat", return_value=mock_response):
        refined = engine.refine(original, "add another step after B")

        assert "C[New step]" in refined.mermaid
        assert refined.svg == "<svg>original</svg>"  # preserved
        assert refined.diagram_type == "flowchart"


def test_refine_rejects_bad_input(engine):
    with pytest.raises(TypeError):
        engine.refine("not a diagram", "add something")

    with pytest.raises(ValueError, match="meaningful string"):
        engine.refine(
            Diagram(mermaid="flowchart TD\nA-->B", explanation="x", diagram_type="flowchart"),
            "  ",
        )


def test_explain_success(engine):
    diagram = Diagram(
        mermaid="flowchart TD\n    A-->B",
        explanation="Test",
        diagram_type="flowchart",
    )

    mock_response = {"message": {"content": "This diagram shows A leading to B."}}

    with patch("ollama.chat", return_value=mock_response):
        explanation = engine.explain(diagram)
        assert "diagram shows A leading to B" in explanation


def test_explain_graceful_fallback(engine):
    diagram = Diagram(
        mermaid="flowchart TD\n    A-->B",
        explanation="Test",
        diagram_type="flowchart",
    )

    with patch("ollama.chat", side_effect=RuntimeError("LLM down")):
        explanation = engine.explain(diagram)
        assert "could not generate an explanation" in explanation.lower()
        assert "A-->B" in explanation


def test_parse_llm_response_strict_json(engine):
    content = (
        '{"mermaid": "graph TD\\n    X-->Y", '
        '"explanation": "A very simple graph."}'
    )
    diagram = engine._parse_llm_response(content, requested_type="flowchart")
    assert diagram.mermaid.startswith("graph")
    assert "simple graph" in diagram.explanation


def test_parse_llm_response_fallback_regex(engine):
    content = 'Some text before\n"mermaid": "flowchart LR\\nA-->B"\nand explanation is "nice".'
    diagram = engine._parse_llm_response(content, requested_type="flowchart")
    assert "A-->B" in diagram.mermaid
    assert "nice" in diagram.explanation.lower()


def test_parse_rejects_invalid_mermaid(engine):
    bad_content = '{"mermaid": "this is not mermaid", "explanation": "bad"}'
    with pytest.raises(RuntimeError):
        # The outer generate method would catch this, but _parse_llm_response
        # is called after sanitize/validate which raises inside generate
        with patch("src.diatype.generator.validate_mermaid", return_value=False):
            engine._parse_llm_response(bad_content, "flowchart")


@pytest.mark.parametrize(
    "prompt,expected_type",
    [
        ("class relationships", "classDiagram"),
        ("user journey", "journey"),
        ("database tables", "erDiagram"),
    ],
)
def test_generate_detects_type(engine, prompt, expected_type):
    mock_response = {
        "message": {
            "content": (
                f'{{"mermaid": "{expected_type} ...", '
                f'"explanation": "Detected type test."}}'
            )
        }
    }

    with patch("ollama.chat", return_value=mock_response):
        diagram = engine.generate(prompt, "auto")
        assert diagram.diagram_type == expected_type


def test_validator_integration():
    assert validate_mermaid("flowchart TD\nA-->B") is True
    assert validate_mermaid("invalid junk") is False
    assert validate_mermaid("") is False

    cleaned = sanitize("```mermaid\nflowchart TD\nA-->B\n```\nSome extra text")
    assert cleaned.startswith("flowchart")
    assert "extra text" not in cleaned


def test_snapshot_common_diagrams(engine, snapshot):
    # Snapshot test for deterministic outputs with temperature=0
    test_cases = [
        "A login sequence with user, frontend, backend and database",
        "Microservice architecture with API gateway, auth service and payment",
        "Class diagram for a library with Book, User and Loan",
    ]

    with patch("ollama.chat") as mock_chat:
        mock_chat.return_value = {
            "message": {
                "content": (
                    '{"mermaid": "flowchart TD\\n    A[User] --> B[Login]\\n    '
                    'B --> C[Database]", "explanation": "Snapshot test diagram."}'
                )
            }
        }

        for case in test_cases:
            diagram = engine.generate(case)
            # Use snapshot to compare the produced model (excluding variable timestamps)
            assert diagram.mermaid
            assert diagram.explanation
            # In real usage the snapshot fixture would compare against stored JSON
            # Here we simply assert structural invariants
            assert len(diagram.mermaid) > 25
            assert "User" in diagram.mermaid or "Login" in diagram.mermaid


def test_settings_propagated_to_ollama_options(settings):
    engine = DiagramEngine(settings)
    opts = engine.settings.get_ollama_options()
    assert opts["temperature"] == 0.0
    assert opts["num_predict"] == 1200
    assert opts["top_p"] == 0.9
