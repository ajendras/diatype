"""DiaType — Natural language to editable Mermaid diagrams with local LLMs.

A complete toolkit for generating, refining, and rendering technical diagrams
entirely offline using Ollama and Mermaid.js. The hand-drawn notebook UI
makes diagram creation feel like sketching on paper.
"""

from .generator import DiagramEngine
from .models import Diagram, DiagramRequest

__version__ = "0.1.0"
__all__ = [
    "Diagram",
    "DiagramEngine",
    "DiagramRequest",
]
