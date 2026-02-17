// 1. Changed "sync" to "async" (required to use "await")
async function sendCode() {
    const codeInput = document.getElementById('codeInput').value;
    const modelChoice = document.getElementById('modelSelect').value;
    const outputDiv = document.getElementById('codeOutput');

    if (!codeInput.trim()) {
        alert("Please paste some code first!");
        return;
    }

    // Loading State
    outputDiv.innerHTML = `<div class="animate-pulse text-blue-400">🚀 OptiCode is analyzing with ${modelChoice.toUpperCase()}...</div>`;

    try {
        const response = await fetch('/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                code: codeInput,
                model: modelChoice 
            })
        });

        if (!response.ok) throw new Error("Server not responding");

        const data = await response.json();
        
        const isSecure = data.security_score === 'secure';
        const statusColor = isSecure ? 'text-emerald-400' : 'text-red-500';
        const borderColor = isSecure ? 'border-emerald-900/50' : 'border-red-900/50';

        outputDiv.innerHTML = `
            <div class="mb-6 p-3 border ${borderColor} rounded-lg bg-slate-900/80 shadow-inner">
                <span class="text-xs font-bold uppercase text-slate-400">Security Scan:</span>
                <span class="${statusColor} font-black ml-2">${data.security_score.toUpperCase()}</span>
            </div>
            <div class="prose prose-invert max-w-none">
                ${marked.parse(data.analysis)}
            </div>
        `;
        
    } catch (error) {
        outputDiv.innerHTML = `<div class="text-red-500">❌ Error: Connection failed. Check if main.py is running.</div>`;
    }
}