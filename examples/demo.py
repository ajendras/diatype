"""Runnable example demonstrating the DiaType Python API.

Generates a system architecture diagram from a natural-language prompt
using a local Ollama model, prints the result, and saves both the
Mermaid source and a Markdown embed. SVG rendering is left to the
web UI or mermaid-cli because the core library focuses on generation.
"""

from pathlib import Path

from diatype.config import Settings
from diatype.generator import DiagramEngine
from diatype.models import Diagram


def main() -> None:
    """Generate an e-commerce system architecture diagram and persist outputs."""
    # Load from the example config (falls back gracefully to defaults if missing)
    settings: Settings = Settings.load("config.example.toml")
    engine = DiagramEngine(settings)

    prompt = (
        "Modern e-commerce platform architecture. Show a React frontend calling "
        "an API Gateway that routes to Product Service, Order Service, and User "
        "Service. Include a PostgreSQL database, Redis cache for sessions, "
        "Kafka for async events between services, and an external Payment Provider. "
        "Use a flowchart with clear groupings and data flow arrows."
    )

    print("🤖 Generating architecture diagram with DiaType...\n")
    diagram: Diagram = engine.generate(prompt, diagram_type="flowchart")

    print("=== Mermaid Diagram ===")
    print(diagram.to_markdown())
    print("\n=== Explanation ===")
    print(diagram.explanation)
    print("\n" + "=" * 60)

    # Persist outputs
    output_dir = settings.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    base_path = output_dir / "ecommerce-architecture"

    mmd_path = base_path.with_suffix(".mmd")
    mmd_path.write_text(diagram.mermaid.strip() + "\n", encoding="utf-8")
    print(f"✅ Mermaid source saved → {mmd_path}")

    md_path = base_path.with_suffix(".md")
    md_path.write_text(diagram.to_markdown(), encoding="utf-8")
    print(f"✅ Markdown embed saved → {md_path}")

    print("\n💡 To render SVG from the .mmd file install mermaid-cli and run:")
    print("   npx @mermaid-js/mermaid-cli -i diagrams/ecommerce-architecture.mmd "
          "-o diagrams/ecommerce-architecture.svg --theme neutral")
    print("\n🌟 Launch the hand-drawn notebook UI with: diatype serve")


if __name__ == "__main__":
    main()
