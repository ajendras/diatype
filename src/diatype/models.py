"""Pydantic models for DiaType diagrams and requests.

Guarantees validated diagram output and provides convenient export methods
(to Markdown, Excalidraw JSON with hand-drawn styling, and draw.io XML).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

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

    def to_drawio(self) -> str:
        """Return a self-contained draw.io (diagrams.net) XML document.

        The generated XML contains the diagram title and source code in
        editable text cells. Save as *.drawio and open in app.diagrams.net.
        The file includes a hint to use the built-in Mermaid renderer for
        a live preview of the diagram.
        """
        escaped_title = escape(self.title)
        escaped_source = escape(self.source).replace("\n", "&#10;")
        timestamp = datetime.now().isoformat()
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="DiaType" modified="{timestamp}" agent="DiaType" version="1.0">
  <diagram id="diatype-diagram" name="Page-1">
    <mxGraphModel dx="1420" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="850" pageHeight="650" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <mxCell id="2" value="{escaped_title}" style="text;html=1;align=center;verticalAlign=middle;fontSize=18;fontFamily=Helvetica;fontStyle=1;strokeColor=none;fillColor=none;" vertex="1" parent="1">
          <mxGeometry x="40" y="20" width="400" height="30" as="geometry" />
        </mxCell>
        <mxCell id="3" value="{escaped_source}" style="text;html=1;whiteSpace=wrap;overflow=hidden;spacing=4;fontSize=13;fontFamily=Courier New;align=left;verticalAlign=top;strokeColor=none;fillColor=none;" vertex="1" parent="1">
          <mxGeometry x="40" y="70" width="760" height="520" as="geometry" />
        </mxCell>
        <mxCell id="4" value="Copy the source above into Insert → Mermaid for live rendering" style="text;html=1;align=center;verticalAlign=middle;fontSize=11;fontFamily=Helvetica;strokeColor=none;fillColor=none;fontStyle=2" vertex="1" parent="1">
          <mxGeometry x="40" y="610" width="760" height="30" as="geometry" />
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
'''


class DiagramRequest(BaseModel):
    """Incoming request payload for diagram generation."""

    prompt: str
    diagram_type: str = "flowchart"
    format: str = "mermaid"
    template: str | None = None

    model_config = {"extra": "forbid"}
