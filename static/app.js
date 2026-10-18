
const $ = s => document.querySelector(s);

let currentUser = null;
let currentPage = 'dashboard';
let tasks = [];
let docs = [];

function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[c]));
}

function notify(message, error = false) {
    const t = $('#toast');
    t.textContent = message;
    t.className = error ? 'error' : '';
    t.style.display = 'block';

    clearTimeout(window.toastTimeout);
    window.toastTimeout = setTimeout(() => {
        t.style.display = 'none';
    }, 4200);
}

async function api(path, opts = {}) {
    const res = await fetch('/api' + path, {
        credentials: 'same-origin',
        ...opts,
        headers: {
            ...(opts.body instanceof FormData
                ? {}
                : { 'Content-Type': 'application/json' }),
            ...opts.headers
        }
    });

    const data = await res.json().catch(() => ({
        detail: 'Unexpected server response'
    }));

    if (!res.ok) {
        throw new Error(
            typeof data.detail === 'string'
                ? data.detail
                : 'Request failed'
        );
    }

    return data;
}

function show(view) {
    $('#landing').classList.toggle('hidden', view !== 'landing');
    $('#auth').classList.toggle('hidden', view !== 'auth');
    $('#workspace').classList.toggle('hidden', view !== 'workspace');
    $('.topbar').classList.toggle('hidden', view === 'workspace');
    window.scrollTo(0, 0);
}

function authMode(mode) {
    const signup = mode === 'signup';

    $('#authTitle').textContent = signup
        ? 'Create Your Account'
        : 'Welcome Back';

    $('#authSubtitle').textContent = signup
        ? 'Start your intelligent workspace.'
        : 'Sign in to continue your intelligent workspace.';

    $('#nameWrap').classList.toggle('hidden', !signup);
    $('#authName').required = signup;

    $('#authSubmit').textContent = signup
        ? 'Create Account →'
        : 'Sign In →';

    $('#loginTab').classList.toggle('active', !signup);
    $('#signupTab').classList.toggle('active', signup);

    $('#authForm').dataset.mode = mode;

    show('auth');
}

$('#signinBtn').onclick = () => authMode('login');

['startBtn', 'heroStart', 'ctaStart'].forEach(id => {
    $('#' + id).onclick = () => authMode('signup');
});

$('#backHome').onclick = () => show('landing');
$('#loginTab').onclick = () => authMode('login');
$('#signupTab').onclick = () => authMode('signup');

$('#authForm').onsubmit = async e => {
    e.preventDefault();

    const mode = e.currentTarget.dataset.mode || 'login';

    try {
        currentUser = await api('/' + mode, {
            method: 'POST',
            body: JSON.stringify({
                name: $('#authName').value,
                email: $('#authEmail').value,
                password: $('#authPassword').value
            })
        });

        $('#authPassword').value = '';
        await enterWorkspace();

    } catch (err) {
        notify(err.message, true);
    }
};

async function enterWorkspace() {
    const name = currentUser?.name || 'User';
    const initial = name.charAt(0).toUpperCase();

    show('workspace');

    $('#sidebarName').textContent = name;
    $('#headerName').textContent = name;
    $('#avatar').textContent = initial;
    $('#headerAvatar').textContent = initial;

    await refresh();
    navigate('dashboard');
}

async function refresh() {
    try {
        [tasks, docs] = await Promise.all([
            api('/tasks'),
            api('/documents')
        ]);
    } catch (err) {
        notify(err.message, true);
    }
}

function navigate(page) {
    currentPage = page;

    document.querySelectorAll('[data-page]').forEach(button => {
        button.classList.toggle(
            'active',
            button.dataset.page === page
        );
    });

    const names = {
        dashboard: 'Dashboard',
        research: 'New Research',
        documents: 'Knowledge Hub',
        tasks: 'My Tasks',
        workflow: 'AI Workflow'
    };

    $('#breadcrumb').textContent = names[page] || 'Dashboard';

    const pages = {
        dashboard,
        research,
        documents: documentsPage,
        tasks: tasksPage,
        workflow
    };

    $('#page').innerHTML = pages[page]();
    bindPage();
}

document.querySelectorAll('[data-page]').forEach(button => {
    button.onclick = () => navigate(button.dataset.page);
});

// LOGOUT
$('#logoutBtn').onclick = async () => {
    try {
        await api('/logout', { method: 'POST' });

        currentUser = null;
        tasks = [];
        docs = [];

        $('#authPassword').value = '';

        show('landing');
        notify('Successfully logged out');

    } catch (err) {
        notify(err.message, true);
    }
};

function title(heading, description) {
    return `
        <div class="page-title">
            <h1>${heading}</h1>
            <p>${description}</p>
        </div>
    `;
}

function taskRows(list) {
    if (!list.length) {
        return '<div class="empty">No tasks yet. Create your first research task.</div>';
    }

    return list.map(t => `
        <div class="list-row">
            <span class="grow">
                <strong>${esc(t.question)}</strong><br>
                <small class="muted">${esc(t.created_at)}</small>
            </span>

            <span class="pill ${t.status === 'insufficient_evidence' ? 'warn' : ''}">
                ${t.status === 'insufficient_evidence'
                    ? 'Needs sources'
                    : 'Research completed'}
            </span>

            <button class="link-btn" data-task="${esc(t.id)}">
                View →
            </button>
        </div>
    `).join('');
}

function dashboard() {
    const name = esc(
        (currentUser?.name || 'User').split(' ')[0]
    );

    return `
        ${title(
            'Welcome, ' + name + '!',
            'What would you like to accomplish today?'
        )}

        <div class="action-grid">
            <button class="action-card" data-go="research">
                <span class="action-icon">✦</span>
                <span>
                    <strong>New Research</strong>
                    <small>Ask a question</small>
                </span>
            </button>

            <button class="action-card" data-go="documents">
                <span class="action-icon">▤</span>
                <span>
                    <strong>Upload Files</strong>
                    <small>PDF, DOCX, TXT</small>
                </span>
            </button>

            <button class="action-card" data-go="workflow">
                <span class="action-icon">◇</span>
                <span>
                    <strong>Workflow</strong>
                    <small>Explore stages</small>
                </span>
            </button>

            <button class="action-card" data-go="tasks">
                <span class="action-icon">▥</span>
                <span>
                    <strong>Reports</strong>
                    <small>Review results</small>
                </span>
            </button>
        </div>

        <div class="metrics">
            <div class="metric">
                <b>${tasks.length}</b>
                <small>Total tasks</small>
            </div>

            <div class="metric">
                <b>${tasks.filter(t => t.status !== 'insufficient_evidence').length}</b>
                <small>Completed research</small>
            </div>

            <div class="metric">
                <b>${docs.length}</b>
                <small>Uploaded documents</small>
            </div>

            <div class="metric">
                <b>${tasks.filter(t => t.status === 'insufficient_evidence').length}</b>
                <small>Needs more sources</small>
            </div>
        </div>

        <div class="dashboard-cols">
            <div class="panel">
                <h3>Recent Tasks</h3>
                ${taskRows(tasks.slice(0, 7))}
            </div>

            <div class="panel">
                <h3>Your Research Workspace</h3>
                <p class="muted">
                    Ask research questions, explore AI answers,
                    review sources and export PDF reports.
                </p>

                <div class="flow">
                    <div class="flow-step">
                        <strong>01 Research</strong>
                        <small>Ask your question</small>
                    </div>

                    <div class="flow-step">
                        <strong>02 Analyze</strong>
                        <small>Review AI findings</small>
                    </div>

                    <div class="flow-step">
                        <strong>03 Export</strong>
                        <small>Download your report</small>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function research() {
    return `
        ${title(
            'Start a New Research Task',
            'Ask a question and explore AI-powered research findings.'
        )}

        <div class="research-layout">
            <div class="panel">
                <h3>Research Question</h3>

                <form id="researchForm">
                    <label class="field-label" for="question">
                        What would you like to research?
                    </label>

                    <textarea
                        id="question"
                        required
                        minlength="3"
                        maxlength="1500"
                        placeholder="Example: What are the latest developments in artificial intelligence?"
                    ></textarea>

                    <p class="hint">
                        AQIRION AI can use configured AI research
                        capabilities and your uploaded knowledge sources.
                    </p>

                    <button
                        class="btn primary"
                        id="runResearch"
                        type="submit"
                    >
                        ✦ Run Research →
                    </button>
                </form>
            </div>

            <div class="panel">
                <h3>Knowledge Sources</h3>

                <p class="muted">
                    ${docs.length} document(s) uploaded.
                </p>

                ${docs.slice(0, 6).map(d => `
                    <div class="list-row">
                        <span>▤ ${esc(d.name)}</span>
                        <small class="muted">
                            ${esc(d.characters)} chars
                        </small>
                    </div>
                `).join('') || '<p class="muted">No documents uploaded yet.</p>'}

                <button class="link-btn" data-go="documents">
                    Manage Knowledge Hub →
                </button>
            </div>
        </div>

        <div id="researchResult"></div>
    `;
}

function documentsPage() {
    return `
        ${title(
            'Knowledge Hub',
            'Manage your uploaded research documents.'
        )}

        <div class="research-layout">
            <div class="panel">
                <h3>Upload Documents</h3>

                <form id="uploadForm" class="upload-zone">
                    <div style="font-size:36px">▤</div>

                    <strong>Choose a document</strong>

                    <p class="hint">
                        TXT, MD, PDF or DOCX • Up to 5 MB
                    </p>

                    <input
                        id="fileInput"
                        type="file"
                        accept=".txt,.md,.pdf,.docx"
                        required
                    >

                    <button class="btn primary" id="uploadBtn">
                        Upload Document
                    </button>
                </form>
            </div>

            <div class="panel">
                <h3>About your knowledge hub</h3>

                <p class="muted">
                    Your uploaded documents are stored in
                    your account and can support your research.
                </p>
            </div>
        </div>

        <div class="panel">
            <h3>My Documents (${docs.length})</h3>

            ${docs.length
                ? docs.map(d => `
                    <div class="list-row">
                        <span class="grow">
                            ▤ <strong>${esc(d.name)}</strong><br>
                            <small class="muted">
                                ${esc(d.created_at)} ·
                                ${esc(d.characters)} characters
                            </small>
                        </span>

                        <button
                            class="danger-btn"
                            data-delete="${esc(d.id)}"
                        >
                            Delete
                        </button>
                    </div>
                `).join('')
                : '<div class="empty">No documents uploaded yet.</div>'}
        </div>
    `;
}

function tasksPage() {
    return `
        ${title(
            'My Research Tasks',
            'Review previous research and download reports.'
        )}

        <div class="panel">
            <h3>Task History</h3>
            ${taskRows(tasks)}
        </div>

        <div id="taskDetail"></div>
    `;
}

function workflow() {
    return `
        ${title(
            'AI Research Workflow',
            'Explore the stages of your research process.'
        )}

        <div class="panel">
            <h3>Research Pipeline</h3>

            <div class="flow">
                <div class="flow-step">
                    <strong>01 Research</strong>
                    <small>Process the research question</small>
                </div>

                <div class="flow-step">
                    <strong>02 Analysis</strong>
                    <small>Analyze available information</small>
                </div>

                <div class="flow-step">
                    <strong>03 Sources</strong>
                    <small>Display available supporting references</small>
                </div>

                <div class="flow-step">
                    <strong>04 Report</strong>
                    <small>Generate a downloadable PDF</small>
                </div>
            </div>
        </div>

        <div class="panel">
            <h3>Start Research</h3>

            <p class="muted">
                Use AQIRION AI to organize research questions,
                findings, documents and reports.
            </p>

            <button class="btn primary" data-go="research">
                Start Research →
            </button>
        </div>
    `;
}

function resultHTML(r) {
    const summary = r.summary || r.answer || 'No answer available.';
    const steps = Array.isArray(r.steps) ? r.steps : [];
    const evidence = Array.isArray(r.evidence) ? r.evidence : [];
    const sources = Array.isArray(r.sources) ? r.sources : [];

    const statusLabel = r.status === 'insufficient_evidence'
        ? 'Insufficient evidence'
        : 'Research completed';

    const evidenceHTML = evidence.map((e, i) => `
        <div class="source">
            <strong>
                ${i + 1}. ${esc(e.source || 'Document')}
            </strong>
            <p>${esc(e.text || '')}</p>
        </div>
    `).join('');

    const webSourcesHTML = sources.map((source, i) => {
        const url = typeof source === 'string'
            ? source
            : source.url || source.uri || '';

        const label = typeof source === 'string'
            ? source
            : source.title || source.name || url;

        let safeUrl = '';

        try {
            const parsed = new URL(url);
            if (['https:', 'http:'].includes(parsed.protocol)) {
                safeUrl = parsed.href;
            }
        } catch (_) {}

        if (!safeUrl) return '';

        return `
            <div class="source">
                <strong>${i + 1}. Web Source</strong>
                <p>
                    <a
                        href="${esc(safeUrl)}"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        ${esc(label)}
                    </a>
                </p>
            </div>
        `;
    }).join('');

    const reportButton = r.id != null
        ? `
            <a
                class="btn primary"
                style="display:inline-block;margin-top:10px"
                href="/api/tasks/${encodeURIComponent(r.id)}/report.pdf"
            >
                ↓ Download PDF Report
            </a>
        `
        : '';

    return `
        <div class="panel" style="margin-top:20px">
            <h3>AI Research Result</h3>

            <span class="pill ${r.status === 'insufficient_evidence' ? 'warn' : ''}">
                ${statusLabel}
            </span>

            <p
                class="result-summary"
                style="white-space:pre-wrap"
            >${esc(summary)}</p>

            ${reportButton}
        </div>

        ${steps.length ? `
            <div class="panel">
                <h3>Workflow Stages</h3>

                <div class="flow">
                    ${steps.map(s => `
                        <div class="flow-step">
                            <strong>${esc(s.agent || s.name || 'Stage')}</strong>
                            <small>${esc(s.detail || '')}</small>
                        </div>
                    `).join('')}
                </div>
            </div>
        ` : ''}

        <div class="panel">
            <h3>Supporting Document Sources (${evidence.length})</h3>

            ${evidenceHTML ||
                '<p class="muted">No document excerpts available.</p>'}
        </div>

        ${webSourcesHTML ? `
            <div class="panel">
                <h3>Web Sources</h3>
                ${webSourcesHTML}
            </div>
        ` : ''}
    `;
}

function bindPage() {
    document.querySelectorAll('[data-go]').forEach(button => {
        button.onclick = () => navigate(button.dataset.go);
    });

    document.querySelectorAll('[data-task]').forEach(button => {
        button.onclick = async () => {
            try {
                const r = await api('/tasks/' + button.dataset.task);

                if (currentPage !== 'tasks') {
                    navigate('tasks');
                }

                $('#taskDetail').innerHTML = resultHTML(r);
                $('#taskDetail').scrollIntoView({
                    behavior: 'smooth'
                });

            } catch (err) {
                notify(err.message, true);
            }
        };
    });

    document.querySelectorAll('[data-delete]').forEach(button => {
        button.onclick = async () => {
            if (!confirm('Delete this document?')) return;

            try {
                await api('/documents/' + button.dataset.delete, {
                    method: 'DELETE'
                });

                await refresh();
                navigate('documents');
                notify('Document deleted');

            } catch (err) {
                notify(err.message, true);
            }
        };
    });

    const researchForm = $('#researchForm');

    if (researchForm) {
        researchForm.onsubmit = async e => {
            e.preventDefault();

            const button = $('#runResearch');
            button.disabled = true;
            button.textContent = 'Researching…';

            try {
                const r = await api('/tasks', {
                    method: 'POST',
                    body: JSON.stringify({
                        question: $('#question').value
                    })
                });

                $('#researchResult').innerHTML = resultHTML(r);

                await refresh();

                $('#researchResult').scrollIntoView({
                    behavior: 'smooth'
                });

                notify('Research completed');

            } catch (err) {
                notify(err.message, true);

            } finally {
                button.disabled = false;
                button.textContent = '✦ Run Research →';
            }
        };
    }

    const uploadForm = $('#uploadForm');

    if (uploadForm) {
        uploadForm.onsubmit = async e => {
            e.preventDefault();

            const file = $('#fileInput').files[0];

            if (!file) return;

            if (file.size > 5_000_000) {
                notify('Maximum file size: 5 MB', true);
                return;
            }

            const form = new FormData();
            form.append('file', file);

            const button = $('#uploadBtn');
            button.disabled = true;
            button.textContent = 'Uploading…';

            try {
                await api('/documents', {
                    method: 'POST',
                    body: form
                });

                await refresh();
                navigate('documents');

                notify('Document uploaded successfully');

            } catch (err) {
                notify(err.message, true);

            } finally {
                button.disabled = false;
                button.textContent = 'Upload Document';
            }
        };
    }
}

// RESTORE SESSION
(async () => {
    try {
        currentUser = await api('/me');
        await enterWorkspace();
    } catch (_) {
        show('landing');
    }
})();
