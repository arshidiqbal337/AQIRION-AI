
import os
import json
import sqlite3
import hashlib
import hmac
import secrets
import io
import re

from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from xml.sax.saxutils import escape

from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    StreamingResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from itsdangerous import (
    URLSafeTimedSerializer,
    BadSignature,
    SignatureExpired,
)
from pypdf import PdfReader
from docx import Document
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from authlib.integrations.starlette_client import OAuth, OAuthError
from starlette.middleware.sessions import SessionMiddleware

from engine import retrieve, generate_ai_answer


# ============================================================
# CONFIGURATION
# ============================================================

BASE = Path(__file__).resolve().parent
DB = Path(os.getenv("AQIRION_DB", str(BASE / "aqirion.db")))

SECRET = os.getenv("AQIRION_SECRET", "")

if not SECRET:
    SECRET = secrets.token_urlsafe(48)
    print(
        "WARNING: AQIRION_SECRET is not set. "
        "Login sessions will reset when the server restarts."
    )

SECURE_COOKIES = (
    os.getenv("AQIRION_SECURE_COOKIES", "false").lower() == "true"
)

signer = URLSafeTimedSerializer(
    SECRET,
    salt="aqirion-session-v1",
)

app = FastAPI(
    title="AQIRION AI",
    version="1.3.0",
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET,
    session_cookie="aqirion_oauth_state",
    max_age=600,
    same_site="lax",
    https_only=SECURE_COOKIES,
)

oauth = OAuth()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url=(
            "https://accounts.google.com/"
            ".well-known/openid-configuration"
        ),
        client_kwargs={
            "scope": "openid email profile",
        },
    )

app.mount(
    "/static",
    StaticFiles(directory=BASE / "static"),
    name="static",
)


# ============================================================
# DATABASE
# ============================================================

@contextmanager
def conn():
    DB.parent.mkdir(parents=True, exist_ok=True)

    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row

    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db():
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                salt TEXT NOT NULL,
                pw_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

        columns = {
            row["name"]
            for row in c.execute("PRAGMA table_info(users)")
        }

        if "google_subject" not in columns:
            c.execute(
                "ALTER TABLE users "
                "ADD COLUMN google_subject TEXT"
            )

        c.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_users_google_subject
            ON users(google_subject)
            """
        )

        # Support Google accounts from the earlier OAuth version.
        existing_tables = {
            row["name"]
            for row in c.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table'"
            )
        }

        if "google_accounts" in existing_tables:
            c.execute(
                """
                UPDATE users
                SET google_subject = (
                    SELECT ga.google_sub
                    FROM google_accounts ga
                    WHERE ga.user_id = users.id
                )
                WHERE google_subject IS NULL
                  AND EXISTS (
                    SELECT 1
                    FROM google_accounts ga
                    WHERE ga.user_id = users.id
                  )
                """
            )


init_db()


def now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        310000,
    ).hex()


# ============================================================
# SECURITY AND SESSIONS
# ============================================================

def user(request: Request):
    cookie = request.cookies.get("aqirion_session")

    if not cookie:
        raise HTTPException(401, "Please sign in")

    try:
        uid = int(
            signer.loads(
                cookie,
                max_age=60 * 60 * 24 * 7,
            )
        )
    except (BadSignature, SignatureExpired, ValueError):
        raise HTTPException(401, "Session expired")

    with conn() as c:
        row = c.execute(
            """
            SELECT id, name, email
            FROM users
            WHERE id = ?
            """,
            (uid,),
        ).fetchone()

    if not row:
        raise HTTPException(401, "Account not found")

    return dict(row)


def csrf_check(request: Request):
    origin = request.headers.get("origin")

    if origin:
        from urllib.parse import urlsplit

        parsed = urlsplit(origin)
        host = request.headers.get("host", "")

        if parsed.netloc != host:
            raise HTTPException(403, "Origin mismatch")


def session_response(uid, name, email):
    response = JSONResponse(
        {
            "id": uid,
            "name": name,
            "email": email,
        }
    )

    response.set_cookie(
        key="aqirion_session",
        value=signer.dumps(str(uid)),
        httponly=True,
        samesite="lax",
        secure=SECURE_COOKIES,
        max_age=604800,
        path="/",
    )

    return response


class Auth(BaseModel):
    name: str = ""
    email: str
    password: str


class Query(BaseModel):
    question: str = Field(
        min_length=3,
        max_length=1500,
    )


# ============================================================
# FRONTEND
# ============================================================

@app.get("/")
def home():
    return FileResponse(
        BASE / "static" / "index.html"
    )


# ============================================================
# NORMAL LOGIN / SIGNUP
# ============================================================

@app.get("/api/me")
def me(request: Request):
    return user(request)


@app.post("/api/signup")
def signup(body: Auth, request: Request):
    csrf_check(request)

    name = body.name.strip()
    email = body.email.strip().lower()

    if (
        len(name) < 2
        or len(name) > 80
        or not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            email,
        )
        or len(body.password) < 10
        or len(body.password) > 256
    ):
        raise HTTPException(
            400,
            "Use a valid name/email and a password "
            "of 10+ characters",
        )

    salt = secrets.token_hex(16)

    try:
        with conn() as c:
            cursor = c.execute(
                """
                INSERT INTO users (
                    name, email, salt, pw_hash, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    name,
                    email,
                    salt,
                    password_hash(body.password, salt),
                    now(),
                ),
            )
            uid = cursor.lastrowid

    except sqlite3.IntegrityError:
        raise HTTPException(
            409,
            "Email already registered",
        )

    return session_response(uid, name, email)


@app.post("/api/login")
def login(body: Auth, request: Request):
    csrf_check(request)

    with conn() as c:
        row = c.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (body.email.strip().lower(),),
        ).fetchone()

    salt = row["salt"] if row else "00" * 16
    digest = password_hash(body.password, salt)

    if not row or not hmac.compare_digest(
        digest,
        row["pw_hash"],
    ):
        raise HTTPException(
            401,
            "Invalid email or password",
        )

    return session_response(
        row["id"],
        row["name"],
        row["email"],
    )


@app.post("/api/logout")
def logout(request: Request):
    csrf_check(request)

    response = JSONResponse({"ok": True})
    response.delete_cookie(
        "aqirion_session",
        path="/",
    )

    return response


# ============================================================
# GOOGLE LOGIN
# ============================================================

@app.get("/auth/google")
async def google_login(request: Request):
    google = oauth.create_client("google")

    if google is None:
        raise HTTPException(
            503,
            "Google Login is not configured. "
            "Check GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )

    redirect_uri = str(
        request.url_for("google_callback")
    )

    return await google.authorize_redirect(
        request,
        redirect_uri,
        prompt="select_account",
    )


@app.get("/auth/google/callback")
async def google_callback(request: Request):
    google = oauth.create_client("google")

    if google is None:
        raise HTTPException(
            503,
            "Google Login is not configured",
        )

    try:
        # Authlib validates OAuth state and exchanges the code.
        # For OpenID Connect it also validates the ID token.
        token = await google.authorize_access_token(request)

    except OAuthError as exc:
        print(
            "Google OAuth error:",
            type(exc).__name__,
            flush=True,
        )
        raise HTTPException(
            401,
            "Google authentication failed. Please try again.",
        )

    except Exception as exc:
        print(
            "Google callback error:",
            type(exc).__name__,
            flush=True,
        )
        raise HTTPException(
            502,
            "Could not complete Google authentication",
        )

    profile = token.get("userinfo")

    if not profile:
        raise HTTPException(
            401,
            "Google identity could not be verified",
        )

    if profile.get("email_verified") is not True:
        raise HTTPException(
            403,
            "Google email is not verified",
        )

    google_subject = str(
        profile.get("sub") or ""
    )

    email = str(
        profile.get("email") or ""
    ).strip().lower()

    name = str(
        profile.get("name") or email.split("@")[0]
    ).strip()[:80]

    if (
        not google_subject
        or not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            email,
        )
    ):
        raise HTTPException(
            401,
            "Google did not provide a valid account",
        )

    with conn() as c:
        row = c.execute(
            """
            SELECT id, name, email
            FROM users
            WHERE google_subject = ?
            """,
            (google_subject,),
        ).fetchone()

        if row is None:
            existing = c.execute(
                """
                SELECT id
                FROM users
                WHERE email = ?
                """,
                (email,),
            ).fetchone()

            if existing:
                raise HTTPException(
                    409,
                    "This email already has a password account. "
                    "Please sign in with email and password. "
                    "Automatic account linking is disabled.",
                )

            salt = secrets.token_hex(16)

            random_password_hash = password_hash(
                secrets.token_urlsafe(48),
                salt,
            )

            try:
                cursor = c.execute(
                    """
                    INSERT INTO users (
                        name,
                        email,
                        salt,
                        pw_hash,
                        created_at,
                        google_subject
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        email,
                        salt,
                        random_password_hash,
                        now(),
                        google_subject,
                    ),
                )

                uid = cursor.lastrowid

            except sqlite3.IntegrityError:
                raise HTTPException(
                    409,
                    "Account conflict. Please contact support.",
                )
        else:
            uid = row["id"]

    response = RedirectResponse(
        url="/",
        status_code=303,
    )

    response.set_cookie(
        key="aqirion_session",
        value=signer.dumps(str(uid)),
        httponly=True,
        samesite="lax",
        secure=SECURE_COOKIES,
        max_age=604800,
        path="/",
    )

    return response


# ============================================================
# DOCUMENTS
# ============================================================

@app.get("/api/documents")
def documents(request: Request):
    u = user(request)

    with conn() as c:
        rows = c.execute(
            """
            SELECT
                id,
                name,
                created_at,
                length(content) AS characters
            FROM documents
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (u["id"],),
        ).fetchall()

    return [dict(row) for row in rows]


@app.post("/api/documents")
async def upload(
    request: Request,
    file: UploadFile = File(...),
):
    csrf_check(request)
    u = user(request)

    filename = Path(
        file.filename or "document"
    ).name[:160]

    ext = Path(filename).suffix.lower()

    if ext not in {".txt", ".md", ".pdf", ".docx"}:
        raise HTTPException(
            400,
            "Supported: TXT, MD, PDF, DOCX",
        )

    raw = await file.read(5_000_001)

    if len(raw) > 5_000_000:
        raise HTTPException(
            413,
            "Maximum file size is 5 MB",
        )

    try:
        if ext in {".txt", ".md"}:
            content = raw.decode("utf-8-sig")

        elif ext == ".pdf":
            reader = PdfReader(io.BytesIO(raw))

            content = "\n".join(
                page.extract_text() or ""
                for page in reader.pages[:100]
            )

        else:
            doc = Document(io.BytesIO(raw))

            content = "\n".join(
                paragraph.text
                for paragraph in doc.paragraphs
            )

    except Exception:
        raise HTTPException(
            400,
            "Could not extract text from file",
        )

    if not content.strip():
        raise HTTPException(
            400,
            "No extractable text found. "
            "Scanned PDFs need OCR.",
        )

    if len(content) > 500_000:
        raise HTTPException(
            413,
            "Extracted text exceeds 500,000 characters",
        )

    with conn() as c:
        count = c.execute(
            """
            SELECT count(*)
            FROM documents
            WHERE user_id = ?
            """,
            (u["id"],),
        ).fetchone()[0]

        if count >= 100:
            raise HTTPException(
                400,
                "Document limit reached (100)",
            )

        cursor = c.execute(
            """
            INSERT INTO documents (
                user_id,
                name,
                content,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                u["id"],
                filename,
                content,
                now(),
            ),
        )

        doc_id = cursor.lastrowid

    return {
        "id": doc_id,
        "name": filename,
        "characters": len(content),
    }


@app.delete("/api/documents/{doc_id}")
def delete_document(
    doc_id: int,
    request: Request,
):
    csrf_check(request)
    u = user(request)

    with conn() as c:
        c.execute(
            """
            DELETE FROM documents
            WHERE id = ? AND user_id = ?
            """,
            (doc_id, u["id"]),
        )

    return {"ok": True}


# ============================================================
# GEMINI AI RESEARCH
# ============================================================

@app.post("/api/tasks")
def create_task(
    body: Query,
    request: Request,
):
    csrf_check(request)
    u = user(request)

    with conn() as c:
        rows = c.execute(
            """
            SELECT id, name, content
            FROM documents
            WHERE user_id = ?
            """,
            (u["id"],),
        ).fetchall()

    docs = [
        {
            "id": row["id"],
            "name": row["name"],
            "text": row["content"],
        }
        for row in rows
    ]

    evidence = retrieve(
        body.question,
        docs,
    )

    try:
        answer = generate_ai_answer(
            body.question,
            evidence,
        )

    except Exception as exc:
        print(
            "Gemini generation failed:",
            type(exc).__name__,
            str(exc),
            flush=True,
        )

        raise HTTPException(
            503,
            "AI service is temporarily unavailable. "
            "Check Gemini API configuration and quota.",
        )

    result = {
        "status": (
            "evidence_found"
            if evidence
            else "general_answer"
        ),
        "summary": answer,
        "evidence": evidence,
        "steps": [
            {
                "agent": "Research",
                "status": "complete",
                "detail": (
                    f"Retrieved {len(evidence)} relevant "
                    "passages from uploaded documents"
                ),
            },
            {
                "agent": "Analysis",
                "status": "complete",
                "detail": (
                    "Generated a natural-language AI answer"
                ),
            },
            {
                "agent": "Verification",
                "status": "complete",
                "detail": (
                    "Uploaded sources are shown for review; "
                    "AI claims are not independently fact-checked"
                ),
            },
            {
                "agent": "Report",
                "status": "complete",
                "detail": (
                    "Prepared the AI research result"
                ),
            },
        ],
    }

    created_at = now()

    with conn() as c:
        cursor = c.execute(
            """
            INSERT INTO tasks (
                user_id,
                question,
                result,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                u["id"],
                body.question,
                json.dumps(result),
                created_at,
            ),
        )

        task_id = cursor.lastrowid

    return {
        "id": task_id,
        "question": body.question,
        "created_at": created_at,
        **result,
    }


# ============================================================
# RESEARCH HISTORY
# ============================================================

@app.get("/api/tasks")
def tasks(request: Request):
    u = user(request)

    with conn() as c:
        rows = c.execute(
            """
            SELECT id, question, result, created_at
            FROM tasks
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 100
            """,
            (u["id"],),
        ).fetchall()

    output = []

    for row in rows:
        data = json.loads(row["result"])

        output.append(
            {
                "id": row["id"],
                "question": row["question"],
                "status": data.get(
                    "status",
                    "complete",
                ),
                "created_at": row["created_at"],
            }
        )

    return output


@app.get("/api/tasks/{task_id}")
def get_task(
    task_id: int,
    request: Request,
):
    u = user(request)

    with conn() as c:
        row = c.execute(
            """
            SELECT *
            FROM tasks
            WHERE id = ? AND user_id = ?
            """,
            (task_id, u["id"]),
        ).fetchone()

    if not row:
        raise HTTPException(
            404,
            "Task not found",
        )

    return {
        "id": row["id"],
        "question": row["question"],
        "created_at": row["created_at"],
        **json.loads(row["result"]),
    }


# ============================================================
# PDF REPORT
# ============================================================

@app.get("/api/tasks/{task_id}/report.pdf")
def report(
    task_id: int,
    request: Request,
):
    data = get_task(
        task_id,
        request,
    )

    output = io.BytesIO()

    pdf = SimpleDocTemplate(
        output,
        pagesize=(595, 842),
        leftMargin=45,
        rightMargin=45,
    )

    styles = getSampleStyleSheet()

    story = [
        Paragraph(
            "AQIRION AI | Research Report",
            styles["Title"],
        ),
        Spacer(1, 16),
        Paragraph(
            "Question: "
            + escape(data["question"]),
            styles["Heading2"],
        ),
        Spacer(1, 12),
        Paragraph(
            "Status: "
            + escape(
                data["status"]
                .replace("_", " ")
                .title()
            ),
            styles["Normal"],
        ),
        Spacer(1, 16),
    ]

    for paragraph in data["summary"].split("\n\n"):
        story.append(
            Paragraph(
                escape(paragraph).replace(
                    "\n",
                    "<br/>",
                ),
                styles["BodyText"],
            )
        )

        story.append(
            Spacer(1, 10)
        )

    story.append(
        Paragraph(
            "Retrieved evidence",
            styles["Heading2"],
        )
    )

    for item in data.get("evidence", []):
        story.append(
            Paragraph(
                escape(
                    str(item.get("source", "Document"))
                ),
                styles["Heading3"],
            )
        )

        story.append(
            Paragraph(
                escape(
                    str(item.get("text", ""))[:1200]
                ),
                styles["BodyText"],
            )
        )

        story.append(
            Spacer(1, 10)
        )

    story.append(
        Paragraph(
            (
                "Method: TF-IDF document retrieval "
                "with Gemini-generated answers. "
                "AI-generated claims are not "
                "independently fact-checked."
            ),
            styles["Italic"],
        )
    )

    pdf.build(story)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="aqirion-report-{task_id}.pdf"'
            )
        },
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app": "AQIRION AI",
        "version": "1.3.0",
    }
