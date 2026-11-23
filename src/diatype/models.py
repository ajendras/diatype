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
            f"```{lang}\n{self.source}\n```\n\n"
            f"**Explanation:** {self.explanation or 'No explanation provided.'}"
        )

    def to_excalidraw(self) -> dict[str, Any]:
        """Return Excalidraw v2 scene with hand-drawn styling (Virgil + roughness)."""
        # Lightweight conversion - parses simple flowchart nodes/edges into Excalidraw elements
        elements: list[dict[str, Any]] = [
            {
                "id": "title",
                "type": "text",
                "x": 50,
                "y": 10,
                "text": self.title,
                "fontFamily": 4,  # Virgil (hand-drawn)
                "fontSize": 28,
                "roughness": 1,
            }
        ]

        # Very basic node extraction for demo purposes
        node_matches = re.findall(r"([A-Za-z0-9_]+)\[([^\]]+)\]", self.source)
        for i, (node_id, label) in enumerate(node_matches[:5]):
            elements.append(
                {
                    "id": f"node-{i}",
                    "type": "rectangle",
                    "x": 100 + (i % 3) * 180,
                    "y": 100 + (i // 3) * 120,
                    "width": 140,
                    "height": 70,
                    "label": {"text": label},
                    "strokeColor": "#5d4037",
                    "backgroundColor": "#f9f4e9",
                    "roughness": 2,
                    "strokeWidth": 3,
                    "roundness": {"type": 3},
                }
            )

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

    prompt: str = Field(..., min_length=8)
    diagram_type: str = Field(default="flowchart")
    format: str = Field(default="mermaid")
    template: str | None = Field(
        default=None,
        description="Optional name of a custom template (JSON or source file in template_dir)",
    )
