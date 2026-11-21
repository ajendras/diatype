"""Tests for DiagramEngine.

Covers generation (with the new few-shot prompts for mermaid/plantuml/graphviz),
refinement, explanation, transcription, history, parsing fallbacks, validation
integration, error handling, and Diagram utilities.
Ollama and faster-whisper are fully mocked.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

from diatype.config import Settings
from diatype.generator import DiagramEngine
from diatype.models import Diagram


@pytest.fixture
def settings():
    s = Settings(
        ollama_model="llama3.2",
        temperature=0.0,
        max_tokens=500,
        history_enabled=False,
        history_dir=Path("test_history"),
        whisper_model="tiny",
    )
    return s


@pytest.fixture
def engine(settings):
    return DiagramEngine(settings)


def test_build_system_prompt_includes_few_shot_examples(engine):
    """The improved few-shot prompting is present for every supported format."""
    for fmt in ("mermaid", "plantuml", "graphviz"):
        prompt = engine._build_system_prompt(fmt)
        assert "Few-shot examples" in prompt
        assert "Assistant:" in prompt
        assert len(prompt) > 1200, f"Prompt for {fmt} should be rich with examples"


@patch("ollama.chat")
def test_generate_uses_few_shot_prompt(mock_chat, engine):
    """generate() sends the rich few-shot system prompt."""
    mock_chat.return_value = {
        "message": {
            "content": json.dumps(
                {
                    "source": "flowchart TD\n    A[Start] --> B[End]",
                    "explanation": "A minimal test diagram.",
                }
            )
        }
    }

    diagram = engine.generate("a simple start to end flow", diagram_type="flowchart")

    assert diagram.source.startswith("flowchart")
    assert "test diagram" in diagram.explanation.lower()

    messages = mock_chat.call_args.kwargs["messages"]
    system_content = messages[0]["content"]
    assert "Few-shot examples" in system_content
    assert "flowchart TD" in system_content
    assert "sequenceDiagram" in system_content


@patch("ollama.chat")
def test_generate_plantuml(mock_chat, engine):
    mock_chat.return_value = {
        "message": {
            "content": json.dumps(
                {
                    "source": "@startuml\nUser -> App: login\n@enduml",
                    "explanation": "PlantUML login sequence.",
                }
            )
        }
    }
    diagram = engine.generate(
        "user login sequence", diagram_type="sequence", output_format="plantuml"
    )
    assert "@startuml" in diagram.source
    assert diagram.format == "plantuml"
    assert "login" in diagram.source


@patch("ollama.chat")
def test_generate_graphviz(mock_chat, engine):
    mock_chat.return_value = {
        "message": {
            "content": json.dumps(
                {
                    "source": "digraph G {\n  rankdir=LR;\n  A -> B;\n}",
                    "explanation": "Graphviz test graph.",
                }
            )
        }
    }
    diagram = engine.generate(
        "simple dependency", diagram_type="graph", output_format="graphviz"
    )
    assert "digraph" in diagram.source.lower()
    assert diagram.format == "graphviz"


@patch("ollama.chat")
def test_refine_uses_few_shot_prompt(mock_chat, engine):
    """refine() also uses the few-shot system prompt."""
    mock_chat.return_value = {
        "message": {
            "content": json.dumps(
                {
                    "source": "flowchart TD\n    A --> B --> C[Error]",
                    "explanation": "Added error handling.",
                }
            )
        }
    }

    original = Diagram(
        source="flowchart TD\n    A --> B",
        explanation="Original",
        diagram_type="flowchart",
        format="mermaid",
        id="diag_test",
        version=1,
    )

    refined = engine.refine(original, "add an error handling step")

    assert "Error" in refined.source
    messages = mock_chat.call_args.kwargs["messages"]
    assert "Few-shot examples" in messages[0]["content"]
    assert refined.version == 2


@patch("ollama.chat")
def test_explain(mock_chat, engine):
    mock_chat.return_value = {"message": {"content": "This diagram shows a login flow."}}
    diagram = Diagram(
        source="flowchart TD\nUser-->Login",
        explanation="Original explanation",
        diagram_type="flowchart",
        format="mermaid",
    )
    explanation = engine.explain(diagram)
    assert "login flow" in explanation.lower()


@patch("faster_whisper.WhisperModel")
def test_transcribe(mock_whisper, engine, tmp_path):
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([MagicMock(text="Hello this is a test")]), None)
    mock_whisper.return_value = mock_model

    engine._whisper_model = mock_model
    text = engine.transcribe(b"fake audio bytes")
    assert "Hello this is a test" in text


def test_parse_llm_response_json(engine):
    content = '{"source": "flowchart TD\\nA-->B", "explanation": "Parsed from JSON"}'
    diagram = engine._parse_llm_response(
        content, requested_type="flowchart", output_format="mermaid"
    )
    assert diagram.source.startswith("flowchart")
    assert "Parsed from JSON" in diagram.explanation


def test_parse_llm_response_markdown_fallback(engine):
    content = 'Here is the diagram:\n\n```mermaid\nflowchart TD\n    X --> Y\n```\n\nExplanation: Markdown fallback worked.'
    diagram = engine._parse_llm_response(
        content, requested_type="flowchart", output_format="mermaid"
    )
    assert "X --> Y" in diagram.source
    assert "Markdown fallback" in diagram.explanation


def test_parse_llm_response_plantuml(engine):
    content = '{"source": "@startuml\\nA -> B\\n@enduml", "explanation": "PlantUML parsed"}'
    diagram = engine._parse_llm_response(
        content, requested_type="sequence", output_format="plantuml"
    )
    assert "@startuml" in diagram.source
    assert diagram.format == "plantuml"


@patch("ollama.chat")
def test_generate_validation_failure(mock_chat, engine):
    mock_chat.return_value = {
        "message": {"content": '{"source": "invalid gibberish", "explanation": "bad"}'}
    }
    with pytest.raises(RuntimeError, match="Could not parse a valid diagram"):
        engine.generate("bad prompt that produces invalid output")


def test_history_methods_when_disabled(engine):
    engine.settings.history_enabled = False
    assert engine.list_history() == []
    assert engine.load_version("any", 1) is None


@patch("pathlib.Path.mkdir")
@patch("pathlib.Path.write_text")
def test_save_to_history(mock_write, mock_mkdir, engine):
    engine.settings.history_enabled = True
    diagram = Diagram(
        source="flowchart TD\nA-->B",
        explanation="test",
        diagram_type="flowchart",
        format="mermaid",
        id="diag_test123",
        version=1,
    )
    engine.save_to_history(diagram)
    mock_write.assert_called_once()
    assert "diag_test123_v01.json" in str(mock_write.call_args[0][0])


def test_to_excalidraw_integration():
    """Test that the Diagram model (used by engine) produces valid Excalidraw."""
    diagram = Diagram(
        source="flowchart TD\nA-->B",
        explanation="A simple test diagram for export.",
        diagram_type="flowchart",
        format="mermaid",
    )
    ex = diagram.to_excalidraw()
    assert ex["type"] == "excalidraw"
    assert ex["version"] == 2
    assert any(e["text"] == "Flowchart Diagram" for e in ex["elements"])
    assert any("A-->B" in e.get("text", "") for e in ex["elements"])


def test_error_on_bad_prompt(engine):
    with pytest.raises(ValueError):
        engine.generate("")
    with pytest.raises(ValueError):
        engine.generate("short")


def test_load_version_not_found(engine):
    assert engine.load_version("nonexistent", 99) is None
