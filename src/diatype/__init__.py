"""DiaType — Natural language to editable Mermaid diagrams with local LLMs.

A complete toolkit for generating, refining, and rendering technical diagrams
entirely offline using Ollama and Mermaid.js. The hand-drawn notebook UI
makes diagram creation feel like sketching on paper. Now exports to Excalidraw
JSON with sketchy hand-drawn styling (Virgil font + roughness) and to draw.io
XML (self-contained file openable in diagrams.net with Mermaid hint).
"""

from .generator import DiagramEngine
from .models import Diagram, DiagramRequest

__version__ = "0.3.0"
__all__ = [
    "Diagram",
    "DiagramEngine",
    "DiagramRequest",
]
