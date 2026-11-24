import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from diatype.config import Settings
from diatype.generator import DiagramEngine
from diatype.models import Diagram


@pytest.fixture
def mock_settings(tmp_path):
    settings = Settings(
        ollama_model="llama3.2",
        history_enabled=True,
        history_dir=tmp_path / "history",
        output_dir=tmp_path / "output",
        template_dir=tmp_path / "templates",
        default_format="mermaid",
    )
    settings.history_dir.mkdir(exist_ok=True)
    settings.output_dir.mkdir(exist_ok=True)
    settings.template_dir.mkdir(exist_ok=True)
    return settings


@pytest.fixture
def engine(mock_settings):
    return DiagramEngine(mock_settings)


@pytest.fixture
def mock_ollama():
    with patch("diatype.generator.ollama.chat") as m:
        yield m


@pytest.fixture
def mock_whisper():
    with patch("diatype.generator.WhisperModel") as m:
        instance = MagicMock()
        instance.transcribe.return_value = (
            [MagicMock(text="transcribed text")],
            None,
        )
        m.return_value = instance
        yield m


def test_build_system_prompt_includes_few_shot_examples(engine):
    prompt = engine._build_system_prompt("mermaid", "flowchart")
    assert "You are an expert software architect" in prompt
    assert "Few-shot examples:" in prompt
    assert "flowchart TD" in prompt
    assert "OAuth login sequence between user and API." in prompt
    assert "Output ONLY a single JSON object" in prompt


def test_parse_llm_response_json(engine):
    content = '{"source": "flowchart TD\\nA-->B", "explanation": "test"}'
    parsed = engine._parse_llm_response(content, "mermaid")
    assert isinstance(parsed, dict)
    assert parsed["source"].startswith("flowchart")
    assert parsed["explanation"] == "test"


def test_parse_llm_response_markdown_fallback(engine):
    content = "Here is a diagram:\n\n```mermaid\nX --> Y\n```"
    parsed = engine._parse_llm_response(content, "mermaid")
    assert isinstance(parsed, dict)
    assert "X --> Y" in parsed["source"]


def test_parse_llm_response_plantuml(engine):
    content = '{"source": "@startuml\\nAlice -> Bob : hello\\n@enduml", "explanation": "puml"}'
    parsed = engine._parse_llm_response(content, "plantuml")
    assert isinstance(parsed, dict)
    assert "@startuml" in parsed["source"]


def test_generate_validation_failure(engine, mock_ollama):
    # Force validation failure path (parse succeeds but validate_source fails)
    mock_ollama.return_value = {
        "message": {"content": "this is definitely not valid mermaid syntax"}
    }
    with patch("diatype.generator.validate_source") as mock_validate:
        mock_validate.side_effect = ValueError("Invalid diagram syntax")
        with pytest.raises(RuntimeError, match="Could not parse a valid diagram"):
            engine.generate("bad prompt that should fail validation")


def test_save_to_history(engine, mock_settings):
    diagram = Diagram(
        id="diag_test123",
        title="Untitled Diagram",
        source="flowchart TD\nA-->B",
        explanation="test explanation",
        format="mermaid",
        prompt="",
        version=1,
        created_at="2026-11-23T18:22:39.433025",
        template=None,
    )
    with patch.object(Path, "write_text") as mock_write:
        engine.save_to_history(diagram)
        mock_write.assert_called_once()
        # write_text is called with (content, encoding=...)
        content = mock_write.call_args.args[0]
        assert '"id": "diag_test123"' in content
        assert '"version": 1' in content
        assert "flowchart TD" in content
        # history file uses padded version for lexical ordering
        assert "diag_test123_v01.json" in str(mock_write.call_args)


def test_to_excalidraw_integration():
    diagram = Diagram(
        source="flowchart TD\n    A-->B",
        explanation="test",
        diagram_type="flowchart",
        format="mermaid",
        title="Test Diagram",
    )
    ex = diagram.to_excalidraw()
    assert ex["type"] == "excalidraw"
    assert ex["source"] == "diatype"
    assert "elements" in ex
    assert any("A-->B" in e.get("text", "") for e in ex["elements"])
    assert any("Test Diagram" in e.get("text", "") for e in ex["elements"])


@patch("diatype.generator.ollama.chat")
def test_refine(mock_chat, engine):
    mock_chat.return_value = {
        "message": {
            "content": '{"source": "flowchart TD\\nA-->B\\nB-->C", "explanation": "refined with extra step"}'
        }
    }
    original = Diagram(
        id="test123",
        source="flowchart TD\nA-->B",
        explanation="original",
        format="mermaid",
        version=1,
    )
    refined = engine.refine(original, "add another step")
    assert refined.version == 2
    assert "C" in refined.source
    assert "refined with extra step" in refined.explanation


def test_transcribe(engine, mock_whisper):
    text = engine.transcribe(b"fake-audio-data-long-enough")
    assert text == "transcribed text"


def test_list_templates(engine, mock_settings):
    template_file = mock_settings.template_dir / "web_app.json"
    template_file.write_text(
        json.dumps(
            {
                "name": "web_app",
                "description": "Modern web stack",
                "diagram_type": "flowchart",
                "format": "mermaid",
                "base_source": "flowchart LR\nBrowser-->Server",
            }
        )
    )
    templates = engine.list_templates()
    assert any(t["name"] == "web_app" for t in templates)


@patch("diatype.generator.ollama.chat")
def test_bulk_generate(mock_chat, engine, mock_settings, tmp_path):
    mock_chat.return_value = {
        "message": {"content": '{"source": "flowchart TD\\nA-->B", "explanation": "ok"}'}
    }
    req_dir = tmp_path / "requirements"
    req_dir.mkdir()
    (req_dir / "auth.md").write_text("OAuth login flow")
    (req_dir / "services.md").write_text("Microservice architecture")

    diagrams = engine.bulk_generate(
        input_dir=req_dir,
        output_dir=tmp_path / "bulk_out",
        diagram_type="flowchart",
        output_format="mermaid",
    )
    assert len(diagrams) == 2
    assert (tmp_path / "bulk_out" / "auth.mmd").exists()
    assert (tmp_path / "bulk_out" / "auth.md").exists()


def test_history_roundtrip(engine, mock_settings):
    diagram = Diagram(
        id="hist_test",
        source="flowchart TD\nX-->Y",
        explanation="history test",
        format="mermaid",
        version=1,
    )
    engine.save_to_history(diagram)
    loaded = engine.load_version("hist_test", 1)
    assert loaded is not None
    assert loaded.source == diagram.source
    assert loaded.version == 1
