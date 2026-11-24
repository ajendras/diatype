"""Diagram generation and refinement engine for DiaType.

Uses local Ollama models to turn natural language into valid Mermaid,
PlantUML or Graphviz diagrams. All output is validated, sanitized, and wrapped in a typed
Diagram model. The engine is designed to be testable (via dependency
injection of settings) and resilient to imperfect LLM responses.

The engine also maintains simple file-based versioning: every generated
or refined diagram is saved as a timestamped JSON file in the configured
history directory. Refinements increment the version number for the same
diagram ID. Voice transcription is provided via faster-whisper.
Custom user-defined templates are supported via the template_dir.
Diagram model provides to_drawio() for direct export to diagrams.net XML format.
"""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import ollama
from faster_whisper import WhisperModel
from pydantic import ValidationError

from .config import Settings
from .models import Diagram, DiagramRequest
from .validator import detect_diagram_type, sanitize, validate_source


class DiagramEngine:
    """Orchestrates prompt construction, LLM calls, parsing, validation and refinement.

    All heavy lifting (prompt engineering per format, retry logic, sanitization) lives here
    so the FastAPI layer and CLI stay thin and focused on transport.
    History persistence is also handled here using simple JSON files.
    Voice transcription uses faster-whisper (loaded once on first use).
    The new bulk_generate processes every markdown file in a folder.
    Custom templates are loaded from diagram_templates/ (JSON definitions or plain source files).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.load()
        self._whisper_model: WhisperModel | None = None

    def _get_whisper(self) -> WhisperModel:
        if self._whisper_model is None:
            self._whisper_model = WhisperModel(
                self.settings.whisper_model, device="cpu", compute_type="int8"
            )
        return self._whisper_model

    def _build_system_prompt(
        self, output_format: str = "mermaid", diagram_type: str = "flowchart", template_data: dict | None = None
    ) -> str:
        base = f"""You are an expert software architect that produces valid, clean {output_format} diagrams.
Output ONLY a single JSON object with exactly two keys: "source" and "explanation".
- "source" must be valid {output_format} syntax for a {diagram_type} diagram.
- Do not include any markdown fences or extra text outside the JSON.
- Keep the explanation under 80 words and focus on the business meaning.

"""
        if output_format == "plantuml":
            base += "PlantUML diagrams must begin with @startuml and end with @enduml.\n"
        elif output_format == "graphviz":
            base += "Graphviz diagrams must be valid DOT syntax (digraph or graph).\n"

        if template_data:
            base += (
                "The user will supply a base template. Adapt and extend that template "
                "to fulfil the request while preserving its overall layout, direction "
                "and visual style as much as possible.\n"
            )

        base += """Few-shot examples:
{"source": "flowchart TD\\n    A[Start] --> B[Process]\\n    B --> C[End]", "explanation": "A simple linear process."}
{"source": "sequenceDiagram\\n    participant User\\n    User->>API: Login\\n    API-->>User: Success", "explanation": "OAuth login sequence between user and API."}

Now answer the request below."""
        return base

    def _parse_llm_response(
        self, content: str, output_format: str, requested_type: str | None = None
    ) -> dict[str, str]:
        """Extract JSON from LLM output; fall back to code-block or raw text.

        requested_type is accepted for compatibility with existing tests.
        """
        json_match = re.search(r"(\{.*\})", content, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                if isinstance(parsed, dict) and "source" in parsed:
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass

        code_match = re.search(
            r"```(?:mermaid|plantuml|dot)?\s*([\s\S]+?)\s*```", content
        )
        if code_match:
            source = code_match.group(1).strip()
            return {
                "source": source,
                "explanation": "Diagram generated and validated by DiaType.",
            }

        return {
            "source": content.strip(),
            "explanation": "Diagram generated from the supplied prompt.",
        }

    def _generate_id(self) -> str:
        return f"diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def _generate_title(self, prompt: str) -> str:
        words = prompt.split()[:5]
        return " ".join(words).title()

    def _save_to_history(self, diagram: Diagram) -> None:
        if not self.settings.history_enabled:
            return
        history_dir = self.settings.history_dir
        base_id = diagram.id.split("_v")[0] if "_v" in diagram.id else diagram.id
        file_path = history_dir / f"{base_id}_v{diagram.version:02d}.json"
        data = diagram.model_dump(mode="json")
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self._prune_history()

    def save_to_history(self, diagram: Diagram) -> None:
        """Public wrapper (used by tests)."""
        self._save_to_history(diagram)

    def _prune_history(self) -> None:
        if not self.settings.history_enabled or not self.settings.history_dir.exists():
            return
        files = sorted(
            self.settings.history_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
        )
        if len(files) > self.settings.max_history:
            for old_file in files[: len(files) - self.settings.max_history]:
                old_file.unlink(missing_ok=True)

    def _load_template(self, name: str) -> dict[str, Any]:
        """Load template by name from template_dir (JSON or plain source file)."""
        tdir = self.settings.template_dir
        json_path = tdir / f"{name}.json"
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                data.setdefault("name", name)
                return data
            except Exception as exc:
                raise ValueError(f"Invalid JSON template '{name}': {exc}") from exc

        for ext, fmt in [(".mmd", "mermaid"), (".puml", "plantuml"), (".dot", "graphviz")]:
            src_path = tdir / f"{name}{ext}"
            if src_path.exists():
                source = src_path.read_text(encoding="utf-8").strip()
                return {
                    "name": name,
                    "description": f"Custom {fmt} template",
                    "diagram_type": detect_diagram_type(source)
                    or self.settings.default_diagram_type,
                    "format": fmt,
                    "base_source": source,
                }
        raise ValueError(f"Template '{name}' not found in {tdir}")

    def list_templates(self) -> list[dict[str, Any]]:
        """Return metadata for every template found in the template directory."""
        templates: list[dict[str, Any]] = []
        tdir = self.settings.template_dir
        if not tdir.exists():
            return templates

        for json_file in tdir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                templates.append(
                    {
                        "name": data.get("name", json_file.stem),
                        "description": data.get("description", "No description provided"),
                        "diagram_type": data.get(
                            "diagram_type", self.settings.default_diagram_type
                        ),
                        "format": data.get("format", self.settings.default_format),
                    }
                )
            except Exception:
                continue

        for ext, fmt in [(".mmd", "mermaid"), (".puml", "plantuml"), (".dot", "graphviz")]:
            for src_file in tdir.glob(f"*{ext}"):
                name = src_file.stem
                if not any(t.get("name") == name for t in templates):
                    templates.append(
                        {
                            "name": name,
                            "description": f"Plain {fmt} source template",
                            "diagram_type": self.settings.default_diagram_type,
                            "format": fmt,
                        }
                    )
        return sorted(templates, key=lambda t: t["name"])

    def generate(
        self,
        prompt: str,
        diagram_type: str | None = None,
        output_format: str | None = None,
        template: str | None = None,
    ) -> Diagram:
        """Generate a new diagram, optionally starting from a custom template."""
        if not prompt or len(prompt.strip()) < 8:
            raise ValueError("Prompt must be at least 8 characters long.")

        if diagram_type is None:
            diagram_type = self.settings.default_diagram_type
        if output_format is None:
            output_format = self.settings.default_format

        template_data: dict[str, Any] | None = None
        if template:
            template_data = self._load_template(template)
            if template_data.get("diagram_type"):
                diagram_type = template_data["diagram_type"]
            if template_data.get("format"):
                output_format = template_data["format"]

        system_prompt = self._build_system_prompt(
            output_format, diagram_type, template_data
        )
        user_prompt = prompt
        if template_data and template_data.get("base_source"):
            user_prompt = (
                f"Base template:\n\n{template_data['base_source']}\n\n"
                f"Adapt the template above to satisfy this request while preserving "
                f"its style and layout:\n{prompt}"
            )

        try:
            response = ollama.chat(
                model=self.settings.ollama_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                options=self.settings.get_ollama_options(),
            )
            content = response["message"]["content"]
            parsed = self._parse_llm_response(content, output_format)
            source = sanitize(parsed.get("source", ""))
            validate_source(source, output_format)
            explanation = parsed.get(
                "explanation", "Diagram generated by local LLM via DiaType."
            )

            diagram = Diagram(
                id=self._generate_id(),
                title=self._generate_title(prompt),
                source=source,
                explanation=explanation,
                diagram_type=diagram_type,
                format=output_format,
                prompt=prompt,
                version=1,
                created_at=datetime.now().isoformat(),
                template=template,
            )

            if self.settings.history_enabled:
                self._save_to_history(diagram)
            return diagram
        except (ValueError, ValidationError) as exc:
            raise RuntimeError("Could not parse a valid diagram") from exc
        except ollama.ResponseError as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"Generation failed: {exc}") from exc

    def refine(self, diagram: Diagram, instruction: str) -> Diagram:
        """Refine an existing diagram according to a natural-language instruction."""
        if not instruction or len(instruction.strip()) < 3:
            raise ValueError("Instruction must be at least 3 characters.")

        system_prompt = (
            f"You are refining a {diagram.format} diagram.\n"
            "Return ONLY a JSON object with 'source' and 'explanation'.\n"
            "Preserve the original structure and only change what the instruction requires.\n\n"
            'Few-shot examples:\n'
            '{"source": "flowchart TD\\n    A[Start] --> B[Process]\\n    B --> C[End]", "explanation": "Added error handling per instruction while preserving overall structure."}\n\n'
            "Now refine the diagram below."
        )
        user_prompt = (
            f"Current diagram source:\n{diagram.source}\n\n"
            f"Instruction: {instruction}\n\n"
            "Return the full updated diagram."
        )

        try:
            response = ollama.chat(
                model=self.settings.ollama_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                options=self.settings.get_ollama_options(),
            )
            content = response["message"]["content"]
            parsed = self._parse_llm_response(content, diagram.format)
            source = sanitize(parsed.get("source", diagram.source))
            validate_source(source, diagram.format)

            refined = Diagram(
                id=diagram.id,
                title=diagram.title,
                source=source,
                explanation=parsed.get("explanation", f"Refined per: {instruction}"),
                diagram_type=diagram.diagram_type,
                format=diagram.format,
                prompt=diagram.prompt,
                version=diagram.version + 1,
                created_at=datetime.now().isoformat(),
                template=diagram.template,
            )
            if self.settings.history_enabled:
                self._save_to_history(refined)
            return refined
        except Exception as exc:
            raise RuntimeError(f"Refinement failed: {exc}") from exc

    def explain(self, diagram: Diagram) -> str:
        """Ask the LLM for a plain-English explanation of the diagram."""
        prompt = (
            f"Explain the following {diagram.format} diagram in clear, concise English.\n\n"
            f"{diagram.source}\n\nFocus on the key components and relationships."
        )
        try:
            response = ollama.chat(
                model=self.settings.ollama_model,
                messages=[{"role": "user", "content": prompt}],
                options=self.settings.get_ollama_options(),
            )
            return response["message"]["content"].strip()
        except Exception as exc:
            return f"Explanation could not be generated: {exc}"

    def transcribe(self, audio_bytes: bytes) -> str:
        """Transcribe audio bytes to text using faster-whisper (local)."""
        if len(audio_bytes) < 16:
            raise ValueError("Audio data too small to transcribe.")
        whisper = self._get_whisper()
        segments, _ = whisper.transcribe(BytesIO(audio_bytes), beam_size=5, word_timestamps=False)
        text = " ".join(segment.text for segment in segments).strip()
        return text

    def bulk_generate(
        self,
        input_dir: Path,
        output_dir: Path | None = None,
        diagram_type: str = "flowchart",
        output_format: str = "mermaid",
    ) -> list[Diagram]:
        """Process every .md file in input_dir as a separate generation request."""
        if output_dir is None:
            output_dir = self.settings.output_dir / "bulk"
        output_dir.mkdir(parents=True, exist_ok=True)

        diagrams: list[Diagram] = []
        for md_file in sorted(input_dir.glob("*.md")):
            prompt = md_file.read_text(encoding="utf-8").strip()
            if not prompt:
                continue
            diagram = self.generate(
                prompt=prompt,
                diagram_type=diagram_type,
                output_format=output_format,
            )
            diagram.title = md_file.stem.replace("-", " ").replace("_", " ").title()

            ext = ".mmd" if output_format == "mermaid" else ".puml" if output_format == "plantuml" else ".dot"
            (output_dir / f"{md_file.stem}{ext}").write_text(diagram.source, encoding="utf-8")
            (output_dir / f"{md_file.stem}.md").write_text(
                diagram.to_markdown(), encoding="utf-8"
            )
            if self.settings.history_enabled:
                self._save_to_history(diagram)
            diagrams.append(diagram)
        return diagrams

    def list_history(self, limit: int = 30) -> list[dict[str, Any]]:
        """Return up to limit history entries (newest first)."""
        hist_dir = self.settings.history_dir
        if not hist_dir.exists():
            return []
        entries = []
        for json_file in hist_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                entries.append(data)
            except Exception:
                continue
        entries.sort(key=lambda e: e.get("created_at", ""), reverse=True)
        return entries[:limit]

    def load_version(self, diagram_id: str, version: int = 1) -> Diagram | None:
        """Load a specific version from the JSON history."""
        hist_dir = self.settings.history_dir
        for suffix in (f"_v{version:02d}", f"_v{version}", ""):
            path = hist_dir / f"{diagram_id}{suffix}.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return Diagram(**data)
                except Exception:
                    return None
        return None
