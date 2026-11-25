"""Tests for the DiagramEngine and related components.

Covers generation (Mermaid/PlantUML/Graphviz), refinement, explanation,
transcription, history persistence, bulk generation, templates, parsing
fallbacks, validation integration and error handling. Consistent with
the production code style and the snapshot-style checks described in README.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from diatype.config import Settings
from diatype.generator import DiagramEngine
from diatype.models import Diagram
from diatype.validator import validate_source, detect_diagram_type


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Settings fixture that uses temporary directories for isolation."""
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    return Settings(
        ollama_model="llama3.2",
        temperature=0.2,
        default_diagram_type="flowchart",
        default_format="mermaid",
        history_dir=history_dir,
        output_dir=output_dir,
        template_dir=template_dir,
        history_enabled=True,
        max_history=5,
        whisper_model="base",
    )


@pytest.fixture
def engine(test_settings: Settings) -> DiagramEngine:
    """Engine under test wired to the isolated settings."""
    return DiagramEngine(test_settings)


@pytest.fixture
def mock_ollama(mocker):
    """Mock for ollama.chat that returns a minimal valid JSON response."""
    mock = mocker.patch("diatype.generator.ollama.chat")
    mock.return_value = {
        "message": {
            "content": (
                '{"source": "flowchart TD\\n    A[Start] --> B[End]", '
                '"explanation": "Simple linear process."}'
            )
        }
    }
    return mock


@pytest.fixture
def mock_whisper(mocker):
    """Mock for faster-whisper model."""
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (
        [MagicMock(text="This is a test diagram of user login")],
        None,
    )
    mocker.patch("diatype.generator.WhisperModel", return_value=mock_model)
    return mock_model


def test_generate_basic(engine: DiagramEngine, mock_ollama):
    """Basic generation produces a validated Diagram."""
    diagram = engine.generate(
        "User logs in via OAuth then reaches the dashboard"
    )
    assert diagram.id.startswith("diag_")
    assert diagram.version == 1
    assert "flowchart" in diagram.source.lower()
    assert diagram.explanation
    assert diagram.format == "mermaid"
    assert diagram.prompt == "User logs in via OAuth then reaches the dashboard"


def test_generate_plantuml(engine: DiagramEngine, mock_ollama):
    """PlantUML output path is exercised and validated."""
    mock_ollama.return_value = {
        "message": {
            "content": (
                '{"source": "@startuml\\nUser -> Service: login\\n@enduml", '
                '"explanation": "Login sequence."}'
            )
        }
    }
    diagram = engine.generate(
        "user login sequence",
        output_format="plantuml",
        diagram_type="sequence",
    )
    assert "@startuml" in diagram.source
    assert diagram.format == "plantuml"
    assert "@enduml" in diagram.source
    validate_source(diagram.source, "plantuml")


def test_generate_graphviz(engine: DiagramEngine, mock_ollama):
    """Graphviz (DOT) output path is exercised."""
    mock_ollama.return_value = {
        "message": {
            "content": (
                '{"source": "digraph G { A -> B }", '
                '"explanation": "Dependency graph."}'
            )
        }
    }
    diagram = engine.generate(
        "service dependencies",
        output_format="graphviz",
        diagram_type="graph",
    )
    assert "digraph" in diagram.source
    assert diagram.format == "graphviz"
    validate_source(diagram.source, "graphviz")


def test_generate_with_template(engine: DiagramEngine, mock_ollama, test_settings):
    """Custom template is loaded and merged into the prompt."""
    template_data = {
        "name": "web_app",
        "description": "Modern web stack",
        "diagram_type": "flowchart",
        "format": "mermaid",
        "base_source": "flowchart LR\n    UI --> API\n    API --> DB",
    }
    (test_settings.template_dir / "web_app.json").write_text(
        json.dumps(template_data), encoding="utf-8"
    )

    mock_ollama.return_value = {
        "message": {
            "content": (
                '{"source": "flowchart LR\\n    UI --> API\\n    API --> DB\\n    '
                'DB --> Cache", "explanation": "Added caching layer."}'
            )
        }
    }

    diagram = engine.generate(
        "add Redis cache layer",
        template="web_app",
    )
    assert "UI" in diagram.source
    assert "Cache" in diagram.source
    assert diagram.template == "web_app"
    assert diagram.diagram_type == "flowchart"


def test_refine(engine: DiagramEngine, mock_ollama):
    """Refinement increments version and respects instruction."""
    original = Diagram(
        id="diag_refine",
        title="Login Flow",
        source="flowchart TD\nA[Login] --> B[Dashboard]",
        explanation="Initial login flow",
        diagram_type="flowchart",
        format="mermaid",
        version=1,
        prompt="original prompt",
    )
    mock_ollama.return_value = {
        "message": {
            "content": (
                '{"source": "flowchart TD\\nA[Login] --> B[Dashboard]\\n'
                'B --> C[Error Handling]", '
                '"explanation": "Added error handling step."}'
            )
        }
    }
    refined = engine.refine(original, "add error handling with retry")
    assert "Error Handling" in refined.source
    assert refined.version == 2
    assert refined.id == original.id
    assert refined.prompt == original.prompt


def test_explain(engine: DiagramEngine, mock_ollama):
    """Explanation calls the LLM with a descriptive prompt."""
    mock_ollama.return_value = {
        "message": {"content": "This diagram illustrates a typical OAuth login sequence."}
    }
    diagram = Diagram(
        source="flowchart TD\nUser --> Auth",
        explanation="",
        format="mermaid",
    )
    result = engine.explain(diagram)
    assert "OAuth" in result or "login" in result.lower()


def test_transcribe(engine: DiagramEngine, mock_whisper):
    """Local transcription returns cleaned text from audio bytes."""
    audio = b"dummy-webm-audio-data-long-enough-to-pass-validation"
    text = engine.transcribe(audio)
    assert "test diagram of user login" in text


def test_save_to_history(engine: DiagramEngine, test_settings):
    """History persistence writes the expected JSON file with correct naming.

    Updated from previous fragile mock.call_args string check (which no
    longer contained the filename after the switch to Path.write_text).
    Now directly inspects the filesystem – the proper way to test side
    effects of _save_to_history.
    """
    diagram = Diagram(
        id="diag_test123",
        title="Untitled Diagram",
        source="flowchart TD\nA-->B",
        explanation="",
        prompt="",
        version=1,
        created_at="2026-11-23T18:22:39.433025",
        template=None,
        diagram_type="flowchart",
        format="mermaid",
    )
    engine.save_to_history(diagram)

    history_files = sorted(test_settings.history_dir.glob("*.json"))
    assert len(history_files) == 1
    assert history_files[0].name == "diag_test123_v01.json"

    content = json.loads(history_files[0].read_text(encoding="utf-8"))
    assert content["id"] == "diag_test123"
    assert content["version"] == 1
    assert content["source"] == "flowchart TD\nA-->B"
    assert content["created_at"] == "2026-11-23T18:22:39.433025"


def test_list_history(engine: DiagramEngine, test_settings):
    """list_history returns newest-first entries limited by max."""
    d1 = Diagram(
        id="diag_old",
        version=1,
        source="old",
        created_at="2025-01-01T00:00:00",
    )
    d2 = Diagram(
        id="diag_new",
        version=1,
        source="new",
        created_at="2026-01-01T00:00:00",
    )
    engine._save_to_history(d1)
    engine._save_to_history(d2)

    entries = engine.list_history(limit=10)
    assert len(entries) == 2
    assert entries[0]["id"] == "diag_new"
    assert entries[1]["id"] == "diag_old"


def test_load_version(engine: DiagramEngine, test_settings):
    """load_version retrieves a specific historic snapshot by id+version."""
    diagram = Diagram(
        id="diag_loadtest",
        version=3,
        source="flowchart TD\nX-->Y",
        created_at="2026-11-23T10:00:00",
    )
    engine._save_to_history(diagram)

    loaded = engine.load_version("diag_loadtest", 3)
    assert loaded is not None
    assert loaded.id == "diag_loadtest"
    assert loaded.version == 3
    assert loaded.source == "flowchart TD\nX-->Y"

    assert engine.load_version("diag_loadtest", 9) is None


def test_bulk_generate(engine: DiagramEngine, mock_ollama, test_settings, tmp_path):
    """Bulk processes every .md file as an independent prompt."""
    req_dir = tmp_path / "requirements"
    req_dir.mkdir()
    (req_dir / "auth.md").write_text(
        "OAuth login flow with validation and error path.", encoding="utf-8"
    )
    (req_dir / "services.md").write_text(
        "Microservice architecture with gateway and DB.", encoding="utf-8"
    )

    out_dir = tmp_path / "bulk_out"
    diagrams = engine.bulk_generate(
        input_dir=req_dir,
        output_dir=out_dir,
        diagram_type="flowchart",
        output_format="mermaid",
    )

    assert len(diagrams) == 2
    assert out_dir.exists()
    assert (out_dir / "auth.mmd").exists()
    assert (out_dir / "services.mmd").exists()
    assert (out_dir / "auth.md").exists()
    assert diagrams[0].title == "Auth"
    assert diagrams[1].title == "Services"


def test_list_templates(engine: DiagramEngine, test_settings):
    """list_templates discovers both JSON and plain-source templates."""
    json_tpl = {
        "name": "api_flow",
        "description": "Standard API call flow",
        "diagram_type": "sequence",
        "format": "mermaid",
    }
    (test_settings.template_dir / "api_flow.json").write_text(
        json.dumps(json_tpl), encoding="utf-8"
    )
    (test_settings.template_dir / "custom.puml").write_text(
        "@startuml\nActor -> System\n@enduml", encoding="utf-8"
    )

    templates = engine.list_templates()
    names = {t["name"] for t in templates}
    assert "api_flow" in names
    assert "custom" in names
    assert any(t["format"] == "plantuml" for t in templates)


def test_parse_llm_response_json(engine: DiagramEngine):
    """JSON extraction from LLM output works even with surrounding text."""
    raw = (
        "Here is the diagram:\n"
        '{"source": "flowchart TD\\nA-->B", "explanation": "Test diagram"}\n'
        "End of response."
    )
    parsed = engine._parse_llm_response(raw, "mermaid")
    assert parsed["source"] == "flowchart TD\nA-->B"
    assert parsed["explanation"] == "Test diagram"


def test_parse_llm_response_codeblock_fallback(engine: DiagramEngine):
    """Code-block fallback is used when JSON extraction fails."""
    raw = "Some explanation...\n```mermaid\nflowchart TD\n    X --> Y\n```"
    parsed = engine._parse_llm_response(raw, "mermaid")
    assert "X --> Y" in parsed["source"]
    assert "Diagram generated and validated by DiaType" in parsed["explanation"]


def test_parse_llm_response_raw_fallback(engine: DiagramEngine):
    """Raw content fallback when neither JSON nor fence is present."""
    raw = "flowchart TD\n    A --> B"
    parsed = engine._parse_llm_response(raw, "mermaid")
    assert parsed["source"] == "flowchart TD\n    A --> B"


def test_invalid_prompt_raises(engine: DiagramEngine):
    """Short prompts are rejected early."""
    with pytest.raises(ValueError, match="at least 8 characters"):
        engine.generate("hi")


def test_validator_integration(engine: DiagramEngine, mock_ollama):
    """Invalid diagram source from LLM raises RuntimeError."""
    mock_ollama.return_value = {
        "message": {"content": '{"source": "INVALID SYNTAX", "explanation": "bad"}'}
    }
    with pytest.raises(RuntimeError, match="Could not parse a valid diagram"):
        engine.generate("bad prompt that produces invalid syntax")


def test_history_pruning(engine: DiagramEngine, test_settings):
    """Old history files are pruned when max_history is exceeded."""
    test_settings.max_history = 2
    for i in range(4):
        d = Diagram(
            id=f"diag_prune_{i}",
            version=1,
            source=f"diagram {i}",
            created_at=f"2026-01-0{i}T00:00:00",
        )
        engine._save_to_history(d)

    files = list(test_settings.history_dir.glob("*.json"))
    assert len(files) == 2
    names = {f.name for f in files}
    assert "diag_prune_2_v01.json" in names
    assert "diag_prune_3_v01.json" in names
