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
    with common Ollama models that understand Mermaid/PlantUML/Graphviz syntax well.
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
        pattern=r"^(flowchart|sequenceDiagram|classDiagram|stateDiagram|erDiagram|journey|gantt|pie|quadrantChart|requirementDiagram|mindmap|timeline|gitGraph|c4Diagram|sequence|class|activity|state|component|object|deployment)$",
        description="Default diagram kind hint (used for all formats).",
    )

    default_format: str = Field(
        default="mermaid",
        pattern=r"^(mermaid|plantuml|graphviz)$",
        description="Default output format. Additional LLM prompts are used for PlantUML and Graphviz.",
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

    history_enabled: bool = Field(
        default=True,
        description="Whether to automatically save generated diagrams to versioned history.",
    )

    max_history: int = Field(
        default=30,
        gt=0,
        le=1000,
        description="Maximum number of history files to retain (oldest are pruned).",
    )

    history_dir: Path = Field(
        default=Path("diagrams/history"),
        description="Directory for JSON version history files.",
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

        # Ensure history directory exists when enabled
        if settings.history_enabled:
            try:
                settings.history_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                print(f"Warning: Could not create history directory {settings.history_dir}: {exc}")

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
            f"default_type={self.default_diagram_type}, "
            f"default_format={self.default_format}, "
            f"history={self.history_enabled})"
        )
