"""Unit tests for DiagramEngine.

Covers JSON parsing, regex fallback, generation, refinement, history, and multi-format support.
Ollama is mocked to avoid real LLM calls during testing.
"""

from unittest.mock import patch
import json
import pytest
from pathlib import Path

from diatype.generator import DiagramEngine
from diatype.models import Diagram
from diatype.config import Settings


@pytest.fixture
def test_settings(tmp_path: Path):
    settings = Settings(
        ollama_model="llama3.2-test",
        temperature=0.0,
        history_enabled=True,
        history_dir=tmp_path / "history",
        output_dir=tmp_path / "output",
    )
    settings.history_dir.mkdir(exist_ok=True)
    return settings


@pytest.fixture
def engine(test_settings):
    return DiagramEngine(test_settings)


def test_parse_json_and_regex_fallback(engine):
    """Verify both JSON parsing and regex-based fallback work as expected."""
    with patch("ollama.chat") as mock:
        # JSON path
        mock.return_value = {"message": {"content": '{"source": "flowchart TD\\n    A --> B", "explanation": "Test diagram"}'}}
        d1 = engine.generate("A simple test flow", diagram_type="flowchart")
        assert d1.source.startswith("flowchart")
        assert "Test diagram" in d1.explanation

        # regex fallback path (non-JSON response)
        mock.return_value = {"message": {"content": 'Some text "source" : "graph TD\\nX-->Y" , "explanation":"fallback"'}}
        d2 = engine.generate("fallback test")
        assert "X-->Y" in d2.source or d2.source.startswith("graph")


def test_generate_success(engine):
    """Test that generate produces a valid Diagram with expected attributes."""
    with patch("ollama.chat") as mock:
        mock.return_value = {
            "message": {
                "content": json.dumps({
                    "source": "graph TD\n    A[Start] --> B[End]",
                    "explanation": "A basic graph."
                })
            }
        }
        diagram = engine.generate(
            "Create a basic graph of start to end",
            diagram_type="graph"
        )
        assert diagram.source.startswith(("flowchart", "graph"))
        assert diagram.explanation == "A basic graph."
        assert diagram.format == "mermaid"
        assert diagram.is_renderable()


def test_refine(engine):
    """Test the refine method appends changes correctly and increments version."""
    base = Diagram(
        source="flowchart TD\n    A[User] --> B[Login]",
        explanation="Initial login flow",
        diagram_type="flowchart",
        format="mermaid",
        id="test-diag-001",
        version=1,
    )
    with patch("ollama.chat") as mock:
        mock.return_value = {
            "message": {
                "content": json.dumps({
                    "source": "flowchart TD\n    A[User] --> B[Login]\n    B --> C[Error Handler]\n    C -->|retry| B",
                    "explanation": "Added error handler with retry."
                })
            }
        }
        refined = engine.refine(base, "add error handling step and a retry loop")
        assert "Error Handler" in refined.source
        assert refined.version >= 2
        assert refined.id == "test-diag-001"


def test_history_methods(engine):
    """Test save_to_history, list_history and load_version work end-to-end."""
    with patch("ollama.chat") as mock:
        mock.return_value = {
            "message": {"content": json.dumps({"source": "flowchart TD\nA-->B", "explanation": "History test"}) }
        }
        diagram = engine.generate("test for history")
        engine.save_to_history(diagram)
        history_list = engine.list_history(limit=5)
        assert len(history_list) >= 1
        assert any(h["id"] == diagram.id for h in history_list)
        loaded = engine.load_version(diagram.id, diagram.version)
        assert loaded is not None
        assert loaded.source == diagram.source
        assert loaded.explanation == diagram.explanation


def test_plantuml_and_graphviz(engine):
    """Test support for additional output formats."""
    with patch("ollama.chat") as mock:
        mock.return_value = {
            "message": {
                "content": json.dumps({
                    "source": "@startuml\nAlice -> Bob : Authenticate\n@enduml",
                    "explanation": "PlantUML sequence"
                })
            }
        }
        puml = engine.generate("user auth sequence", "sequence", output_format="plantuml")
        assert puml.format == "plantuml"
        assert "@startuml" in puml.source
        assert puml.to_markdown().startswith("```plantuml")

        mock.return_value = {
            "message": {
                "content": json.dumps({
                    "source": "digraph G {\n  rankdir=LR\n  A -> B\n}",
                    "explanation": "Graphviz dep graph"
                })
            }
        }
        dot = engine.generate("dependencies", output_format="graphviz")
        assert dot.format == "graphviz"
        assert "digraph" in dot.source


def test_excalidraw_export():
    """Test the to_excalidraw method produces valid structure."""
    diagram = Diagram(
        source="flowchart TD\n    Login --> Dashboard",
        explanation="Simple flow",
        diagram_type="flowchart",
        format="mermaid",
    )
    excal = diagram.to_excalidraw()
    assert excal["type"] == "excalidraw"
    assert excal["version"] == 2
    assert isinstance(excal["elements"], list)
    assert len(excal["elements"]) > 0
    assert "appState" in excal


def test_explain_method(engine):
    with patch("ollama.chat") as mock:
        mock.return_value = {"message": {"content": "This diagram illustrates a user logging into a system."}}
        diagram = Diagram(
            source="flowchart TD\nA-->B",
            explanation="original",
            diagram_type="flowchart",
            format="mermaid",
        )
        explanation = engine.explain(diagram)
        assert len(explanation) > 10
