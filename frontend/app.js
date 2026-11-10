const BACKEND_URL = 'http://127.0.0.1:8080/chat';
let currentThreadId = '';
let activeController = null;

window.addEventListener('DOMContentLoaded', () => {
    startNewThread();
    checkBackendConnection();
    
    document.getElementById('chat-input').addEventListener('input', function() {
        const btn = document.getElementById('send-btn');
        if (activeController) {
            btn.disabled = true;
            return;
        }
        btn.disabled = this.value.trim().length === 0;
    });
});

function generateThreadId() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}${pad(d.getMonth()+1)}${pad(d.getDate())}${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function startNewThread() {
    currentThreadId = generateThreadId();
    document.getElementById('thread-id-display').innerText = currentThreadId;
    
    const container = document.getElementById('chat-container');
    container.innerHTML = '';
}

async function checkBackendConnection() {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 2000);
        await fetch('http://127.0.0.1:8080/checkpoints?thread_id=ping', { method: 'GET', signal: controller.signal });
        clearTimeout(timeoutId);
        dot.className = 'status-dot';
        text.innerText = 'Connected';
    } catch(e) {
        dot.className = 'status-dot disconnected';
        text.innerText = 'Disconnected';
    }
}
setInterval(checkBackendConnection, 10000);

function autoGrow(element) {
    element.style.height = "20px";
    element.style.height = element.scrollHeight + "px";
}

function handleKeyPress(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

function getMessageText(content) {
    if (typeof content === 'string') return content;
    if (Array.isArray(content)) {
        let text = '';
        content.forEach(item => {
            if (typeof item === 'string') text += item;
            else if (item && typeof item === 'object') {
                if (item.type === 'thinking') return;
                if (item.text) text += item.text;
                else if (item.content) text += item.content;
            }
        });
        return text;
    }
    return String(content);
}

function setAgentRunningState(runningAgent) {
    const agents = ['Orchestrator', 'Notes_Agent', 'Question_Maker_Agent', 'Explainer_Agent'];
    agents.forEach(agent => {
        const badge = document.getElementById(`badge-${agent}`);
        if (badge) {
            badge.style.display = (agent === runningAgent) ? 'inline-flex' : 'none';
        }
    });
}

function renderParsedStream(streamText) {
    const lines = streamText.split('\n');
    let html = '';
    let activeRunningAgent = 'Orchestrator';
    
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (!line || !line.trim()) continue;
        
        const trimmedLine = line.trim();
        
        let match = line.match(/^Orchestrator -> You:\s*(.*)$/i);
        if (match) {
            activeRunningAgent = null;
            let contentText = match[1];
            for (let j = i + 1; j < lines.length; j++) {
                contentText += '\n' + lines[j];
            }
            
            html += `
                <div class="message-row ai">
                    <div class="message-bubble">
                        <div class="orchestrator-output-header" style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: var(--primary); margin-bottom: 6px; letter-spacing: 0.5px;">Orchestrator -> User</div>
                        ${contentText.replace(/\n/g, '<br>')}<span class="typing-cursor"></span>
                    </div>
                    <div class="message-meta">
                        <button class="action-btn retry-btn" onclick="triggerRetry(this)">
                            <svg viewBox="0 0 24 24"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
                            Retry
                        </button>
                    </div>
                </div>
            `;
            break;
        }

        match = trimmedLine.match(/^Orchestrator -> ([A-Za-z0-9_]+):\s*"?(.*?)"?$/i);
        if (match) {
            const target = match[1];
            const content = match[2];
            activeRunningAgent = target;
            html += `
                <div class="directive-row">
                    <div class="directive-header">
                        <span>Orchestrator ➜ ${target}</span>
                        <button class="action-btn retry-btn" onclick="triggerRetry(this)">
                            <svg viewBox="0 0 24 24"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
                            Retry
                        </button>
                    </div>
                    <div class="directive-content">"${content}"</div>
                </div>
            `;
            continue;
        }
        
        match = trimmedLine.match(/^\[([A-Za-z0-9_]+) is running tool: (.*?)\]/i);
        if (match) {
            const agent = match[1];
            const tool = match[2];
            activeRunningAgent = agent;
            html += `
                <div class="system-badge-row">
                    <div class="system-badge success">
                        <span>✔</span>
                        <span>${agent} ran tool: <strong>${tool.replace(/\.\.\./g, '')}</strong></span>
                    </div>
                </div>
            `;
            continue;
        }
        
        match = trimmedLine.match(/^\[([A-Za-z0-9_]+) finished running tool\.?\]/i);
        if (match) {
            continue;
        }
        
        match = trimmedLine.match(/^\[([A-Za-z0-9_]+) finished processing.\]/i);
        if (match) {
            const agent = match[1];
            activeRunningAgent = 'Orchestrator';
            html += `
                <div class="system-badge-row">
                    <div class="system-badge success">
                        <span>✔</span>
                        <span>${agent} finished execution.</span>
                    </div>
                </div>
            `;
            continue;
        }
        
        match = line.match(/^\[([A-Za-z0-9_]+) Thinking:\s*(.*)$/i);
        if (match) {
            const agent = match[1];
            activeRunningAgent = agent;
            let thinkingContent = match[2];
            
            let nextIndex = i + 1;
            let closed = false;
            
            if (thinkingContent.endsWith(']')) {
                thinkingContent = thinkingContent.slice(0, -1);
                closed = true;
            } else {
                for (let j = i + 1; j < lines.length; j++) {
                    const l = lines[j];
                    nextIndex = j + 1;
                    if (l.includes(']')) {
                        const parts = l.split(']');
                        thinkingContent += '\n' + parts[0];
                        closed = true;
                        if (parts[1] && parts[1].trim()) {
                            lines[j] = parts[1];
                            nextIndex = j;
                        }
                        break;
                    } else {
                        thinkingContent += '\n' + l;
                    }
                }
            }
            
            html += `
                <details class="thinking-dropdown">
                    <summary>${agent} Reasoning Process</summary>
                    <div class="thinking-content">${thinkingContent}${!closed ? '<span class="typing-cursor"></span>' : ''}</div>
                </details>
            `;
            
            i = nextIndex - 1;
            continue;
        }
        
        match = trimmedLine.match(/^Error occurred during execution:\s*(.*)$/i);
        if (match) {
            let errDetails = match[1];
            activeRunningAgent = null;
            
            for (let j = i + 1; j < lines.length; j++) {
                errDetails += '\n' + lines[j];
            }
            
            html += `
                <div class="system-badge-row" style="flex-direction: column; align-items: flex-start; gap: 8px; width: 100%;">
                    <div class="system-badge" style="background: rgba(239, 68, 68, 0.08); border-color: rgba(239, 68, 68, 0.2); color: #ef4444; max-width: 100%; word-break: break-word; padding: 12px 16px; border-radius: 8px; font-size: 13px; line-height: 1.5; text-align: left; display: block; width: 100%;">
                        <strong>✖ System Error:</strong> ${errDetails.replace(/\n/g, '<br>')}
                    </div>
                    <div class="message-meta" style="margin-left: 0; padding-left: 0;">
                        <button class="action-btn retry-btn" onclick="triggerRetry(this)" style="color: #ef4444;">
                            <svg viewBox="0 0 24 24"><path fill="currentColor" d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
                            Retry
                        </button>
                    </div>
                </div>
            `;
            break;
        }
        
        let sender = 'Notes_Agent';
        if (activeRunningAgent && activeRunningAgent !== 'Orchestrator') {
            sender = activeRunningAgent;
        } else {
            const lastThinking = lines.slice(0, i + 1).reverse().find(l => l.includes('Thinking:'));
            if (lastThinking) {
                const m = lastThinking.match(/\[([A-Za-z0-9_]+) Thinking:/);
                if (m) sender = m[1];
            }
        }
        activeRunningAgent = sender;
        
        let agentContent = line;
        let nextI = i + 1;
        for (let j = i + 1; j < lines.length; j++) {
            const l = lines[j];
            if (l.includes('Orchestrator ->') || l.includes('Thinking:') || l.includes('running tool:') || l.includes('finished processing')) {
                nextI = j;
                break;
            }
            agentContent += '\n' + l;
            nextI = j + 1;
        }
        
        html += `
            <div class="message-row ai">
                <div class="message-bubble" style="background: rgba(30, 41, 59, 0.45); border-color: rgba(255, 255, 255, 0.04);">
                    <div class="agent-output-header" style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: var(--info); margin-bottom: 6px; letter-spacing: 0.5px;">${sender} Output</div>
                    ${agentContent.replace(/\n/g, '<br>')}<span class="typing-cursor"></span>
                </div>
                <div class="message-meta">
                    <button class="action-btn retry-btn" onclick="triggerRetry(this)">
                        <svg viewBox="0 0 24 24"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
                        Retry
                    </button>
                </div>
            </div>
        `;
        i = nextI - 1;
    }
    
    setAgentRunningState(activeRunningAgent);
    
    return html;
}

async function sendMessage() {
    const inputField = document.getElementById('chat-input');
    const query = inputField.value.trim();
    if (!query) return;

    if (activeController) return;

    inputField.value = '';
    inputField.style.height = '20px';
    document.getElementById('send-btn').disabled = true;

    const chatContainer = document.getElementById('chat-container');
    const isFirstMessage = chatContainer.querySelectorAll('.message-row.human').length === 0;
    const editBtnHtml = isFirstMessage ? '' : `
        <div class="message-meta">
            <button class="action-btn edit-btn" onclick="triggerEdit(this)">
                <svg viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>
                Edit
            </button>
        </div>
    `;

    const humanRowHtml = `
        <div class="message-row human">
            <div class="message-bubble">
                ${query.replace(/\n/g, '<br>')}
            </div>
            ${editBtnHtml}
        </div>
    `;
    chatContainer.insertAdjacentHTML('beforeend', humanRowHtml);
    chatContainer.scrollTop = chatContainer.scrollHeight;

    activeController = new AbortController();
    startStreamingState();
    setAgentRunningState('Orchestrator');

    const activeStreamId = 'active-stream-' + Date.now();
    const activeStreamHtml = `<div id="${activeStreamId}" style="width:100%; display: flex; flex-direction: column; gap:16px;"></div>`;
    chatContainer.insertAdjacentHTML('beforeend', activeStreamHtml);
    const activeStreamDiv = document.getElementById(activeStreamId);

    try {
        const response = await fetch(BACKEND_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query, thread_id: currentThreadId }),
            signal: activeController.signal
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let accumulatedText = '';

        let renderPending = false;
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value, { stream: true });
            accumulatedText += chunk;
            if (!renderPending) {
                renderPending = true;
                requestAnimationFrame(() => {
                    activeStreamDiv.innerHTML = renderParsedStream(accumulatedText);
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                    renderPending = false;
                });
            }
        }
        
        activeStreamDiv.innerHTML = renderParsedStream(accumulatedText);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    } catch(err) {
        if (err.name !== 'AbortError') {
            activeStreamDiv.insertAdjacentHTML('beforeend', `
                <div class="system-badge-row">
                    <div class="system-badge" style="background: rgba(239, 68, 68, 0.08); border-color: rgba(239, 68, 68, 0.2); color: #ef4444;">
                        <span>✖ Error: Failed to connect to server stream.</span>
                    </div>
                </div>
            `);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
        setAgentRunningState(null);
    } finally {
        const cursors = activeStreamDiv.querySelectorAll('.typing-cursor');
        cursors.forEach(c => c.remove());
        
        activeController = null;
        stopStreamingState();
        setAgentRunningState(null);
        
        await fetchAndAssignCheckpoints();
    }
}

function startStreamingState() {
    const btn = document.getElementById('send-btn');
    btn.disabled = true;
}

function stopStreamingState() {
    const btn = document.getElementById('send-btn');
    const inputField = document.getElementById('chat-input');
    btn.disabled = inputField.value.trim().length === 0;
}

async function fetchAndAssignCheckpoints() {
    try {
        const response = await fetch(`http://127.0.0.1:8080/checkpoints?thread_id=${currentThreadId}`);
        if (!response.ok) return;
        const checkpoints = await response.json();
        
        const bubbles = Array.from(document.querySelectorAll(
            '#chat-container .message-row, ' +
            '#chat-container .directive-row, ' +
            '#chat-container .system-badge-row, ' +
            '#chat-container .thinking-dropdown'
        ));
        
        let checkpointPtr = checkpoints.length - 1;
        const firstHumanBubble = bubbles.find(b => b.classList.contains('human'));
        let currentIdx = null;
        
        for (let i = bubbles.length - 1; i >= 0; i--) {
            const bubble = bubbles[i];
            
            if (bubble.classList.contains('human')) {
                while (checkpointPtr >= 0) {
                    const cp = checkpoints[checkpointPtr];
                    if (cp.next_node.includes('__start__')) {
                        currentIdx = cp.idx;
                        bubble.setAttribute('data-idx', currentIdx);
                        
                        if (bubble === firstHumanBubble) {
                            const editBtn = bubble.querySelector('.edit-btn');
                            if (editBtn) editBtn.remove();
                        }
                        checkpointPtr--;
                        break;
                    }
                    checkpointPtr--;
                }
            } else if (bubble.classList.contains('directive-row')) {
                while (checkpointPtr >= 0) {
                    const cp = checkpoints[checkpointPtr];
                    const nextCp = checkpoints[checkpointPtr + 1];
                    if (cp.next_node.includes('Orchestrator_Manager') && nextCp && nextCp.current_worker && nextCp.current_worker !== 'FINISH') {
                        currentIdx = cp.idx;
                        bubble.setAttribute('data-idx', currentIdx);
                        checkpointPtr--;
                        break;
                    }
                    checkpointPtr--;
                }
            } else if (bubble.classList.contains('ai')) {
                const isFinal = bubble.querySelector('.orchestrator-output-header') !== null;
                
                if (isFinal) {
                    while (checkpointPtr >= 0) {
                        const cp = checkpoints[checkpointPtr];
                        const nextCp = checkpoints[checkpointPtr + 1];
                        if (cp.next_node.includes('Orchestrator_Manager') && (!nextCp || nextCp.current_worker === 'FINISH')) {
                            currentIdx = cp.idx;
                            bubble.setAttribute('data-idx', currentIdx);
                            checkpointPtr--;
                            break;
                        }
                        checkpointPtr--;
                    }
                } else {
                    while (checkpointPtr >= 0) {
                        const cp = checkpoints[checkpointPtr];
                        const isSubAgent = cp.next_node.some(node => ['Notes_Agent', 'Question_Maker_Agent', 'Explainer_Agent'].includes(node));
                        if (isSubAgent) {
                            currentIdx = cp.idx;
                            bubble.setAttribute('data-idx', currentIdx);
                            checkpointPtr--;
                            break;
                        }
                        checkpointPtr--;
                    }
                }
            } else if (bubble.classList.contains('thinking-dropdown') || bubble.classList.contains('system-badge-row')) {
                if (currentIdx !== null) {
                    bubble.setAttribute('data-idx', currentIdx);
                }
            }
        }
    } catch (e) {
        console.error("Error matching checkpoints: ", e);
    }
}

function rollbackUI(idx) {
    const chatContainer = document.getElementById('chat-container');
    
    const elements = Array.from(document.querySelectorAll(
        '#chat-container .message-row, ' +
        '#chat-container .directive-row, ' +
        '#chat-container .system-badge-row, ' +
        '#chat-container .thinking-dropdown'
    ));
    
    let startDeleting = false;
    
    elements.forEach(el => {
        const val = parseInt(el.getAttribute('data-idx'));
        if (!startDeleting && !isNaN(val) && val >= idx) {
            startDeleting = true;
        }
        if (startDeleting) {
            el.remove();
        }
    });
    
    document.querySelectorAll('[id^="active-stream-"]').forEach(wrapper => {
        if (wrapper.children.length === 0) {
            wrapper.remove();
        }
    });
}

async function triggerRetry(btn) {
    if (activeController) return;
    
    const bubble = btn.closest('.message-row, .directive-row');
    if (!bubble) return;
    const idxStr = bubble.getAttribute('data-idx');
    if (idxStr === null || idxStr === undefined) return;
    const idx = parseInt(idxStr);
    if (isNaN(idx)) return;
    
    rollbackUI(idx);
    
    activeController = new AbortController();
    startStreamingState();
    setAgentRunningState('Orchestrator');
    
    const chatContainer = document.getElementById('chat-container');
    const activeStreamId = 'active-stream-' + Date.now();
    const activeStreamHtml = `<div id="${activeStreamId}" style="width:100%; display: flex; flex-direction: column; gap:16px;"></div>`;
    chatContainer.insertAdjacentHTML('beforeend', activeStreamHtml);
    const activeStreamDiv = document.getElementById(activeStreamId);
    
    try {
        const response = await fetch(`http://127.0.0.1:8080/retry?thread_id=${currentThreadId}&idx=${idx}&continue_chat=true`, {
            method: 'POST',
            signal: activeController.signal
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let accumulatedText = '';
        
        let renderPending = false;
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value, { stream: true });
            accumulatedText += chunk;
            if (!renderPending) {
                renderPending = true;
                requestAnimationFrame(() => {
                    activeStreamDiv.innerHTML = renderParsedStream(accumulatedText);
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                    renderPending = false;
                });
            }
        }
        
        activeStreamDiv.innerHTML = renderParsedStream(accumulatedText);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    } catch(err) {
        if (err.name !== 'AbortError') {
            activeStreamDiv.insertAdjacentHTML('beforeend', `
                <div class="system-badge-row">
                    <div class="system-badge" style="background: rgba(239, 68, 68, 0.08); border-color: rgba(239, 68, 68, 0.2); color: #ef4444;">
                        <span>✖ Error: Failed to retry stream execution.</span>
                    </div>
                </div>
            `);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
        setAgentRunningState(null);
    } finally {
        const cursors = activeStreamDiv.querySelectorAll('.typing-cursor');
        cursors.forEach(c => c.remove());
        
        activeController = null;
        stopStreamingState();
        setAgentRunningState(null);
        
        await fetchAndAssignCheckpoints();
    }
}

function triggerEdit(btn) {
    if (activeController) return;
    
    const messageRow = btn.closest('.message-row');
    if (!messageRow) return;
    const idxStr = messageRow.getAttribute('data-idx');
    if (idxStr === null || idxStr === undefined) return;
    const idx = parseInt(idxStr);
    if (isNaN(idx)) return;
    
    const bubble = messageRow.querySelector('.message-bubble');
    const originalText = bubble.innerText.trim();
    
    const originalHTML = bubble.innerHTML;
    bubble.innerHTML = `
        <textarea class="edit-textarea" style="width: 100%; min-height: 60px; background: rgba(0,0,0,0.2); border: 1px solid var(--panel-border); color: #fff; padding: 8px; border-radius: 6px; resize: vertical; outline: none; font-family: inherit; font-size: inherit; line-height: inherit; margin-bottom: 6px;"></textarea>
        <div style="display: flex; gap: 8px; justify-content: flex-end;">
            <button class="action-btn" onclick="saveEdit(${idx}, this)" style="color: var(--success); font-weight:600; padding: 4px 8px; background: rgba(16, 185, 129, 0.1); border-radius: 4px;">Save</button>
            <button class="action-btn" onclick="cancelEdit(this)" style="color: #ef4444; font-weight:600; padding: 4px 8px; background: rgba(239, 68, 68, 0.1); border-radius: 4px;">Cancel</button>
        </div>
    `;
    bubble.querySelector('textarea').value = originalText;
    bubble.dataset.originalHTML = originalHTML;
}

function cancelEdit(btn) {
    const bubble = btn.closest('.message-bubble');
    bubble.innerHTML = bubble.dataset.originalHTML;
}

async function saveEdit(idx, btn) {
    const bubble = btn.closest('.message-bubble');
    const newText = bubble.querySelector('textarea').value.trim();
    if (!newText) return;
    
    rollbackUI(idx);
    
    activeController = new AbortController();
    startStreamingState();
    
    try {
        const response = await fetch(`http://127.0.0.1:8080/retry?thread_id=${currentThreadId}&idx=${idx}&continue_chat=false`, {
            method: 'POST',
            signal: activeController.signal
        });
        
        if (!response.ok) {
            throw new Error(`Failed to fork graph state configuration.`);
        }
        
        activeController = null;
        
        document.getElementById('chat-input').value = newText;
        sendMessage();
    } catch (err) {
        console.error(err);
        stopStreamingState();
        setAgentRunningState(null);
        alert("Failed to edit prompt: " + err.message);
    }
}
