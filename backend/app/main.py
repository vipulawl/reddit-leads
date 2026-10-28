from datetime import datetime

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import filters
from .auth import create_token, current_user, hash_password, verify_password
from .config import settings
from .db import SessionLocal, get_db, init_db
from .models import Lead, Project, User
from .onboarding import generate_profile

app = FastAPI(title="reddit-leads")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class ProjectCreate(BaseModel):
    url: str


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    icp: str | None = None
    pain_points: list[str] | None = None
    keywords: list[str] | None = None
    negative_keywords: list[str] | None = None
    subreddits: list[str] | None = None
    similarity_threshold: float | None = Field(None, ge=0, le=1)
    min_score: int | None = Field(None, ge=0, le=100)
    active: bool | None = None


class LeadUpdate(BaseModel):
    status: str = Field(pattern="^(new|replied|skipped)$")


def project_out(p: Project, lead_count: int = 0) -> dict:
    return {
        "id": p.id, "url": p.url, "name": p.name, "description": p.description, "icp": p.icp,
        "pain_points": p.pain_points, "keywords": p.keywords, "negative_keywords": p.negative_keywords,
        "subreddits": p.subreddits, "similarity_threshold": p.similarity_threshold, "min_score": p.min_score,
        "active": p.active, "ready": p.profile_embedding is not None, "lead_count": lead_count,
    }


def lead_out(l: Lead) -> dict:
    return {
        "id": l.id, "kind": l.kind, "subreddit": l.subreddit, "author": l.author, "title": l.title,
        "body": l.body, "permalink": l.permalink, "matched_keywords": l.matched_keywords,
        "similarity": round(l.similarity, 3), "vendor_prob": round(l.vendor_prob, 3), "score": l.score,
        "status": l.status, "posted_at": l.posted_at.isoformat(), "created_at": l.created_at.isoformat(),
    }


def own_project(db: Session, user: User, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "Project not found")
    return p


def refresh_embedding(p: Project):
    p.profile_embedding = filters.embed([p.profile_text()])[0].tolist()


@app.post("/api/auth/signup")
def signup(body: Credentials, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(400, "Email already registered")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return {"token": create_token(user.id), "email": user.email}


@app.post("/api/auth/login")
def login(body: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return {"token": create_token(user.id), "email": user.email}


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"email": user.email}


def build_profile(project_id: int):
    with SessionLocal() as db:
        p = db.get(Project, project_id)
        try:
            prof = generate_profile(p.url)
            p.name = prof["name"] or p.name
            p.description = prof["description"]
            p.icp = prof["icp"]
            p.pain_points = prof["pain_points"]
            p.keywords = prof["keywords"]
            p.negative_keywords = prof["negative_keywords"]
            p.subreddits = prof["subreddits"]
            refresh_embedding(p)
            db.commit()
        except Exception as e:
            db.rollback()
            p = db.get(Project, project_id)
            p.description = f"Setup failed: {e}"
            db.commit()


@app.get("/api/projects")
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)):
    counts = dict(db.execute(
        select(Lead.project_id, func.count()).join(Project)
        .where(Project.user_id == user.id, Lead.score >= Project.min_score, Lead.status == "new")
        .group_by(Lead.project_id)
    ).all())
    return [project_out(p, counts.get(p.id, 0)) for p in user.projects]


@app.post("/api/projects")
def create_project(body: ProjectCreate, tasks: BackgroundTasks, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    url = body.url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    p = Project(user_id=user.id, url=url, name=url.split("//")[-1].split("/")[0])
    db.add(p)
    db.commit()
    tasks.add_task(build_profile, p.id)
    return project_out(p)


@app.post("/api/projects/{project_id}/regenerate")
def regenerate_project(project_id: int, tasks: BackgroundTasks, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    p = own_project(db, user, project_id)
    p.description = ""
    p.profile_embedding = None
    db.commit()
    tasks.add_task(build_profile, p.id)
    return project_out(p)


@app.get("/api/projects/{project_id}")
def get_project(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return project_out(own_project(db, user, project_id))


@app.patch("/api/projects/{project_id}")
def update_project(project_id: int, body: ProjectUpdate, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    p = own_project(db, user, project_id)
    changes = body.model_dump(exclude_none=True)
    for list_field in ("keywords", "negative_keywords"):
        if list_field in changes:
            changes[list_field] = [k.lower().strip() for k in changes[list_field] if k.strip()]
    if "subreddits" in changes:
        changes["subreddits"] = [s.removeprefix("r/").strip() for s in changes["subreddits"] if s.strip()]
    for k, v in changes.items():
        setattr(p, k, v)
    if {"name", "description", "icp", "pain_points"} & changes.keys():
        refresh_embedding(p)
    db.commit()
    return project_out(p)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = own_project(db, user, project_id)
    db.query(Lead).filter(Lead.project_id == p.id).delete()
    db.delete(p)
    db.commit()
    return {"ok": True}


@app.get("/api/projects/{project_id}/leads")
def list_leads(project_id: int, status: str = "new", min_score: int | None = None, since: datetime | None = None,
               limit: int = 100, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = own_project(db, user, project_id)
    q = select(Lead).where(Lead.project_id == p.id, Lead.score >= (p.min_score if min_score is None else min_score))
    if status != "all":
        q = q.where(Lead.status == status)
    if since:
        q = q.where(Lead.created_at > since)
    return [lead_out(l) for l in db.scalars(q.order_by(Lead.created_at.desc()).limit(min(limit, 500)))]


@app.patch("/api/leads/{lead_id}")
def update_lead(lead_id: int, body: LeadUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    own_project(db, user, lead.project_id)
    lead.status = body.status
    db.commit()
    return lead_out(lead)
