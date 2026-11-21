import {
	App,
	Editor,
	MarkdownView,
	Modal,
	Notice,
	Plugin,
	PluginSettingTab,
	Setting,
} from "obsidian";

interface DiaTypeSettings {
	apiBaseUrl: string;
	defaultDiagramType: string;
}

const DEFAULT_SETTINGS: DiaTypeSettings = {
	apiBaseUrl: "http://127.0.0.1:8000",
	defaultDiagramType: "flowchart",
};

class DiaTypeModal extends Modal {
	prompt = "";
	diagramType = "flowchart";
	plugin: DiaTypePlugin;
	editor: Editor;

	constructor(app: App, plugin: DiaTypePlugin, editor: Editor) {
		super(app);
		this.plugin = plugin;
		this.editor = editor;
		this.diagramType = plugin.settings.defaultDiagramType;
	}

	onOpen() {
		const { contentEl } = this;
		contentEl.empty();
		contentEl.addClass("diatype-modal");

		contentEl.createEl("h2", {
			text: "Generate Diagram with DiaType",
			cls: "diatype-title",
		});

		new Setting(contentEl)
			.setName("Description")
			.setDesc("Describe the diagram in plain English")
			.addTextArea((text) => {
				text.setPlaceholder(
					"User logs in via OAuth, then the API gateway routes to an order service backed by PostgreSQL"
				)
					.setValue(this.prompt)
					.onChange((val) => {
						this.prompt = val;
					});
				text.inputEl.rows = 5;
				text.inputEl.style.width = "100%";
				text.inputEl.style.fontFamily = "var(--font-interface)";
			});

		new Setting(contentEl)
			.setName("Diagram type")
			.setDesc("Mermaid diagram kind")
			.addDropdown((dd) => {
				dd.addOption("flowchart", "Flowchart")
					.addOption("sequenceDiagram", "Sequence")
					.addOption("classDiagram", "Class")
					.addOption("stateDiagram", "State")
					.addOption("erDiagram", "Entity Relationship")
					.addOption("mindmap", "Mindmap")
					.setValue(this.diagramType)
					.onChange((val) => {
						this.diagramType = val;
					});
			});

		new Setting(contentEl)
			.addButton((btn) =>
				btn
					.setButtonText("Generate & Insert")
					.setCta()
					.onClick(() => this.generateDiagram())
			)
			.addButton((btn) =>
				btn
					.setButtonText("Cancel")
					.onClick(() => this.close())
			);
	}

	async generateDiagram() {
		if (!this.prompt || this.prompt.trim().length < 8) {
			new Notice("Description must be at least 8 characters.");
			return;
		}

		const url = `${this.plugin.settings.apiBaseUrl}/api/generate`;
		const payload = {
			prompt: this.prompt.trim(),
			diagram_type: this.diagramType,
			format: "mermaid",
		};

		try {
			new Notice("Asking local LLM to generate diagram…");

			const response = await fetch(url, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(payload),
			});

			if (!response.ok) {
				throw new Error(`HTTP error ${response.status}`);
			}

			const diagram = await response.json();

			const markdown = `\`\`\`mermaid\n${diagram.source}\n\`\`\`\n\n**Explanation:** ${diagram.explanation}\n\n`;

			this.editor.replaceSelection(markdown);
			new Notice("Diagram inserted successfully ✓");
			this.close();
		} catch (err: any) {
			console.error(err);
			new Notice(`Generation failed: ${err.message || err}`);
		}
	}

	onClose() {
		const { contentEl } = this;
		contentEl.empty();
	}
}

class DiaTypeSettingTab extends PluginSettingTab {
	plugin: DiaTypePlugin;

	constructor(app: App, plugin: DiaTypePlugin) {
		super(app, plugin);
		this.plugin = plugin;
	}

	display(): void {
		const { containerEl } = this;
		containerEl.empty();

		containerEl.createEl("h2", { text: "DiaType Settings" });

		new Setting(containerEl)
			.setName("API base URL")
			.setDesc("URL of your running DiaType server (default is localhost)")
			.addText((text) =>
				text
					.setPlaceholder("http://127.0.0.1:8000")
					.setValue(this.plugin.settings.apiBaseUrl)
					.onChange(async (value) => {
						this.plugin.settings.apiBaseUrl = value.trim();
						await this.plugin.saveSettings();
					})
			);

		new Setting(containerEl)
			.setName("Default diagram type")
			.setDesc("Pre-selected type in the generation modal")
			.addDropdown((dd) => {
				dd.addOption("flowchart", "Flowchart")
					.addOption("sequenceDiagram", "Sequence")
					.addOption("classDiagram", "Class")
					.addOption("stateDiagram", "State")
					.addOption("erDiagram", "Entity Relationship")
					.addOption("mindmap", "Mindmap")
					.setValue(this.plugin.settings.defaultDiagramType)
					.onChange(async (value) => {
						this.plugin.settings.defaultDiagramType = value;
						await this.plugin.saveSettings();
					});
			});
	}
}

export default class DiaTypePlugin extends Plugin {
	settings: DiaTypeSettings;

	async onload() {
		await this.loadSettings();

		this.addRibbonIcon("diagram", "Generate DiaType diagram", (evt: MouseEvent) => {
			const activeView = this.app.workspace.getActiveViewOfType(MarkdownView);
			if (!activeView || !activeView.editor) {
				new Notice("Open a markdown file first.");
				return;
			}
			new DiaTypeModal(this.app, this, activeView.editor).open();
		});

		this.addCommand({
			id: "insert-diatype-diagram",
			name: "Insert generated diagram",
			editorCallback: (editor: Editor, view: MarkdownView) => {
				new DiaTypeModal(this.app, this, editor).open();
			},
		});

		this.addSettingTab(new DiaTypeSettingTab(this.app, this));

		console.log("DiaType Obsidian plugin loaded");
	}

	onunload() {}

	async loadSettings() {
		this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
	}

	async saveSettings() {
		await this.saveData(this.settings);
	}
}
