<!-- header:start -->
<div align="center">

<img src="./assets/banner.svg" alt="DiaType" width="100%">

<a href="#-quick-start"><img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=20&pause=1000&color=f9f4e9&center=true&vCenter=true&width=640&lines=Describe+in+plain+English;Get+instant+visuals;Private%2C+local%2C+editable" alt="Describe in plain English · Get instant visuals · Private, local, editable"></a>

<a href="LICENSE"><img src="https://img.shields.io/github/license/ajendras/diatype?style=for-the-badge&color=5d4037" alt="License"></a>
<img src="https://img.shields.io/badge/Python-5d4037?style=for-the-badge&logo=python&logoColor=white" alt="Python">
<a href="https://github.com/ajendras/diatype/stargazers"><img src="https://img.shields.io/github/stars/ajendras/diatype?style=for-the-badge&logo=github&color=f9f4e9" alt="Stars"></a>
<a href="https://github.com/ajendras/diatype/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/ajendras/diatype/ci.yml?style=for-the-badge&label=CI" alt="CI"></a>
<img src="https://img.shields.io/github/last-commit/ajendras/diatype?style=for-the-badge&color=5d4037" alt="Last commit">
<a href="CONTRIBUTING.md"><img src="https://img.shields.io/badge/PRs-welcome-22c55e?style=for-the-badge" alt="PRs welcome"></a>

**Converts natural language into editable Mermaid diagrams with local LLMs inside a hand-drawn notebook interface**

[✨ Features](#-features) • [⚡ Quick start](#-quick-start) • [🧰 Usage](#-usage) • [🧩 Architecture](#-architecture) • [📍 Roadmap](#-roadmap) • [🤝 Contributing](#-contributing)

</div>
<!-- header:end -->

## ✨ Why DiaType?

Creating and updating technical diagrams is tedious and error-prone. Existing tools force you to learn complex syntax or send sensitive data to the cloud. DiaType lets developers, architects, and technical writers describe what they need in plain English, instantly receive valid Mermaid diagrams, and keep everything local, private, and version-controlled inside a delightful hand-drawn notebook interface.

- **Natural language to diagrams** — describe any process or structure and get clean, valid Mermaid instantly via local Ollama
- **Iterative refinement** — tell the model to "add error handling" or "make the layout left-to-right" without rewriting prompts
- **Hand-drawn notebook UI** — lined paper, Caveat handwriting font, wobbly borders and highlighter accents create a familiar sketchbook feel
- **Zero cloud, fully editable** — live Mermaid preview, one-click SVG/PNG/PDF export, and CLI companion for scripts and CI

## 🎬 Demo

<p align="center"><img src="./assets/demo.svg" alt="DiaType demo" width="760"></p>

## 🚀 Features

<table>
<tr>
<td align="center" valign="top" width="33%">
🤖<br>
<b>Natural Generation</b><br>
Describe any diagram in plain English; receive valid Mermaid via Ollama
</td>
<td align="center" valign="top" width="33%">
📓<br>
<b>Notebook UI</b><br>
Handwriting-font headings, lined paper, wobbly borders and sticky notes
</td>
<td align="center" valign="top" width="33%">
🔄<br>
<b>AI Refinement</b><br>
Iterate with natural-language instructions; original structure is preserved
</td>
</tr>
<tr>
<td align="center" valign="top">
👀<br>
<b>Live Preview</b><br>
Real-time Mermaid renderer updates as you edit the generated code
</td>
<td align="center" valign="top">
📤<br>
<b>One-click Export</b><br>
Export as SVG, PNG, PDF or copy Markdown embed code
</td>
<td align="center" valign="top">
🧩<br>
<b>Template Gallery</b><br>
Start from common patterns (architecture, user flows, sequence diagrams)
</td>
</tr>
<tr>
<td align="center" valign="top">
📝<br>
<b>Explanation Mode</b><br>
Ask the LLM to describe a diagram or suggest improvements in plain English
</td>
<td align="center" valign="top">
⌨️<br>
<b>CLI Companion</b><br>
Generate diagrams directly from terminal with <code>diatype generate</code>
</td>
<td></td>
</tr>
</table>

## 📦 Installation

**Requirements**: Python 3.10+, a running Ollama instance with a model such as `llama3.2`.

```bash
pip install diatype
diatype serve          # starts the notebook UI at http://127.0.0.1:8000
```

For development or to run tests:

```bash
pip install -e ".[dev]"
pytest
```

The CLI entry point `diatype` is automatically installed from `pyproject.toml`.

## ⚡ Quick start

```python
from diatype.config import Settings
from diatype.generator import DiagramEngine

engine = DiagramEngine(Settings.load())
diagram = engine.generate(
    "User logs in via OAuth, then the API gateway routes to an order service backed by PostgreSQL",
    diagram_type="flowchart"
)

print(diagram.to_markdown())
print("\nExplanation:", diagram.explanation)
```

The returned `Diagram` object is guaranteed to contain validated Mermaid syntax.

## 🧰 Usage

**CLI one-liner** (creates both `.mmd` and `.md` files):

```bash
diatype generate "microservice architecture with API gateway, auth and payment services" \
  --type flowchart --output diagrams/architecture --explain
```

**Refining an existing diagram** (Python):

```python
from diatype.models import Diagram

original = engine.generate("simple login flow")
refined = engine.refine(
    original,
    "add error handling step and a retry loop"
)
print(refined.to_markdown())
```

**Explanation mode** (useful for documentation):

```python
explanation = engine.explain(refined)
print(explanation)
```

**Launching the web notebook** with custom host/port:

```bash
diatype serve --host 0.0.0.0 --port 8080 --reload
```

<details><summary>Advanced: using the FastAPI endpoints directly</summary>

```bash
curl -X POST http://127.0.0.1:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "sequence of a CI pipeline", "diagram_type": "sequenceDiagram"}'
```

The `/api/refine` and `/api/explain` endpoints accept a `Diagram` payload plus an `instruction` key and return updated `Diagram` objects (or plain text for explanations). All routes are defined in `src/diatype/app.py`.
</details>

## 🔧 Configuration

DiaType loads settings from `config.toml` (or falls back to defaults). The `Settings` class in `src/diatype/config.py` exposes:

| Option                | Default          | Description |
|-----------------------|------------------|-------------|
| `ollama_model`        | `llama3.2`       | Ollama model tag. Smaller instruction-tuned models work best. |
| `temperature`         | `0.2`            | Lower values yield more deterministic diagram syntax (0.0-0.7). |
| `default_diagram_type`| `flowchart`      | One of the supported Mermaid kinds (validated by regex). |
| `max_tokens`          | `2500`           | Maximum tokens requested from the model. |
| `output_dir`          | `diagrams`       | Directory for exported files (created automatically). |

See `config.example.toml` for a ready-to-copy sample.

## 🧩 Architecture

```mermaid
flowchart TD
    User[User / CLI] -->|prompt| CLI["cli.py (diatype generate/serve)"]
    User -->|browser| UI["templates/index.html + HTMX"]
    CLI --> Engine["DiagramEngine (generator.py)"]
    UI --> FastAPI["FastAPI (/api/generate, /api/refine, /api/explain)"]
    FastAPI --> Engine
    Engine -->|system + user prompt| Ollama["Ollama (local LLM)"]
    Ollama -->|JSON response| Validator["validator.py (sanitize, validate_mermaid, detect_diagram_type)"]
    Validator --> Diagram["Diagram model (models.py)"]
    Diagram -->|mermaid| Renderer["Mermaid.js (live preview)"]
    Diagram -->|SVG/Markdown| Export["Export (SVG/PNG/PDF)"]
    Config["config.py (Settings)"] --> Engine
```

`DiagramEngine` orchestrates prompt construction, LLM calls, parsing, validation and refinement. The FastAPI layer and CLI stay thin, delegating all intelligence to the engine. All generated diagrams are sanitised and validated before leaving the backend.

## 📁 Project structure

```text
.
├── pyproject.toml                 # metadata, dependencies, CLI entry point
├── config.example.toml            # sample settings (ollama_model, temperature, etc.)
├── src/diatype/
│   ├── __init__.py                # public API: Diagram, DiagramEngine, DiagramRequest
│   ├── config.py                  # Settings Pydantic model with TOML loader
│   ├── models.py                  # Diagram & DiagramRequest with validators
│   ├── generator.py               # DiagramEngine (generate, refine, explain)
│   ├── validator.py               # validate_mermaid, sanitize, detect_diagram_type
│   ├── app.py                     # FastAPI routes + Jinja2 notebook UI
│   └── cli.py                     # Typer commands: generate, serve, version
├── templates/index.html           # hand-drawn notebook UI (Caveat font, lined paper)
├── static/
│   ├── css/styles.css             # wobbly borders, highlighter accents, sticky notes
│   └── js/main.js                 # HTMX interactions, mermaid rendering, exports
├── tests/test_generator.py        # pytest + mocked Ollama, snapshot tests
├── examples/demo.py               # runnable Python example (architecture diagram)
└── LICENSE
```

## 🧪 Testing

```bash
pytest
```

The test suite (`tests/test_generator.py`) covers `DiagramEngine.generate`, `refine`, `explain`, prompt validation, fallback JSON/markdown parsing, validator integration, error handling, and snapshot-style checks for common diagram outputs. Ollama calls are fully mocked.

## 📍 Roadmap
<!-- roadmap:start -->
- [x] **v0.1.0** — first release: Natural Generation, Notebook UI, AI Refinement, Live Preview
- [ ] Add Excalidraw JSON export with sketchy hand-drawn look
- [ ] Implement diagram history with simple file-based versioning
- [ ] Support PlantUML and Graphviz via additional LLM prompts
- [ ] Add voice input using whisper for diagram descriptions
- [ ] Create Obsidian plugin to insert generated diagrams
- [ ] Improve few-shot prompting for higher first-try accuracy
- [ ] Add bulk generation from a folder of markdown requirement files
- [ ] Support custom user-defined diagram templates
- [ ] Export directly to draw.io XML format
- [ ] Add WebSocket live collaboration for shared notebooks
- [ ] Provide browser extension to capture DOM structure and suggest matching diagrams
- [ ] Create sepia dark notebook theme variant

> 🤖 This roadmap is worked through continuously — ideas and PRs welcome!
<!-- roadmap:end -->

## 🤝 Contributing

We welcome contributions! Whether it's a new diagram template, improved prompts, UI polish, or better validation heuristics, every PR helps.

Please read [CONTRIBUTING.md](https://github.com/ajendras/diatype/blob/main/CONTRIBUTING.md) and follow our [CODE_OF_CONDUCT.md](https://github.com/ajendras/diatype/blob/main/CODE_OF_CONDUCT.md). Good-first-issues are tagged and make excellent starting points.

## 📄 License

DiaType is licensed under the **MIT License**. See [LICENSE](LICENSE) for the full text.

<!-- footer:start -->
<div align="center">

### ⭐ Star history

<a href="https://star-history.com/#ajendras/diatype&Date"><img src="https://api.star-history.com/svg?repos=ajendras/diatype&type=Date" alt="Star history" width="600"></a>

If **DiaType** saves you time, a ⭐ helps others find it.

Made with ❤️ by [Ajendra](https://ajendra.info)

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:5d4037,100:f9f4e9&height=120&section=footer" width="100%" alt="">

</div>
<!-- footer:end -->
