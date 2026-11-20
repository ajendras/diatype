"""FastAPI application for the DiaType notebook interface.

Serves the hand-drawn UI, provides JSON endpoints for generation and refinement,
and mounts static assets (CSS, JS, fonts).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from .config import Settings
from .generator import DiagramEngine
from .models import Diagram, DiagramRequest

app = FastAPI(
    title="DiaType",
    version="0.3.0",
    description="Hand-drawn notebook for turning natural language into Mermaid diagrams — 100% local.",
)

# Mount static files (CSS, JS, fonts)
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory="templates")


def get_engine() -> DiagramEngine:
    """Return a singleton DiagramEngine (lazy initialisation)."""
    if not hasattr(get_engine, "_engine"):
        get_engine._engine = DiagramEngine(Settings.load())  # type: ignore[attr-defined]
    return get_engine._engine  # type: ignore[attr-defined]


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request) -> HTMLResponse:
    """Render the hand-drawn notebook interface."""
    settings = Settings.load()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "ollama_model": settings.ollama_model,
            "default_diagram_type": settings.default_diagram_type,
            "whisper_model": settings.whisper_model,
        },
    )


@app.post("/api/generate", response_model=Diagram)
async def api_generate(
    req: DiagramRequest, engine: DiagramEngine = Depends(get_engine)
) -> Diagram:
    """Generate a new diagram from a natural language prompt.

    All output is sanitised and validated before being returned.
    A versioned copy is saved to the history directory.
    """
    try:
        diagram = engine.generate(req.prompt, req.diagram_type)
        return diagram
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/refine", response_model=Diagram)
async def api_refine(
    request: Request, engine: DiagramEngine = Depends(get_engine)
) -> Diagram:
    """Refine an existing diagram based on a natural-language instruction.

    Accepts a JSON payload containing a full Diagram plus an 'instruction' key.
    The refined version is saved with an incremented version number.
    """
    try:
        payload = await request.json()
        instruction: str = payload.pop("instruction", "").strip()

        if len(instruction) < 3:
            raise ValueError("instruction must be at least 3 characters")

        diagram = Diagram(
            source=payload.get("source") or payload.get("mermaid", ""),
            explanation=payload.get("explanation") or "The diagram has been refined according to your instructions.",
            svg=payload.get("svg", ""),
            diagram_type=payload.get("diagram_type", "flowchart"),
            format=payload.get("format", "mermaid"),
        )

        refined = engine.refine(diagram, instruction)
        return refined
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Refinement failed: {exc}") from exc


@app.post("/api/explain")
async def api_explain(
    request: Request, engine: DiagramEngine = Depends(get_engine)
) -> dict[str, str]:
    """Return a plain-English explanation of the supplied diagram."""
    try:
        payload = await request.json()
        diagram = Diagram(
            source=payload.get("source") or payload.get("mermaid", ""),
            explanation=payload.get("explanation") or "Explanation of the provided diagram.",
            diagram_type=payload.get("diagram_type", "flowchart"),
            format=payload.get("format", "mermaid"),
            svg=payload.get("svg", ""),
        )
        explanation = engine.explain(diagram)
        return {"explanation": explanation}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/transcribe")
async def api_transcribe(
    file: UploadFile = File(...), engine: DiagramEngine = Depends(get_engine)
) -> dict[str, str]:
    """Transcribe uploaded audio to text using faster-whisper.

    Accepts webm, mp3, wav etc. Returns the recognised text to be used as prompt.
    """
    if not file.content_type or not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="Audio file required")

    try:
        audio_bytes = await file.read()
        if len(audio_bytes) < 512:
            raise ValueError("Audio file too small")
        text = engine.transcribe(audio_bytes)
        return {"text": text}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Transcription failed: {exc}"
        ) from exc


@app.post("/api/excalidraw")
async def api_excalidraw(request: Request) -> dict[str, Any]:
    """Return Excalidraw v2 JSON with sketchy hand-drawn styling.

    Accepts a Diagram payload and returns a scene that can be imported
    directly into Excalidraw (Virgil font, roughness=2, slight angles).
    """
    try:
        payload = await request.json()
        diagram = Diagram(
            source=payload.get("source") or payload.get("mermaid", ""),
            explanation=payload.get("explanation") or "Diagram exported for use in Excalidraw with hand-drawn styling.",
            diagram_type=payload.get("diagram_type", "flowchart"),
            format=payload.get("format", "mermaid"),
            svg=payload.get("svg", ""),
        )
        return diagram.to_excalidraw()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Excalidraw export failed: {exc}") from exc


@app.get("/api/history")
async def api_history(
    engine: DiagramEngine = Depends(get_engine),
) -> list[dict[str, Any]]:
    """Return list of history entries (newest first)."""
    return engine.list_history(limit=30)


@app.post("/api/load_version", response_model=Diagram)
async def api_load_version(
    request: Request, engine: DiagramEngine = Depends(get_engine)
) -> Diagram:
    """Load a specific version from the file-based history by ID and version number."""
    try:
        payload = await request.json()
        diagram_id: str = str(payload.get("id", "")).strip()
        version: int = int(payload.get("version", 1))

        if not diagram_id:
            raise ValueError("id is required")

        diagram = engine.load_version(diagram_id, version)
        if diagram is None:
            raise HTTPException(status_code=404, detail="History entry not found")

        return diagram
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load version: {exc}"
        ) from exc


@app.get("/health")
async def health() -> dict[str, str]:
    """Simple health check exposing the configured model."""
    settings = Settings.load()
    return {"status": "healthy", "model": settings.ollama_model, "whisper": settings.whisper_model}
