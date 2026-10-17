# AQIRION AI

**Your Ideas Deserve More Than Answers.**

AQIRION AI is a full-stack, responsive research workspace with an Emerald Tech theme, an original A/leaf/dot SVG logo, user authentication, document uploads, source-linked offline research, task history, a transparent four-stage workflow and downloadable PDF reports.

## Features in version 1.0

- Responsive marketing homepage, sign-in/sign-up, dashboard and workspace
- Local accounts, PBKDF2-SHA256 password hashing, signed HttpOnly session cookies
- TXT, MD, DOCX and text-based PDF uploads; SQLite storage and per-user isolation
- Offline TF-IDF-like retrieval over uploaded document passages
- Research → Analysis → Source tracing → PDF reporting pipeline
- Task history, evidence excerpts and PDF export
- No paid API key needed for the core application

**Important limitations:** This is an evidence-retrieval prototype, **not** an autonomous multi-LLM agent, independent fact-checker, or live web search engine. The workflow steps describe a deterministic processing pipeline. PDF extraction cannot read image-only scans. The hero artwork is CSS/SVG; no stock photo dependency. Landing page counts and claims of accuracy are intentionally omitted. The product is a functional MVP, not production-hardened SaaS.

## Windows setup (PowerShell)

1. Install Python 3.11 or newer.
2. Unzip the project and open the `aqirion-ai` folder in VS Code.
3. Open a terminal **inside that folder** and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

If PowerShell prevents activating the environment, use these commands without activation:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --reload
```

4. Open **http://127.0.0.1:8000**.
5. Sign up, upload a TXT/PDF/DOCX document, run research, and download a report.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

## Deployment preparation

Set environment variables before hosting:

- `AQIRION_SECRET`: long random value, **persistent across restarts**.
- `AQIRION_SECURE_COOKIES=true`: when using HTTPS.
- `AQIRION_DB`: path to a **persistent** SQLite database file.

Start command: `uvicorn app:app --host 0.0.0.0 --port 8000` (or use the host's supplied `PORT`).

For a public launch, deploy behind HTTPS with persistent storage, database backups, upload quotas, rate limiting, anti-abuse controls, observability, security review and a privacy policy. SQLite may be replaced with PostgreSQL for multi-instance hosting. Free ephemeral hosts can erase local SQLite data; **do not deploy this version to ephemeral storage without a persistent database**. Do not upload sensitive files until your hosting/privacy setup is reviewed. Social sign-in buttons are not included because OAuth needs configured credentials and callbacks.

## Architecture

- `app.py`: FastAPI endpoints, auth, SQLite, uploads, PDF exports
- `engine.py`: offline text splitting and source passage retrieval
- `static/index.html`: all screens
- `static/styles.css`: responsive Emerald Tech design
- `static/app.js`: UI state and API integration
- `static/logo.svg`: scalable selected-style A/leaf/dot symbol
- `tests/`: core engine tests

## Next releases

1. Replace the offline excerpt engine with optional, source-citing LLM synthesis.
2. Add permissioned web search and independent claim verification.
3. Add queue workers and genuine autonomous agent orchestration.
4. Add PostgreSQL, migrations, CSRF tokens, email verification, password reset, SSO/OAuth, RBAC, audit logs and monitoring.
5. Implement deploy-ready CI/CD, privacy and security checks.

© AQIRION AI. Prototype project.
