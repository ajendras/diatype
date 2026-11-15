/* DiaType — Hand-drawn notebook JavaScript */
let currentDiagram = {
    mermaid: '',
    explanation: '',
    svg: '',
    diagram_type: 'flowchart'
};

let mermaidInitialized = false;

function initMermaid() {
    if (mermaidInitialized) return;
    
    mermaid.initialize({
        startOnLoad: false,
        theme: 'base',
        flowchart: { 
            curve: 'basis',
            useMaxWidth: true 
        },
        securityLevel: 'loose',
        fontFamily: 'Instrument Serif, serif'
    });
    
    mermaidInitialized = true;
}

async function renderMermaid(mermaidCode, containerId = 'mermaid-preview') {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    if (!mermaidCode || mermaidCode.trim() === '') {
        container.innerHTML = `
            <div class="flex items-center justify-center h-64 text-[#8d6b4f] italic">
                Your diagram will appear here...
            </div>`;
        return;
    }
    
    try {
        container.innerHTML = `
            <div class="preview-label">Preview</div>
            <div id="mermaid-render-target" class="flex justify-center items-center min-h-[380px]"></div>`;
        
        const target = document.getElementById('mermaid-render-target');
        
        // Use unique ID to avoid mermaid cache collisions
        const uniqueId = 'mermaid-' + Date.now();
        target.innerHTML = `<div id="${uniqueId}" class="mermaid">${mermaidCode}</div>`;
        
        await mermaid.run({
            nodes: [document.getElementById(uniqueId)]
        });
        
        // Capture SVG for export
        const svgElement = target.querySelector('svg');
        if (svgElement) {
            currentDiagram.svg = svgElement.outerHTML;
        }
    } catch (err) {
        console.error('Mermaid render error:', err);
        container.innerHTML = `
            <div class="p-8 text-red-700 bg-red-50 border border-red-300 rounded-2xl">
                <strong>Render error:</strong><br>
                ${err.message}<br><br>
                <small class="opacity-70">The generated syntax may be invalid. Try refining the prompt.</small>
            </div>`;
    }
}

async function generateDiagram(prompt, diagramType = 'flowchart') {
    const statusEl = document.getElementById('status');
    if (statusEl) {
        statusEl.textContent = 'Generating with Ollama...';
        statusEl.className = 'status';
    }
    
    try {
        const response = await fetch('/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt: prompt,
                diagram_type: diagramType
            })
        });
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Generation failed');
        }
        
        const diagram = await response.json();
        currentDiagram = { ...diagram };
        
        // Update UI
        document.getElementById('mermaid-code').value = diagram.mermaid;
        document.getElementById('explanation').innerHTML = `
            <span class="highlighter">Explanation</span><br>
            ${diagram.explanation}
        `;
        
        await renderMermaid(diagram.mermaid);
        
        if (statusEl) {
            statusEl.innerHTML = `
                <span class="inline-block w-3 h-3 bg-emerald-500 rounded-full animate-pulse"></span>
                Ready — ${diagram.diagram_type}
            `;
        }
        
        // Show export toolbar
        const toolbar = document.getElementById('export-toolbar');
        if (toolbar) toolbar.style.display = 'flex';
        
    } catch (err) {
        console.error(err);
        const statusEl = document.getElementById('status');
        if (statusEl) {
            statusEl.textContent = 'Error: ' + err.message;
            statusEl.className = 'status error';
        }
        
        // Show error in preview
        const container = document.getElementById('mermaid-preview');
        if (container) {
            container.innerHTML = `
                <div class="p-6 bg-red-50 border-2 border-red-400 rounded-3xl text-red-800">
                    <div class="font-bold text-lg mb-2">⚠️ Generation failed</div>
                    <p class="text-sm">${err.message}</p>
                    <button onclick="retryLastPrompt()" 
                            class="mt-6 btn btn-secondary text-base">Try again with different wording</button>
                </div>`;
        }
    }
}

async function refineDiagram(instruction) {
    if (!currentDiagram.mermaid) {
        alert("Generate a diagram first!");
        return;
    }
    
    const statusEl = document.getElementById('status');
    if (statusEl) statusEl.textContent = 'Refining diagram...';
    
    try {
        const response = await fetch('/api/refine', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ...currentDiagram,
                instruction: instruction
            })
        });
        
        if (!response.ok) throw new Error('Refinement failed');
        
        const refined = await response.json();
        currentDiagram = { ...refined };
        
        document.getElementById('mermaid-code').value = refined.mermaid;
        document.getElementById('explanation').innerHTML = `
            <span class="highlighter">Refined</span><br>
            ${refined.explanation}
        `;
        
        await renderMermaid(refined.mermaid);
        
        if (statusEl) statusEl.textContent = 'Refinement complete';
        
    } catch (err) {
        console.error(err);
        if (statusEl) {
            statusEl.textContent = 'Refine error: ' + err.message;
            statusEl.className = 'status error';
        }
    }
}

async function explainDiagram() {
    if (!currentDiagram.mermaid) return;
    
    const statusEl = document.getElementById('status');
    if (statusEl) statusEl.textContent = 'Asking for explanation...';
    
    try {
        const response = await fetch('/api/explain', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(currentDiagram)
        });
        
        if (!response.ok) throw new Error('Explanation request failed');
        
        const data = await response.json();
        
        const explDiv = document.getElementById('explanation');
        if (explDiv) {
            explDiv.innerHTML = `
                <span class="highlighter">Explanation</span><br>
                ${data.explanation.replace(/\n/g, '<br>')}
            `;
        }
        
        if (statusEl) statusEl.textContent = 'Explanation updated';
        
    } catch (err) {
        console.error(err);
        if (statusEl) statusEl.textContent = 'Could not explain diagram';
    }
}

async function exportExcalidraw() {
    if (!currentDiagram.mermaid) {
        alert("Generate a diagram first!");
        return;
    }
    
    const statusEl = document.getElementById('status');
    if (statusEl) statusEl.textContent = 'Exporting Excalidraw JSON...';
    
    try {
        const response = await fetch('/api/excalidraw', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(currentDiagram)
        });
        
        if (!response.ok) throw new Error('Export failed');
        
        const exData = await response.json();
        
        const blob = new Blob([JSON.stringify(exData, null, 2)], {
            type: 'application/json'
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `diagram-${currentDiagram.diagram_type || 'flowchart'}.excalidraw`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        if (statusEl) {
            statusEl.innerHTML = `
                <span class="inline-block w-3 h-3 bg-violet-500 rounded-full"></span>
                Excalidraw JSON saved (sketchy style)
            `;
        }
    } catch (err) {
        console.error(err);
        if (statusEl) {
            statusEl.textContent = 'Export error: ' + err.message;
            statusEl.className = 'status error';
        }
    }
}

function exportSVG() {
    if (!currentDiagram.svg) {
        alert("No diagram to export yet.");
        return;
    }
    
    const blob = new Blob([currentDiagram.svg], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `diagram-${currentDiagram.diagram_type || 'flowchart'}.svg`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function exportPNG() {
    if (!currentDiagram.svg) {
        alert("Render a diagram first.");
        return;
    }
    
    const svgBlob = new Blob([currentDiagram.svg], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(svgBlob);
    
    const img = new Image();
    img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = img.width * 2;
        canvas.height = img.height * 2;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#f9f4e9';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        
        canvas.toBlob((pngBlob) => {
            const pngUrl = URL.createObjectURL(pngBlob);
            const a = document.createElement('a');
            a.href = pngUrl;
            a.download = `diagram-${Date.now()}.png`;
            a.click();
            URL.revokeObjectURL(pngUrl);
        }, 'image/png');
        
        URL.revokeObjectURL(url);
    };
    img.src = url;
}

function copyMarkdown() {
    if (!currentDiagram.mermaid) return;
    
    const md = "```mermaid\n" + currentDiagram.mermaid + "\n```";
    navigator.clipboard.writeText(md).then(() => {
        const orig = event.target.textContent;
        event.target.textContent = 'Copied ✓';
        setTimeout(() => {
            event.target.textContent = orig;
        }, 1800);
    });
}

function loadTemplate(prompt, type = 'flowchart') {
    const textarea = document.getElementById('prompt-input');
    if (textarea) {
        textarea.value = prompt;
        // Auto-scroll to top of notebook
        window.scrollTo({ top: 180, behavior: 'smooth' });
    }
    
    // Generate immediately
    setTimeout(() => {
        generateDiagram(prompt, type);
    }, 420);
}

function debounce(fn, delay = 420) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
    };
}

const liveRender = debounce(() => {
    const code = document.getElementById('mermaid-code').value;
    if (code && code.trim()) {
        currentDiagram.mermaid = code;
        renderMermaid(code);
    }
}, 650);

// Attach all event listeners once DOM is ready
function initializeUI() {
    initMermaid();
    
    const generateBtn = document.getElementById('generate-btn');
    if (generateBtn) {
        generateBtn.addEventListener('click', () => {
            const promptInput = document.getElementById('prompt-input');
            if (!promptInput || !promptInput.value.trim()) {
                alert("Please describe the diagram you want.");
                return;
            }
            generateDiagram(promptInput.value.trim());
        });
    }
    
    // Live editing of Mermaid source
    const codeEditor = document.getElementById('mermaid-code');
    if (codeEditor) {
        codeEditor.addEventListener('input', liveRender);
    }
    
    // Refinement form
    const refineForm = document.getElementById('refine-form');
    if (refineForm) {
        refineForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const instructionInput = document.getElementById('refine-instruction');
            if (instructionInput && instructionInput.value.trim()) {
                refineDiagram(instructionInput.value.trim());
                instructionInput.value = '';
            }
        });
    }
    
    // Export handlers
    const exportSvgBtn = document.getElementById('export-svg');
    if (exportSvgBtn) exportSvgBtn.addEventListener('click', exportSVG);
    
    const exportPngBtn = document.getElementById('export-png');
    if (exportPngBtn) exportPngBtn.addEventListener('click', exportPNG);
    
    const exportExBtn = document.getElementById('export-excalidraw');
    if (exportExBtn) exportExBtn.addEventListener('click', exportExcalidraw);
    
    const copyBtn = document.getElementById('copy-md');
    if (copyBtn) copyBtn.addEventListener('click', copyMarkdown);
    
    const explainBtn = document.getElementById('explain-btn');
    if (explainBtn) explainBtn.addEventListener('click', explainDiagram);
    
    // Keyboard shortcut: Ctrl/Cmd + Enter in prompt
    const promptInput = document.getElementById('prompt-input');
    if (promptInput) {
        promptInput.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                if (promptInput.value.trim()) {
                    generateDiagram(promptInput.value.trim());
                }
            }
        });
    }
    
    // Make sticky notes in gallery interactive
    document.querySelectorAll('.sticky-note').forEach(note => {
        note.addEventListener('click', () => {
            const prompt = note.getAttribute('data-prompt');
            const type = note.getAttribute('data-type') || 'flowchart';
            if (prompt) loadTemplate(prompt, type);
        });
    });
    
    // Initial demo diagram after a short delay
    setTimeout(() => {
        const demoPrompt = "User authentication flow with login, verification and database";
        const demoCode = `flowchart TD
    A[User] -->|enters credentials| B[Login Service]
    B --> C{Valid?}
    C -->|Yes| D[Dashboard]
    C -->|No| E[Error Message]
    D --> F[Session Stored in DB]`;
        
        currentDiagram = {
            mermaid: demoCode,
            explanation: "This flowchart illustrates a typical user login sequence including credential validation and session storage.",
            svg: '',
            diagram_type: 'flowchart'
        };
        
        const codeEl = document.getElementById('mermaid-code');
        if (codeEl) codeEl.value = demoCode;
        
        const explEl = document.getElementById('explanation');
        if (explEl) {
            explEl.innerHTML = `<span class="highlighter">Example</span><br>This flowchart illustrates a typical user login sequence including credential validation and session storage.`;
        }
        
        renderMermaid(demoCode);
        
        const toolbar = document.getElementById('export-toolbar');
        if (toolbar) toolbar.style.display = 'flex';
    }, 120);
}

// Auto-initialize when loaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeUI);
} else {
    initializeUI();
}

// Global helper for inline onclick handlers
window.retryLastPrompt = function() {
    const promptInput = document.getElementById('prompt-input');
    if (promptInput && promptInput.value) {
        generateDiagram(promptInput.value);
    }
};

window.exportSVG = exportSVG;
window.exportPNG = exportPNG;
window.exportExcalidraw = exportExcalidraw;
window.copyMarkdown = copyMarkdown;
window.explainDiagram = explainDiagram;
