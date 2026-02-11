from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
from backend.db import init_db, get_conn
from backend.security import verify_password, hash_password
import json 
from datetime import datetime
from backend.feedback_pipeline import generate_feedback
from fastapi import UploadFile, File
import os, secrets
import hashlib
from datetime import timedelta
import smtplib
from email.mime.text import MIMEText
# password reset rate limit to prevent abuse of passowrd resetting
RESET_RATE_LIMIT_SECONDS = 20

def _reset_rate_limit(request: Request):
    last = request.session.get("reset_last_ts")
    now = datetime.utcnow().timestamp()
    if last and (now - last) < RESET_RATE_LIMIT_SECONDS:
        raise HTTPException(status_code=429, detail="Too many requests. Try again shortly.")
    request.session["reset_last_ts"] = now

app = FastAPI()
init_db()
# --- Paths ---
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"

UPLOAD_DIR = Path(__file__).parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# NOTE: for IPD prototype this is fine. 
app.add_middleware(SessionMiddleware, secret_key="dev-secret-change-me")

# --- Static files ---
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# --- Pages ---
@app.get("/", response_class=HTMLResponse)
def home():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        return "<h1>Error</h1><p>frontend/index.html not found.</p>"
    return index_file.read_text(encoding="utf-8")


@app.get("/login", response_class=HTMLResponse)
def login_page():
    login_file = FRONTEND_DIR / "login.html"
    if not login_file.exists():
        return "<h1>Error</h1><p>frontend/login.html not found.</p>"
    return login_file.read_text(encoding="utf-8")

@app.get("/reset", response_class=HTMLResponse)
def reset_page():
    reset_file = FRONTEND_DIR / "reset.html"
    if not reset_file.exists():
        return "<h1>Error</h1><p>frontend/reset.html not found.</p>"
    return reset_file.read_text(encoding="utf-8")



# --- Auth API ---
@app.post("/auth/login")
async def login(request: Request):
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT email, password_hash, role FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    request.session["user_email"] = row["email"]
    request.session["role"] = row["role"]

    return {"ok": True, "role": row["role"]}


@app.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}

def require_role(request: Request, allowed_roles: set[str]):
    role = request.session.get("role")
    if role is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    if role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Forbidden")
    return role

@app.get("/auth/change-password", response_class=HTMLResponse)
def change_password_page(request: Request):
    require_role(request, {"student", "teacher", "admin"})
    file = FRONTEND_DIR / "change_password.html"
    if not file.exists():
        return "<h1>Error</h1><p>frontend/change_password.html not found.</p>"
    return file.read_text(encoding="utf-8")


@app.post("/auth/change-password")
async def change_password(request: Request):
    require_role(request, {"student", "teacher", "admin"})
    body = await request.json()

    current_password = body.get("current_password") or ""
    new_password = body.get("new_password") or ""

    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    email = request.session.get("user_email")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE email = ?", (email,))
    row = cur.fetchone()

    if not row or not verify_password(current_password, row["password_hash"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    cur.execute("UPDATE users SET password_hash = ? WHERE email = ?", (hash_password(new_password), email))
    conn.commit()
    conn.close()

    return {"ok": True}

ALLOWED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  
    "application/msword",  
    "application/vnd.ms-powerpoint", 
    "text/plain",
    "image/jpeg",
    "image/jpg",
    "image/png",  
}

MAX_UPLOAD_MB = 15  

RESET_TOKEN_MINUTES = 30

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def send_reset_email(to_email: str, reset_url: str):
    gmail_user = os.getenv("GMAIL_USER")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_password:
        raise ValueError("Missing Gmail environment variables")

    subject = "Password Reset Request"

    html_content = f"""
    <p>Hello,</p>
    <p>You requested a password reset.</p>
    <p>Click below to reset your password:</p>
    <p><a href="{reset_url}">{reset_url}</a></p>
    <p>This link expires in 30 minutes.</p>
    """

    msg = MIMEText(html_content, "html")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.send_message(msg)


@app.post("/auth/forgot")
async def forgot_password(request: Request):
    _reset_rate_limit(request)
    body = await request.json()
    email = (body.get("email") or "").strip().lower()

    
    if not email or "@" not in email:
        return {"ok": True, "reset_url": None}

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT email FROM users WHERE email = ?", (email,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return {"ok": True, "reset_url": None}

    # Create token
    token = secrets.token_urlsafe(32)
    token_hash = sha256_hex(token)

    now = datetime.utcnow()
    expires_at = (now + timedelta(minutes=RESET_TOKEN_MINUTES)).isoformat()

    cur.execute("""
        INSERT INTO password_reset_tokens (user_email, token_hash, expires_at, used_at, created_at)
        VALUES (?, ?, ?, NULL, ?)
    """, (email, token_hash, expires_at, now.isoformat()))
    conn.commit()
    conn.close()

    # returns reset link via email
    base_url = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    reset_url = f"{base_url}/reset?token={token}"
    send_reset_email(email, reset_url)
    return {"ok": True}



@app.post("/auth/reset")
async def reset_password(request: Request):
    body = await request.json()
    token = (body.get("token") or "").strip()
    new_password = body.get("new_password") or ""

    if not token:
        raise HTTPException(status_code=400, detail="Missing token")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    token_hash = sha256_hex(token)
    now = datetime.utcnow()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, user_email, expires_at, used_at
        FROM password_reset_tokens
        WHERE token_hash = ?
        ORDER BY id DESC
        LIMIT 1
    """, (token_hash,))
    t = cur.fetchone()

    if not t:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    if t["used_at"]:
        conn.close()
        raise HTTPException(status_code=400, detail="Token already used")

    expires_at = datetime.fromisoformat(t["expires_at"])
    if now > expires_at:
        conn.close()
        raise HTTPException(status_code=400, detail="Token expired")

    # Update password + mark token used
    pw_hash = hash_password(new_password)

    cur.execute("UPDATE users SET password_hash = ? WHERE email = ?", (pw_hash, t["user_email"]))
    cur.execute("UPDATE password_reset_tokens SET used_at = ? WHERE id = ?", (now.isoformat(), t["id"]))
    conn.commit()
    conn.close()

    return {"ok": True}

@app.post("/api/uploads")
async def upload_file(request: Request, file: UploadFile = File(...)):
    ALLOWED_EXT = {".pdf", ".docx", ".pptx", ".txt", ".png", ".jpg", ".jpeg"}

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"File extension not allowed: {ext}")

    # ...rest of your upload logic...

    role = require_role(request, {"student", "teacher", "admin"})
    email = request.session.get("user_email")

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"File type not allowed: {file.content_type}")

    contents = await file.read()
    size_bytes = len(contents)
    if size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large (max {MAX_UPLOAD_MB}MB)")

    ext = Path(file.filename).suffix.lower()
    stored_name = f"{secrets.token_hex(16)}{ext}"
    save_path = UPLOAD_DIR / stored_name

    with open(save_path, "wb") as f:
        f.write(contents)

    now = datetime.utcnow().isoformat()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO uploads (user_email, role, original_name, stored_name, content_type, size_bytes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (email, role, file.filename, stored_name, file.content_type, size_bytes, now))
    upload_id = cur.lastrowid
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "upload_id": upload_id,
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": size_bytes
    }




@app.get("/auth/me")
def me(request: Request):
    email = request.session.get("user_email")
    role = request.session.get("role")
    if not email or not role:
        raise HTTPException(status_code=401, detail="Not logged in")
    return {"email": email, "role": role}
@app.get("/student", response_class=HTMLResponse)
def student_dashboard(request: Request):
    require_role(request, {"student"})
    file = FRONTEND_DIR / "student.html"
    return file.read_text(encoding="utf-8")


@app.get("/teacher", response_class=HTMLResponse)
def teacher_dashboard(request: Request):
    require_role(request, {"teacher"})
    file = FRONTEND_DIR / "teacher.html"
    return file.read_text(encoding="utf-8")


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    require_role(request, {"admin"})
    file = FRONTEND_DIR / "admin.html"
    return file.read_text(encoding="utf-8")

@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request):
    require_role(request, {"admin"})
    file = FRONTEND_DIR / "admin_users.html"
    return file.read_text(encoding="utf-8")
@app.get("/api/admin/users")
def list_users(request: Request):
    require_role(request, {"admin"})
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT email, role FROM users ORDER BY email ASC")
    rows = cur.fetchall()
    conn.close()
    return {"users": [{"email": r["email"], "role": r["role"]} for r in rows]}


@app.post("/api/admin/users")
async def create_user(request: Request):
    require_role(request, {"admin"})
    body = await request.json()

    email = (body.get("email") or "").strip().lower()
    role = (body.get("role") or "").strip().lower()
    password = body.get("password") or ""

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email is required")
    if role not in {"student", "teacher", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    pw_hash = hash_password(password)

    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)",
            (email, pw_hash, role),
        )
        conn.commit()
        conn.close()
    except Exception:
        raise HTTPException(status_code=400, detail="User already exists or database error")

    return {"ok": True}

# Rubrics & Submissions 

@app.get("/api/rubrics")
def get_rubrics(request: Request):
    # Any logged in user can fetch rubrics
    require_role(request, {"student", "teacher", "admin"})
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, title FROM rubrics ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return {"rubrics": [{"id": r["id"], "title": r["title"]} for r in rows]}




@app.post("/api/submissions")
async def create_submission(request: Request):
    require_role(request, {"student"})
    body = await request.json()

    rubric_id = body.get("rubric_id")
    submission_text = (body.get("submission_text") or "").strip()

    attachment_ids = body.get("attachment_ids") or []
    if not isinstance(attachment_ids, list):
        raise HTTPException(status_code=400, detail="attachment_ids must be a list")

    if not rubric_id:
        raise HTTPException(status_code=400, detail="rubric_id is required")
    if len(submission_text) < 20:
        raise HTTPException(status_code=400, detail="Submission text must be at least 20 characters")

    # Load rubric criteria
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT criteria_json FROM rubrics WHERE id = ?", (rubric_id,))
    r = cur.fetchone()
    if not r:
        conn.close()
        raise HTTPException(status_code=404, detail="Rubric not found")
    criteria = json.loads(r["criteria_json"])

    # Insert submission
    email = request.session.get("user_email")
    now = datetime.utcnow().isoformat()
    cur.execute(
        "INSERT INTO submissions (user_email, rubric_id, submission_text, created_at) VALUES (?, ?, ?, ?)",
        (email, rubric_id, submission_text, now),
    )
    submission_id = cur.lastrowid

    # Link attachments to this submission if any and links to same user
    if attachment_ids:
        placeholders = ",".join(["?"] * len(attachment_ids))
        cur.execute(
            f"""
            UPDATE uploads
            SET submission_id = ?
            WHERE id IN ({placeholders})
              AND user_email = ?
            """,
            (submission_id, *attachment_ids, email),
        )

        if cur.rowcount != len(attachment_ids):
            raise HTTPException(status_code=403, detail="One or more attachments not found / not yours")

    # Generate and store feedback
    rubric_data = {"criteria": criteria}
    feedback = generate_feedback(submission_text, rubric_data)
    cur.execute(
        "INSERT INTO feedback (submission_id, feedback_json, created_at) VALUES (?, ?, ?)",
        (submission_id, json.dumps(feedback), now),
    )

    conn.commit()
    conn.close()

    return {"ok": True, "submission_id": submission_id, "attachment_ids": attachment_ids}


@app.get("/api/submissions/me")
def my_submissions(request: Request):
    require_role(request, {"student"})
    email = request.session.get("user_email")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id, s.created_at, r.title as rubric_title
        FROM submissions s
        JOIN rubrics r ON r.id = s.rubric_id
        WHERE s.user_email = ?
        ORDER BY s.id DESC
    """, (email,))
    rows = cur.fetchall()
    conn.close()

    return {"submissions": [
        {"id": row["id"], "created_at": row["created_at"], "rubric_title": row["rubric_title"]}
        for row in rows
    ]}


@app.get("/api/submissions/{submission_id}")
def get_submission(request: Request, submission_id: int):
    role = require_role(request, {"student", "teacher", "admin"})
    email = request.session.get("user_email")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id, s.user_email, s.submission_text, s.created_at, r.title as rubric_title
        FROM submissions s
        JOIN rubrics r ON r.id = s.rubric_id
        WHERE s.id = ?
    """, (submission_id,))
    s = cur.fetchone()

    if not s:
        conn.close()
        raise HTTPException(status_code=404, detail="Submission not found")

    # Students can only view their own
    if role == "student" and s["user_email"] != email:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")

    cur.execute("SELECT feedback_json FROM feedback WHERE submission_id = ?", (submission_id,))
    f = cur.fetchone()
    conn.close()

    feedback = json.loads(f["feedback_json"]) if f else None

    return {
        "id": s["id"],
        "user_email": s["user_email"],
        "rubric_title": s["rubric_title"],
        "created_at": s["created_at"],
        "submission_text": s["submission_text"],
        "feedback": feedback
    }


@app.get("/api/teacher/submissions")
def teacher_submissions(request: Request):
    require_role(request, {"teacher", "admin"})

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id, s.user_email, s.created_at, r.title as rubric_title
        FROM submissions s
        JOIN rubrics r ON r.id = s.rubric_id
        ORDER BY s.id DESC
    """)
    rows = cur.fetchall()
    conn.close()

    return {"submissions": [
        {"id": row["id"], "user_email": row["user_email"], "created_at": row["created_at"], "rubric_title": row["rubric_title"]}
        for row in rows
    ]}
@app.get("/api/teacher/review/{submission_id}")
def get_teacher_review(request: Request, submission_id: int):
    require_role(request, {"teacher", "admin"})
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT submission_id, flagged, note, updated_at FROM teacher_reviews WHERE submission_id = ?",
        (submission_id,),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return {"submission_id": submission_id, "flagged": 0, "note": "", "updated_at": None}

    return {
        "submission_id": row["submission_id"],
        "flagged": int(row["flagged"] or 0),
        "note": row["note"] or "",
        "updated_at": row["updated_at"],
    }


@app.post("/api/teacher/review/{submission_id}")
async def save_teacher_review(request: Request, submission_id: int):
    require_role(request, {"teacher", "admin"})
    body = await request.json()

    flagged = 1 if body.get("flagged") else 0
    note = (body.get("note") or "").strip()
    if len(note) > 2000:
        raise HTTPException(status_code=400, detail="Note too long (max 2000 chars)")

    now = datetime.utcnow().isoformat()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO teacher_reviews (submission_id, flagged, note, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(submission_id) DO UPDATE SET
          flagged=excluded.flagged,
          note=excluded.note,
          updated_at=excluded.updated_at
    """, (submission_id, flagged, note, now))
    conn.commit()
    conn.close()

    return {"ok": True}



# Admin: Rubrics + Analytics

@app.get("/api/admin/analytics")
def admin_analytics(request: Request):
    require_role(request, {"admin"})
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) as c FROM users")
    users_count = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) as c FROM submissions")
    submissions_count = cur.fetchone()["c"]

    cur.execute("""
        SELECT r.title, COUNT(*) as c
        FROM submissions s
        JOIN rubrics r ON r.id = s.rubric_id
        GROUP BY r.title
        ORDER BY c DESC
        LIMIT 1
    """)
    top = cur.fetchone()
    top_rubric = {"title": top["title"], "count": top["c"]} if top else None

    conn.close()

    return {
        "users_count": users_count,
        "submissions_count": submissions_count,
        "top_rubric": top_rubric
    }


@app.get("/api/admin/rubrics")
def admin_list_rubrics(request: Request):
    require_role(request, {"admin"})
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, title FROM rubrics ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return {"rubrics": [{"id": r["id"], "title": r["title"]} for r in rows]}


@app.post("/api/admin/rubrics")
async def admin_create_rubric(request: Request):
    require_role(request, {"admin"})
    body = await request.json()

    title = (body.get("title") or "").strip()
    criteria = body.get("criteria")  # expects array of objects

    if len(title) < 3:
        raise HTTPException(status_code=400, detail="Title must be at least 3 characters")
    if not isinstance(criteria, list) or len(criteria) < 1:
        raise HTTPException(status_code=400, detail="Criteria must be a non-empty list")

    # basic validation
    cleaned = []
    for c in criteria:
        name = (c.get("name") or "").strip()
        desc = (c.get("description") or "").strip()
        if len(name) < 2 or len(desc) < 3:
            raise HTTPException(status_code=400, detail="Each criterion needs name + description")
        cleaned.append({"name": name, "description": desc})

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO rubrics (title, criteria_json) VALUES (?, ?)",
        (title, json.dumps(cleaned)),
    )
    conn.commit()
    conn.close()

    return {"ok": True}
@app.get("/admin/rubrics", response_class=HTMLResponse)
def admin_rubrics_page(request: Request):
    require_role(request, {"admin"})
    file = FRONTEND_DIR / "admin_rubrics.html"
    return file.read_text(encoding="utf-8")


# Chat CoPilot (Mock pipeline for now, LLM will be added in soon)

def basic_guardrails(message: str) -> str:
    """
    guardrail for prototyp to make it safer for and suited for 
    Later: replace with stronger LLM moderation + policies.
    """
    msg = (message or "").strip()
    if len(msg) == 0:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(msg) > 800:
        raise HTTPException(status_code=400, detail="Message too long (max 800 characters)")

    banned = ["suicide", "self harm", "kill myself", "porn", "nudes"]
    lowered = msg.lower()
    if any(b in lowered for b in banned):
        return "I can’t help with that. Please talk to a trusted adult or teacher. If you are in danger, contact emergency services."

    return msg


def mock_chat_response(mode: str, message: str, context: dict | None = None) -> str:

    attachments = (context or {}).get("attachments") or []
    if attachments:
        names = ", ".join([a["name"] for a in attachments][:3])
        extra = f"\nI also received {len(attachments)} attachment(s): {names}"
    else:
        extra = ""
        if mode == "general":
            return (
            "Here’s some school-safe help:\n"
            f"- Your question: “{message}”\n"
            "- Try breaking it into 1–2 key points.\n"
            "- If you tell me the subject (e.g., business/English/science), I can tailor the explanation.\n"
        )

    if mode == "teacher":
        return (
            "Teacher Copilot (prototype):\n"
            f"- Request: “{message}”\n"
            "Ideas you can try:\n"
            "1) Lesson plan outline (starter, main task, plenary)\n"
            "2) Differentiation: support + stretch prompts\n"
            "3) Misconceptions to watch for + quick checks\n"
            "Reply with subject, year group, and lesson length for a tailored plan."
        )

    # feedback mode
    rubric_title = (context or {}).get("rubric_title", "your rubric")
    return (
        f"Let’s improve your work using {rubric_title}.\n"
        f"Your question: “{message}”\n"
        "Suggestion:\n"
        "- Pick one criterion to improve first.\n"
        "- Add a specific example and explain why it supports your point.\n"
        "- Rewrite one paragraph for clarity, then re-check against the rubric.\n"
    )



@app.post("/api/chat")
async def chat(request: Request):
    role = require_role(request, {"student", "teacher", "admin"})
    body = await request.json()

    attachment_ids = body.get("attachment_ids") or []
    if not isinstance(attachment_ids, list):
        raise HTTPException(status_code=400, detail="attachment_ids must be a list")

    rows = []
    if attachment_ids:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(f"""
            SELECT id, original_name, content_type, stored_name
            FROM uploads
            WHERE id IN ({",".join(["?"]*len(attachment_ids))})
              AND user_email = ?
        """, (*attachment_ids, request.session.get("user_email")))
        rows = cur.fetchall()
        conn.close()

        if len(rows) != len(attachment_ids):
            raise HTTPException(status_code=403, detail="One or more attachments not found / not yours")

    # context always exists now
    context = {}
    if rows:
        context["attachments"] = [
            {"id": r["id"], "name": r["original_name"], "type": r["content_type"], "stored": r["stored_name"]}
            for r in rows
        ]

    mode = (body.get("mode") or "").strip().lower()
    message = basic_guardrails(body.get("message") or "")

    if mode not in {"general", "feedback", "teacher"}:
        raise HTTPException(status_code=400, detail="Invalid mode")

    if mode == "teacher" and role == "student":
        raise HTTPException(status_code=403, detail="Teacher chat is not available for students")

    if mode == "feedback":
        submission_id = body.get("submission_id")
        if not submission_id:
            raise HTTPException(status_code=400, detail="submission_id is required for feedback mode")
        if role != "student":
            raise HTTPException(status_code=403, detail="Feedback mode chat is only available for students")

        email = request.session.get("user_email")
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT s.id, s.user_email, s.submission_text, s.created_at, r.title as rubric_title
            FROM submissions s
            JOIN rubrics r ON r.id = s.rubric_id
            WHERE s.id = ?
        """, (submission_id,))
        s = cur.fetchone()
        if not s:
            conn.close()
            raise HTTPException(status_code=404, detail="Submission not found")
        if s["user_email"] != email:
            conn.close()
            raise HTTPException(status_code=403, detail="Forbidden")

        cur.execute("SELECT feedback_json FROM feedback WHERE submission_id = ?", (submission_id,))
        f = cur.fetchone()
        conn.close()

        feedback = json.loads(f["feedback_json"]) if f else None

        # feedback merged into context for more informed responses
        context.update({
            "rubric_title": s["rubric_title"],
            "submission_text": s["submission_text"],
            "feedback": feedback,
        })

    reply = mock_chat_response(mode, message, context)
    return {"ok": True, "reply": reply}

