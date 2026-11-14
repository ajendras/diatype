"""Configuration management for DiaType.

Loads settings from an optional config.toml with sensible defaults
optimized for fast, consistent local diagram generation with Ollama.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Settings(BaseModel):
    """Application settings with TOML loading and diagram-friendly defaults.

    Defaults are chosen for reliability (low temperature) and compatibility
    with common Ollama models that understand Mermaid syntax well.
    """

    ollama_model: str = Field(
        default="llama3.2",
        description="Ollama model tag. Smaller, instruction-tuned models work best.",
        examples=["llama3.2", "mistral", "phi3"],
    )

    temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=0.7,
        description="Lower temperature yields more deterministic diagram syntax.",
    )

    default_diagram_type: str = Field(
        default="flowchart",
        pattern=r"^(flowchart|sequenceDiagram|classDiagram|stateDiagram|erDiagram|journey|gantt|pie|quadrantChart|requirementDiagram|mindmap|timeline|gitGraph|c4Diagram)$",
        description="Default Mermaid diagram kind when not specified.",
    )

    max_tokens: int = Field(
        default=2500,
        gt=100,
        le=8192,
        description="Maximum tokens to request from the model.",
    )

    output_dir: Path = Field(
        default=Path("diagrams"),
        description="Directory for exported diagrams (created automatically).",
    )

    model_config = ConfigDict(
        extra="ignore",
        validate_assignment=True,
    )

    @classmethod
    def load(cls, config_path: str | Path = "config.toml") -> "Settings":
        """Load settings from TOML file or return defaults on any error.

        Supports both a flat TOML file and a [diatype] or [settings] table.
        """
        path = Path(config_path)
        data: dict[str, Any] = {}

        if path.exists():
            try:
                with open(path, "rb") as f:
                    toml_data = tomllib.load(f)

                # Support common TOML layouts
                for key in ("diatype", "settings", "tool.diatype"):
                    if "." in key:
                        section = toml_data
                        for part in key.split("."):
                            section = section.get(part, {})
                        if isinstance(section, dict):
                            data = section
                            break
                    elif key in toml_data and isinstance(toml_data[key], dict):
                        data = toml_data[key]
                        break
                else:
                    # flat file
                    data = toml_data
            except Exception as exc:  # pylint: disable=broad-except
                # Graceful degradation - log in production
                print(f"Warning: Failed to load {path}: {exc}. Using defaults.")

        settings = cls(**data)

        # Ensure output directory exists
        try:
            settings.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"Warning: Could not create output directory {settings.output_dir}: {exc}")

        return settings

    def get_ollama_options(self) -> dict[str, Any]:
        """Return options dictionary suitable for ollama.chat/generate calls."""
        return {
            "temperature": self.temperature,
            "num_predict": self.max_tokens,
            "top_p": 0.9,
        }

    def __repr__(self) -> str:
        return (
            f"Settings(model={self.ollama_model}, "
            f"temp={self.temperature}, "
            f"default_type={self.default_diagram_type})"
        )
