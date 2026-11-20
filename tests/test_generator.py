"""Tests for DiagramEngine.

Covers JSON parsing, regex/code-block fallback, diagram_type validation (including 'graph'),
history persistence/loading, and error handling. Ollama calls are mocked.
"""

from unittest.mock import patch

import pytest

from diatype.config import Settings
from diatype.generator import DiagramEngine
from diatype.models import Diagram


@pytest.fixture
def test_settings(tmp_path):
    settings = Settings(
        ollama_model="llama3.2",
        temperature=0.2,
        default_diagram_type="flowchart",
        default_format="mermaid",
        history_enabled=True,
        history_dir=tmp_path / "history",
        output_dir=tmp_path / "output",
        max_history=5,
    )
    settings.history_dir.mkdir(parents=True, exist_ok=True)
    return settings


@pytest.fixture
def engine(test_settings):
    return DiagramEngine(test_settings)


@patch("ollama.chat")
def test_parse_json_and_regex_fallback(mock_chat, engine):
    """Test both JSON parsing and regex/code-block fallback paths."""
    # JSON path
    mock_chat.return_value = {
        "message": {
            "content": '{"source": "flowchart TD\\n    A[Start] --> B[End]", "explanation": "Simple test diagram."}'
        }
    }
    d1 = engine.generate("simple test")
    assert d1.source.startswith("flowchart")
    assert "Simple test diagram" in d1.explanation

    # regex + code-block fallback (text before/after fence)
    mock_chat.return_value = {
        "message": {
            "content": """Here's a diagram for you:

```mermaid
graph TD
    User --> Login
    Login --> Dashboard
```

Explanation: This shows a basic user flow."""
        }
    }
    d2 = engine.generate("fallback test")
    assert d2 is not None
    assert any(kw in d2.source.lower() for kw in ["graph", "user", "login", "dashboard"])
    assert "basic user flow" in d2.explanation.lower()
    assert d2.diagram_type in ("flowchart", "graph")


@patch("ollama.chat")
def test_generate_success(mock_chat, engine):
    """Test successful generation with 'graph' diagram_type (was previously rejected by pattern)."""
    mock_chat.return_value = {
        "message": {
            "content": '{"source": "graph TD\\n    A --> B", "explanation": "Success test."}'
        }
    }
    diagram = engine.generate(
        "test prompt for graph",
        diagram_type="graph",
        output_format="mermaid",
    )
    assert diagram is not None
    assert diagram.diagram_type in ("flowchart", "graph")
    assert any(kw in diagram.source for kw in ["graph TD", "A --> B"])
    assert "Success test" in diagram.explanation


@patch("ollama.chat")
def test_history_methods(mock_chat, engine, test_settings):
    """Test history save, list, and load (extra saved_at field must be ignored)."""
    mock_chat.return_value = {
        "message": {
            "content": '{"source": "flowchart TD\\n    A --> B", "explanation": "History test."}'
        }
    }
    d = engine.generate("history test prompt")
    assert d.id.startswith("diag_")
    assert d.version == 1

    history = engine.list_history(limit=5)
    assert len(history) >= 1
    assert any(entry["id"] == d.id for entry in history)

    loaded = engine.load_version(d.id, d.version)
    assert loaded is not None
    assert loaded.source == d.source
    assert loaded.explanation == d.explanation
    assert loaded.id == d.id
    assert loaded.version == d.version

    # non-existent version returns None
    assert engine.load_version("nonexistent-id", 99) is None
