"""Diagram generation and refinement engine for DiaType.

Uses local Ollama models to turn natural language into valid Mermaid
diagrams. All output is validated, sanitized, and wrapped in a typed
Diagram model. The engine is designed to be testable (via dependency
injection of settings) and resilient to imperfect LLM responses.

The engine also maintains simple file-based versioning: every generated
or refined diagram is saved as a timestamped JSON file in the configured
history directory. Refinements increment the version number for the same
diagram ID.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import ollama
from pydantic import ValidationError

from .config import Settings
from .models import Diagram, DiagramRequest
from .validator import detect_diagram_type, sanitize, validate_mermaid


class DiagramEngine:
    """Orchestrates prompt construction, LLM calls, parsing, validation and refinement.

    All heavy lifting (prompt engineering, retry logic, sanitization) lives here
    so the FastAPI layer and CLI stay thin and focused on transport.
    History persistence is also handled here using simple JSON files.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.load()
        self._system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """High-precision system prompt that steers the model toward
        structured JSON output containing valid Mermaid.
        """
        return (
            "You are an expert Mermaid.js diagramming assistant. "
            "Your responses must be valid JSON with exactly two fields: "
            "'mermaid' (the complete diagram source) and 'explanation' "
            "(a concise plain-English description, 2-4 sentences).\n\n"
            "Rules:\n"
            "1. The mermaid field MUST start with a valid diagram type "
            "(flowchart, sequenceDiagram, classDiagram, etc.).\n"
            "2. Use clear, descriptive node labels. Prefer --> for relationships.\n"
            "3. Never add extra commentary outside the JSON object.\n"
            "4. Keep the diagram layout logical (TD/LR as appropriate).\n"
            "5. For refinements, preserve as much of the original structure as possible.\n\n"
            "Example response:\n"
            '{"mermaid": "flowchart TD\\n    A[User] --> B[Login]\\n    B --> C[Database]", '
            '"explanation": "This flowchart shows a simple user login flow with a database."}'
        )

    def generate(self, prompt: str, diagram_type: str = "flowchart") -> Diagram:
        """Generate a fresh diagram from a natural-language description.

        The returned Diagram is guaranteed to have passed basic validation.
        A copy is automatically saved to the history directory.
        """
        if not isinstance(prompt, str) or len(prompt.strip()) < 8:
            raise ValueError("prompt must be a string at least 8 characters long")

        request = DiagramRequest(prompt=prompt, diagram_type=diagram_type)

        user_content = (
            f"Diagram type: {request.diagram_type}\n\n"
            f"Description: {request.prompt}\n\n"
            "Produce the diagram now."
        )

        try:
            response = ollama.chat(
                model=self.settings.ollama_model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": user_content},
                ],
                options=self.settings.get_ollama_options(),
                format="json",
            )
            content = response["message"]["content"].strip()
            diagram = self._parse_llm_response(
                content,
                requested_type=request.diagram_type,
                original_prompt=prompt,
            )
            self.save_to_history(diagram)
            return diagram

        except ollama.ResponseError as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
        except (json.JSONDecodeError, KeyError, ValidationError) as exc:
            raise RuntimeError(
                "Could not parse a valid diagram from the model. "
                "The model may be overloaded or the prompt too ambiguous."
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"Unexpected error during generation: {exc}") from exc

    def refine(self, diagram: Diagram, instruction: str) -> Diagram:
        """Iteratively improve an existing diagram according to a natural-language instruction.

        The refined diagram shares the same ID but receives an incremented version number
        and is saved to history.
        """
        if not isinstance(diagram, Diagram):
            raise TypeError("diagram must be an instance of Diagram")
        if not isinstance(instruction, str) or len(instruction.strip()) < 3:
            raise ValueError("instruction must be at least 3 characters")

        user_content = (
            f"Current diagram (type: {diagram.diagram_type}):\n\n"
            f"{diagram.mermaid}\n\n"
            f"Instruction: {instruction}\n\n"
            "Return an updated version using the same JSON format."
        )

        try:
            response = ollama.chat(
                model=self.settings.ollama_model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": user_content},
                ],
                options=self.settings.get_ollama_options(),
                format="json",
            )
            content = response["message"]["content"].strip()
            updated = self._parse_llm_response(
                content,
                requested_type=diagram.diagram_type,
                original_prompt=instruction,
                base_id=diagram.id,
                version=diagram.version + 1,
            )

            # Preserve any already-rendered SVG from the original
            if diagram.svg and not updated.svg:
                updated.svg = diagram.svg
            if not updated.original_prompt:
                updated.original_prompt = diagram.original_prompt

            self.save_to_history(updated)
            return updated

        except Exception as exc:
            raise RuntimeError(f"Refinement failed: {exc}") from exc

    def explain(self, diagram: Diagram) -> str:
        """Ask the LLM to describe a diagram back in plain English.

        Useful for the 'Explanation Mode' feature.
        """
        if not isinstance(diagram, Diagram):
            raise TypeError("diagram must be an instance of Diagram")
        if not diagram.is_renderable():
            raise ValueError("Cannot explain a diagram with empty mermaid source")

        prompt = (
            f"Explain the following {diagram.diagram_type} diagram in clear, "
            f"non-technical English. Focus on what the diagram shows, the "
            f"relationships, and the overall meaning.\n\n"
            f"{diagram.mermaid}\n\n"
            "Be concise (3-5 sentences)."
        )

        try:
            response = ollama.chat(
                model=self.settings.ollama_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a helpful technical communicator. "
                            "Explain diagrams using everyday language."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": 0.4},
            )
            return response["message"]["content"].strip()
        except Exception:  # pylint: disable=broad-except
            # Graceful fallback so the UI never completely breaks
            return (
                f"I could not generate an explanation at this time.\n\n"
                f"{diagram.explanation}\n\n"
                f"Diagram source:\n{diagram.to_markdown()}"
            )

    def _parse_llm_response(
        self,
        content: str,
        requested_type: str,
        original_prompt: str = "",
        base_id: str | None = None,
        version: int = 1,
    ) -> Diagram:
        """Convert raw LLM text (JSON or markdown) into a validated Diagram object.

        Centralizes all parsing, sanitization, validation and Pydantic construction.
        History fields are populated here so that each version is correctly tracked.
        """
        # Try strict JSON first (encouraged by the format="json" parameter)
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                raw_mermaid = parsed.get("mermaid", "")
                explanation = parsed.get("explanation", "")
            else:
                raw_mermaid = content
                explanation = "No explanation provided by model."
        except json.JSONDecodeError:
            # Fallback: extract with regex (handles markdown-wrapped answers)
            mermaid_match = re.search(
                r'"?mermaid"?\s*[:=]\s*["\'](.*?)["\'](?:,|\s*\})',
                content,
                re.DOTALL,
            )
            expl_match = re.search(
                r'"?explanation"?\s*[:=]\s*["\'](.*?)["\'](?:,|\s*\})',
                content,
                re.DOTALL,
            )
            raw_mermaid = mermaid_match.group(1) if mermaid_match else content
            explanation = expl_match.group(1) if expl_match else "Diagram generated from your description."

        clean_mermaid = sanitize(raw_mermaid)

        if not validate_mermaid(clean_mermaid):
            raise ValueError(
                "The generated diagram failed basic validation. "
                "Please rephrase your request with more detail."
            )

        detected_type = detect_diagram_type(clean_mermaid) or requested_type

        return Diagram(
            mermaid=clean_mermaid,
            explanation=explanation.strip() or "No explanation available.",
            diagram_type=detected_type,
            svg="",  # populated by frontend Mermaid renderer
            original_prompt=original_prompt,
            id=base_id or f"diag_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            version=version,
        )

    def save_to_history(self, diagram: Diagram) -> None:
        """Persist a diagram version to the history directory as JSON.

        Uses the diagram's ID and version to produce a deterministic filename.
        Old entries are pruned according to the configured limit.
        """
        if not self.settings.history_enabled:
            return

        history_dir: Path = self.settings.history_dir
        try:
            history_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{diagram.id}_v{diagram.version:02d}.json"
            filepath = history_dir / filename

            data = diagram.model_dump(mode="json")
            data["saved_at"] = datetime.now().isoformat()

            filepath.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            self._prune_old_history()
        except Exception as exc:  # broad to avoid breaking generation on IO errors
            print(f"Warning: Could not save diagram to history: {exc}")

    def _prune_old_history(self) -> None:
        """Remove oldest history files when the configured limit is exceeded."""
        if not self.settings.history_enabled or self.settings.max_history < 1:
            return

        history_dir: Path = self.settings.history_dir
        try:
            files = list(history_dir.glob("*.json"))
            if len(files) <= self.settings.max_history:
                return
            files.sort(key=lambda f: f.stat().st_mtime)
            for old_file in files[: len(files) - self.settings.max_history]:
                old_file.unlink(missing_ok=True)
        except Exception:
            pass  # never let cleanup break the application

    def list_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return a list of history entries (newest first) for UI/CLI display.

        Only metadata is returned; full diagrams are loaded on demand via load_version.
        """
        if not self.settings.history_enabled:
            return []

        history_dir: Path = self.settings.history_dir
        if not history_dir.exists():
            return []

        entries: list[dict[str, Any]] = []
        try:
            files = list(history_dir.glob("*_v*.json"))
            files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            for file_path in files[:limit]:
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    entries.append(
                        {
                            "id": data.get("id", ""),
                            "version": data.get("version", 1),
                            "title": data.get("title", "Untitled Diagram"),
                            "diagram_type": data.get("diagram_type", "flowchart"),
                            "created_at": data.get("created_at") or data.get("saved_at", ""),
                            "prompt": data.get("original_prompt", "")[:80],
                            "filename": file_path.name,
                        }
                    )
                except (json.JSONDecodeError, OSError, KeyError):
                    continue
            return entries
        except Exception:
            return []

    def load_version(self, diagram_id: str, version: int = 1) -> Diagram | None:
        """Load a specific version of a diagram from the history directory.

        Returns None if the requested file cannot be found or parsed.
        """
        if not self.settings.history_enabled:
            return None

        history_dir: Path = self.settings.history_dir
        if not history_dir.exists():
            return None

        # Prefer exact version match
        exact_path = history_dir / f"{diagram_id}_v{version:02d}.json"
        candidates = [exact_path] if exact_path.exists() else []
        if not candidates:
            candidates = list(history_dir.glob(f"{diagram_id}_v*.json"))

        for candidate in candidates:
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                return Diagram.model_validate(data)
            except Exception:
                continue

        return None
