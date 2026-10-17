import os, json, sqlite3, hashlib, hmac, secrets, io, re
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pypdf import PdfReader
from docx import Document
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted
from reportlab.lib.styles import getSampleStyleSheet
from xml.sax.saxutils import escape
from engine import analyze

BASE=Path(__file__).resolve().parent
DB=Path(os.getenv('AQIRION_DB',str(BASE/'aqirion.db')))
SECRET=os.getenv('AQIRION_SECRET','')
if not SECRET:
    SECRET=secrets.token_urlsafe(48)
    print('NOTICE: AQIRION_SECRET not set; sessions reset on restart. Set a persistent secret before deployment.')
signer=URLSafeTimedSerializer(SECRET,salt='aqirion-session-v1')
app=FastAPI(title='AQIRION AI',version='1.0.0')
app.mount('/static',StaticFiles(directory=BASE/'static'),name='static')

@contextmanager
def conn():
    DB.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    try:
        yield c
        c.commit()
    finally:c.close()

def init_db():
    with conn() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, pw_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, question TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL);''')
init_db()

def now():return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
def password_hash(password,salt):return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),310000).hex()
def user(request):
    cookie=request.cookies.get('aqirion_session')
    if not cookie:raise HTTPException(401,'Please sign in')
    try:uid=int(signer.loads(cookie,max_age=60*60*24*7))
    except (BadSignature,SignatureExpired,ValueError):raise HTTPException(401,'Session expired')
    with conn() as c: row=c.execute('SELECT id,name,email FROM users WHERE id=?',(uid,)).fetchone()
    if not row:raise HTTPException(401,'Account not found')
    return dict(row)

def csrf_check(request):
    origin=request.headers.get('origin')
    if origin:
        from urllib.parse import urlsplit
        parsed=urlsplit(origin)
        host=request.headers.get('host','')
        if parsed.netloc!=host:raise HTTPException(403,'Origin mismatch')

class Auth(BaseModel):
    name:str=''
    email:str
    password:str
class Query(BaseModel):
    question:str=Field(min_length=3,max_length=1500)

@app.get('/')
def home():return FileResponse(BASE/'static'/'index.html')
@app.get('/api/me')
def me(request:Request):return user(request)
@app.post('/api/signup')
def signup(body:Auth,request:Request):
    csrf_check(request)
    name=body.name.strip();email=body.email.strip().lower()
    if len(name)<2 or len(name)>80 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email) or len(body.password)<10 or len(body.password)>256:
        raise HTTPException(400,'Use a valid name/email and a password of 10+ characters')
    salt=secrets.token_hex(16)
    try:
        with conn() as c:
            cur=c.execute('INSERT INTO users(name,email,salt,pw_hash,created_at) VALUES(?,?,?,?,?)',(name,email,salt,password_hash(body.password,salt),now()))
            uid=cur.lastrowid
    except sqlite3.IntegrityError:raise HTTPException(409,'Email already registered')
    return session_response(uid,name,email)

def session_response(uid,name,email):
    res=JSONResponse({'id':uid,'name':name,'email':email})
    res.set_cookie('aqirion_session',signer.dumps(str(uid)),httponly=True,samesite='lax',secure=os.getenv('AQIRION_SECURE_COOKIES','false').lower()=='true',max_age=604800,path='/')
    return res

@app.post('/api/login')
def login(body:Auth,request:Request):
    csrf_check(request)
    with conn() as c: row=c.execute('SELECT * FROM users WHERE email=?',(body.email.strip().lower(),)).fetchone()
    salt=row['salt'] if row else '00'*16
    digest=password_hash(body.password,salt)
    if not row or not hmac.compare_digest(digest,row['pw_hash']):raise HTTPException(401,'Invalid email or password')
    return session_response(row['id'],row['name'],row['email'])
@app.post('/api/logout')
def logout(request:Request):
    csrf_check(request)
    res=JSONResponse({'ok':True});res.delete_cookie('aqirion_session',path='/');return res

@app.get('/api/documents')
def documents(request:Request):
    u=user(request)
    with conn() as c:rows=c.execute('SELECT id,name,created_at,length(content) AS characters FROM documents WHERE user_id=? ORDER BY id DESC',(u['id'],)).fetchall()
    return [dict(x) for x in rows]

@app.post('/api/documents')
async def upload(request:Request,file:UploadFile=File(...)):
    csrf_check(request);u=user(request)
    filename=Path(file.filename or 'document').name[:160]
    ext=Path(filename).suffix.lower()
    if ext not in {'.txt','.md','.pdf','.docx'}:raise HTTPException(400,'Supported: TXT, MD, PDF, DOCX')
    raw=await file.read(5_000_001)
    if len(raw)>5_000_000:raise HTTPException(413,'Maximum file size is 5 MB')
    try:
        if ext in {'.txt','.md'}:content=raw.decode('utf-8-sig')
        elif ext=='.pdf':content='\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(raw)).pages[:100])
        else:content='\n'.join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
    except Exception:raise HTTPException(400,'Could not extract text from file')
    if not content.strip():raise HTTPException(400,'No extractable text found; scanned PDFs need OCR')
    if len(content)>500_000:raise HTTPException(413,'Extracted text exceeds 500,000 characters')
    with conn() as c:
        count=c.execute('SELECT count(*) FROM documents WHERE user_id=?',(u['id'],)).fetchone()[0]
        if count>=100:raise HTTPException(400,'Document limit reached (100)')
        cur=c.execute('INSERT INTO documents(user_id,name,content,created_at) VALUES(?,?,?,?)',(u['id'],filename,content,now()))
    return {'id':cur.lastrowid,'name':filename,'characters':len(content)}

@app.delete('/api/documents/{doc_id}')
def delete_document(doc_id:int,request:Request):
    csrf_check(request);u=user(request)
    with conn() as c:c.execute('DELETE FROM documents WHERE id=? AND user_id=?',(doc_id,u['id']))
    return {'ok':True}

@app.post('/api/tasks')
def create_task(body:Query,request:Request):
    csrf_check(request);u=user(request)
    with conn() as c:
        rows=c.execute('SELECT id,name,content FROM documents WHERE user_id=?',(u['id'],)).fetchall()
        docs=[{'id':r['id'],'name':r['name'],'text':r['content']} for r in rows]
        result=analyze(body.question,docs)
        cur=c.execute('INSERT INTO tasks(user_id,question,result,created_at) VALUES(?,?,?,?)',(u['id'],body.question,json.dumps(result),now()))
        return {'id':cur.lastrowid,'question':body.question,'created_at':now(),**result}

@app.get('/api/tasks')
def tasks(request:Request):
    u=user(request)
    with conn() as c:rows=c.execute('SELECT id,question,result,created_at FROM tasks WHERE user_id=? ORDER BY id DESC LIMIT 100',(u['id'],)).fetchall()
    return [{'id':r['id'],'question':r['question'],'status':json.loads(r['result'])['status'],'created_at':r['created_at']} for r in rows]

@app.get('/api/tasks/{task_id}')
def get_task(task_id:int,request:Request):
    u=user(request)
    with conn() as c:r=c.execute('SELECT * FROM tasks WHERE id=? AND user_id=?',(task_id,u['id'])).fetchone()
    if not r:raise HTTPException(404,'Task not found')
    return {'id':r['id'],'question':r['question'],'created_at':r['created_at'],**json.loads(r['result'])}

@app.get('/api/tasks/{task_id}/report.pdf')
def report(task_id:int,request:Request):
    data=get_task(task_id,request)
    output=io.BytesIO();pdf=SimpleDocTemplate(output,pagesize=(595,842),leftMargin=45,rightMargin=45)
    st=getSampleStyleSheet();story=[Paragraph('AQIRION AI | Research Report',st['Title']),Spacer(1,16),Paragraph('Question: '+escape(data['question']),st['Heading2']),Spacer(1,12),Paragraph('Status: '+escape(data['status'].replace('_',' ').title()),st['Normal']),Spacer(1,16)]
    for para in data['summary'].split('\n\n'):story.append(Paragraph(escape(para).replace('\n','<br/>'),st['BodyText']));story.append(Spacer(1,10))
    story.append(Paragraph('Retrieved evidence',st['Heading2']))
    for e in data['evidence']:
        story.append(Paragraph(escape(e['source']),st['Heading3']))
        story.append(Paragraph(escape(e['text'][:1200]),st['BodyText']));story.append(Spacer(1,10))
    story.append(Paragraph('Method: Offline keyword/TF-IDF evidence retrieval. Sources are user-uploaded and are not independently fact-checked.',st['Italic']))
    pdf.build(story);output.seek(0)
    return StreamingResponse(output,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="aqirion-report-{task_id}.pdf"'})

@app.get('/api/health')
def health():return {'status':'ok','app':'AQIRION AI'}
