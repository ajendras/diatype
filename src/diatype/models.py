"""Pydantic models for DiaType request/response data.

All models include strict validation, helpful error messages, and
domain-specific properties to ensure only valid diagram data flows
through the system.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DiagramRequest(BaseModel):
    """Request to generate or refine a diagram from natural language.

    The prompt is validated for reasonable length to prevent abuse and
    ensure the LLM receives focused instructions.
    """

    prompt: str = Field(
        ...,
        min_length=8,
        max_length=4000,
        description="Natural language description of the desired diagram or refinement instruction.",
        examples=["A user login flow with authentication service and database"],
    )

    diagram_type: str = Field(
        default="flowchart",
        pattern=r"^(flowchart|sequenceDiagram|classDiagram|stateDiagram|erDiagram|journey|gantt|pie|quadrantChart|requirementDiagram|mindmap|timeline|gitGraph|c4Diagram|sequence|class|activity|state|component|object|deployment|graph)$",
        description="Diagram kind hint. Must be one of the supported values (Mermaid kinds or common PlantUML/Graphviz equivalents).",
        examples=["flowchart", "sequenceDiagram", "sequence"],
    )

    format: str = Field(
        default="mermaid",
        pattern=r"^(mermaid|plantuml|graphviz)$",
        description="The output format to request from the LLM.",
    )


class Diagram(BaseModel):
    """Represents a generated or refined diagram.

    Uses `source` for the diagram code and `format` to indicate mermaid/plantuml/graphviz.
    All instances are validated by validator.py before creation.
    """

    source: str = Field(..., min_length=10, description="The raw diagram source.")
    explanation: str = Field(default="Diagram generated successfully.", description="LLM explanation.")
    diagram_type: str = "flowchart"
    format: str = "mermaid"
    svg: str = Field(default="", description="SVG rendered by frontend.")
    original_prompt: str = Field(default="", description="Original user prompt.")
    id: str = Field(default="")
    version: int = Field(default=1, ge=1)
    title: str = "Untitled Diagram"
    created_at: str | None = None

    @model_validator(mode="after")
    def set_defaults(self) -> "Diagram":
        if not self.id:
            self.id = f"diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.title and self.original_prompt:
            self.title = self.original_prompt[:50] + ("..." if len(self.original_prompt) > 50 else "")
        return self

    def to_markdown(self) -> str:
        lang = "mermaid" if self.format == "mermaid" else "plantuml" if self.format == "plantuml" else "dot"
        return f"```{lang}\n{self.source}\n```"

    def is_renderable(self) -> bool:
        return bool(self.source and len(self.source.strip()) > 3)

    def to_excalidraw(self) -> dict[str, Any]:
        """Export to Excalidraw JSON format with hand-drawn styling (Virgil font, roughness)."""
        elements: list[dict[str, Any]] = [
            {
                "id": "title",
                "type": "text",
                "x": 50,
                "y": 30,
                "text": f"{self.diagram_type.title()} Diagram",
                "fontSize": 28,
                "fontFamily": 1,  # 1 = Virgil (handwritten)
                "roughness": 1,
            },
            {
                "id": "note",
                "type": "text",
                "x": 50,
                "y": 80,
                "text": self.explanation[:120] + ("..." if len(self.explanation) > 120 else ""),
                "fontSize": 16,
                "fontFamily": 1,
            },
        ]
        # Add a simple box for the diagram content
        elements.append({
            "id": "diagram-box",
            "type": "rectangle",
            "x": 100,
            "y": 150,
            "width": 400,
            "height": 250,
            "strokeColor": "#5d4037",
            "backgroundColor": "#fff7ed",
            "roughness": 2,
            "strokeWidth": 3,
            "roundness": {"type": 3},
        })
        elements.append({
            "id": "content",
            "type": "text",
            "x": 130,
            "y": 200,
            "text": self.source[:280] + ("..." if len(self.source) > 280 else ""),
            "fontSize": 14,
            "fontFamily": 2,  # monospace for code
            "width": 340,
        })
        return {
            "type": "excalidraw",
            "version": 2,
            "source": "diatype",
            "elements": elements,
            "appState": {
                "theme": "light",
                "viewBackgroundColor": "#f9f4e9",
                "gridMode": 0,
                "zenModeEnabled": False,
            },
            "files": {},
        }

    model_config = ConfigDict(
        extra="ignore",
        validate_assignment=True,
    )
