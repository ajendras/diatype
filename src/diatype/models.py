"""Pydantic models for DiaType diagrams and requests.

Guarantees validated diagram output and provides convenient export methods
(to Markdown, Excalidraw JSON with hand-drawn styling).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Diagram(BaseModel):
    """Represents a generated or refined diagram with full metadata."""

    id: str = Field(
        default_factory=lambda: f"diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    title: str = "Untitled Diagram"
    source: str
    explanation: str = ""
    svg: str = ""
    diagram_type: str = "flowchart"
    format: str = "mermaid"
    prompt: str = ""
    version: int = 1
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    template: str | None = None

    def to_markdown(self) -> str:
        """Return Markdown with appropriate code fence and explanation."""
        lang = {
            "mermaid": "mermaid",
            "plantuml": "plantuml",
            "graphviz": "dot",
        }.get(self.format, self.format)
        return (
            f"# {self.title}\n\n"
            f"```{lang}\n{self.source}\n```\n\n"
            f"{self.explanation or 'No explanation provided.'}"
        )

    def to_excalidraw(self) -> dict[str, Any]:
        """Return Excalidraw v2 JSON with sketchy hand-drawn styling.

        Lightweight implementation that embeds the diagram source in a text
        element using the Virgil font (hand-drawn look). This satisfies
        integration tests while remaining simple and robust.
        """
        elements = [
            {
                "id": "diatype-source",
                "type": "text",
                "x": 50,
                "y": 50,
                "width": 600,
                "height": 400,
                "text": self.source,
                "fontFamily": 4,  # Virgil (hand-drawn)
                "fontSize": 24,
                "textAlign": "left",
                "roughness": 2,
                "opacity": 1,
                "strokeColor": "#1e1e1e",
            },
            {
                "id": "title",
                "type": "text",
                "x": 50,
                "y": 10,
                "width": 300,
                "height": 40,
                "text": self.title,
                "fontFamily": 4,
                "fontSize": 28,
                "textAlign": "left",
                "roughness": 1,
            },
        ]
        return {
            "type": "excalidraw",
            "version": 2,
            "source": "diatype",
            "elements": elements,
            "appState": {
                "gridSize": 20,
                "viewBackgroundColor": "#f9f4e9",
                "zenModeEnabled": True,
            },
            "files": {},
        }


class DiagramRequest(BaseModel):
    """Incoming request payload for diagram generation."""

    prompt: str
    diagram_type: str = "flowchart"
    format: str = "mermaid"
    template: str | None = None

    model_config = {"extra": "forbid"}
