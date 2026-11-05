import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import func
from sqlalchemy.orm import Session

from dotenv import load_dotenv

load_dotenv()

from actions import create_task
from agents import (
    Analysis,
    Draft,
    Priority,
    analyze_agent,
    draft_agent,
    prioritize_agent,
)
from database import (
    Base,
    EmailVerification,
    LoginSession,
    ScanRecord,
    ScanRun,
    SessionLocal,
    User,
    engine,
)
from detect import run_detection
from notify import send_email_alert, send_verification_email
from sf_client import get_sf


logger = logging.getLogger("dealwatch.api")
SESSION_COOKIE = "dealwatch_session"
SESSION_HOURS = 12
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax").lower()
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
TEAM_TIMEZONE = os.getenv("TEAM_TIMEZONE", "Asia/Manila")
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "true").lower() == "true"
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.getenv("RATE_LIMIT_STORAGE_URI", "memory://"),
)
scheduler = None
_scan_lock = threading.Lock()

if COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    raise RuntimeError("COOKIE_SAMESITE must be lax, strict, or none.")
if COOKIE_SAMESITE == "none" and not COOKIE_SECURE:
    raise RuntimeError("COOKIE_SECURE=true is required when COOKIE_SAMESITE=none.")


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=256)


class BootstrapRequest(RegisterRequest):
    setup_secret: str = Field(min_length=1, max_length=512)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)


class ResendVerificationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class UserDecision(BaseModel):
    status: Literal["approved", "rejected"]
    role: Literal["rep", "manager"] = "rep"


class ApproveRequest(BaseModel):
    task_subject: str = Field(min_length=1, max_length=255)
    task_description: str = Field(min_length=1, max_length=32000)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _normalized_email(email: str) -> str:
    value = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return value


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    password_hash = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=64,
        maxmem=64 * 1024 * 1024,
    )
    return f"scrypt${salt.hex()}${password_hash.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt_hex, hash_hex = stored_hash.split("$", 2)
        if algorithm != "scrypt":
            return False
        expected = bytes.fromhex(hash_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=2**14,
            r=8,
            p=1,
            dklen=len(expected),
            maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _public_user(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "status": user.status,
    }


def _issue_session(db: Session, user: User, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    db.add(LoginSession(token_hash=token_hash, user_id=user.id, expires_at=expires_at))
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_HOURS * 60 * 60,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Please sign in.")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = db.get(LoginSession, token_hash)
    if not session:
        raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.")

    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.")

    user = db.get(User, session.user_id)
    if not user or user.status != "approved":
        raise HTTPException(status_code=403, detail="This account is not approved.")
    return user


def require_manager(user: User = Depends(get_current_user)) -> User:
    if user.role != "manager":
        raise HTTPException(status_code=403, detail="Manager access is required.")
    return user


def _scan_result(scan: ScanRun, records: list[ScanRecord]) -> dict:
    return {
        "id": scan.id,
        "status": scan.status,
        "started_at": scan.started_at.isoformat(),
        "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
        "error_message": scan.error_message,
        "record_count": len(records),
        "records": [_record_result(record) for record in records],
    }


def _record_result(record: ScanRecord) -> dict:
    return {
        "item_id": record.id,
        "salesforce_id": record.salesforce_id,
        "type": record.record_type,
        "name": record.name,
        "owner_id": record.owner_id,
        "owner_name": record.owner_name,
        "owner_email": record.owner_email,
        "payload": record.payload,
        "analysis": record.analysis,
        "priority": record.priority,
        "draft": record.draft,
        "action_status": record.action_status,
        "task_id": record.task_id,
        "email_status": record.email_status,
        "action_error": record.action_error,
    }


def _can_view_record(user: User, record: ScanRecord) -> bool:
    return user.role == "manager" or (
        record.owner_email is not None
        and record.owner_email.strip().lower() == user.email.strip().lower()
    )


def _visible_records(db: Session, scan_id: str, user: User) -> list[ScanRecord]:
    records = (
        db.query(ScanRecord)
        .filter(ScanRecord.scan_id == scan_id)
        .all()
    )
    visible = [record for record in records if _can_view_record(user, record)]
    visible.sort(key=lambda record: record.priority.get("rank", 0))
    return visible


def _run_scan_once() -> str:
    scan_id = str(uuid.uuid4())
    with SessionLocal() as db:
        scan = ScanRun(id=scan_id, status="running")
        db.add(scan)
        db.commit()
        db.refresh(scan)
        try:
            records = run_detection()
            if records:
                analyses = analyze_agent(records)
                priorities = prioritize_agent(records, analyses)
                drafts = draft_agent(records, analyses)

                expected_ids = {record["id"] for record in records}
                analysis_by_id = {item.id: item for item in analyses}
                priority_by_id = {item.id: item for item in priorities}
                draft_by_id = {item.id: item for item in drafts}
                if (
                    len(analysis_by_id) != len(analyses)
                    or len(priority_by_id) != len(priorities)
                    or len(draft_by_id) != len(drafts)
                    or len(expected_ids) != len(records)
                    or set(analysis_by_id) != expected_ids
                    or set(priority_by_id) != expected_ids
                    or set(draft_by_id) != expected_ids
                ):
                    raise RuntimeError("AI results did not contain exactly one result per Salesforce record.")
                if sorted(item.rank for item in priorities) != list(range(1, len(records) + 1)):
                    raise RuntimeError("AI priorities must be a complete sequence from 1 to the record count.")

                for record in records:
                    db.add(
                        ScanRecord(
                            id=str(uuid.uuid4()),
                            scan_id=scan.id,
                            salesforce_id=record["id"],
                            record_type=record["type"],
                            name=record["name"],
                            owner_id=record.get("owner_id"),
                            owner_name=record.get("owner_name"),
                            owner_email=record.get("owner_email"),
                            payload=record,
                            analysis=analysis_by_id[record["id"]].model_dump(),
                            priority=priority_by_id[record["id"]].model_dump(),
                            draft=draft_by_id[record["id"]].model_dump(),
                        )
                    )

            scan.status = "completed"
            scan.finished_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("Scan %s completed with %s record(s).", scan.id, len(records))
        except Exception as exc:
            db.rollback()
            scan = db.get(ScanRun, scan_id)
            if scan:
                scan.status = "failed"
                scan.error_message = str(exc)[:1000]
                scan.finished_at = datetime.now(timezone.utc)
                db.commit()
            logger.exception("Scan %s failed.", scan_id)
    return scan_id


def _run_scan() -> str:
    if not _scan_lock.acquire(blocking=False):
        raise RuntimeError("A scan is already running.")
    try:
        return _run_scan_once()
    finally:
        _scan_lock.release()


def _start_scheduler() -> BackgroundScheduler | None:
    if not ENABLE_SCHEDULER:
        logger.info("Scheduled scans are disabled by configuration.")
        return None

    timezone_info = ZoneInfo(TEAM_TIMEZONE)
    scan_scheduler = BackgroundScheduler(timezone=timezone_info)
    scan_scheduler.add_job(
        _run_scan,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=0, timezone=timezone_info),
        id="weekday-salesforce-scan",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scan_scheduler.start()
    logger.info("Weekday scans scheduled for 9:00 AM %s.", TEAM_TIMEZONE)
    return scan_scheduler


def _send_verification_link(db: Session, user: User) -> None:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    db.query(EmailVerification).filter(EmailVerification.user_id == user.id).delete()
    db.add(
        EmailVerification(
            token_hash=token_hash,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
    )
    db.commit()
    verification_url = f"{FRONTEND_ORIGIN}/?verify={token}"
    try:
        if not send_verification_email(get_sf(), user.email, verification_url):
            raise RuntimeError("Salesforce did not confirm the verification email.")
    except Exception as exc:
        logger.exception("Could not send an email verification link.")
        raise HTTPException(
            status_code=502,
            detail="Could not send the verification email. Use the resend option after checking the server settings.",
        ) from exc


@asynccontextmanager
async def lifespan(_: FastAPI):
    global scheduler
    Base.metadata.create_all(bind=engine)
    scheduler = _start_scheduler()
    try:
        yield
    finally:
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler = None


app = FastAPI(title="DealWatch API", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "scheduler_running": bool(scheduler and scheduler.running),
        "scan_timezone": TEAM_TIMEZONE,
    }


@app.get("/api/auth/bootstrap-status")
def bootstrap_status(db: Session = Depends(get_db)):
    manager_exists = (
        db.query(User)
        .filter(User.role == "manager", User.status == "approved")
        .first()
        is not None
    )
    return {"setup_required": not manager_exists}


@app.post("/api/auth/bootstrap-manager", status_code=201)
@limiter.limit("5/hour")
def bootstrap_manager(
    request: Request,
    body: BootstrapRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    setup_secret = os.getenv("DEALWATCH_SETUP_SECRET")
    if not setup_secret:
        raise HTTPException(status_code=503, detail="Initial manager setup is not configured.")
    if not hmac.compare_digest(body.setup_secret, setup_secret):
        raise HTTPException(status_code=403, detail="Setup secret is incorrect.")
    manager_exists = (
        db.query(User)
        .filter(User.role == "manager", User.status == "approved")
        .first()
        is not None
    )
    if manager_exists:
        raise HTTPException(status_code=409, detail="The initial manager has already been created.")

    email = _normalized_email(body.email)
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(
        id=str(uuid.uuid4()),
        name=body.name.strip(),
        email=email,
        password_hash=_hash_password(body.password),
        role="manager",
        status="approved",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    _issue_session(db, user, response)
    return _public_user(user)


@app.post("/api/auth/register", status_code=201)
@limiter.limit("3/hour")
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    email = _normalized_email(body.email)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Enter your name.")
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(
        id=str(uuid.uuid4()),
        name=name,
        email=email,
        password_hash=_hash_password(body.password),
        role="rep",
        status="pending",
    )
    db.add(user)
    db.commit()
    _send_verification_link(db, user)
    return {
        "status": "verification_required",
        "message": "Check your email for a verification link. A manager can approve your account after verification.",
    }


@app.post("/api/auth/resend-verification")
@limiter.limit("3/hour")
def resend_verification(
    request: Request,
    body: ResendVerificationRequest,
    db: Session = Depends(get_db),
):
    email = _normalized_email(body.email)
    user = (
        db.query(User)
        .filter(func.lower(User.email) == email)
        .first()
    )
    if user and user.status == "pending" and not user.email_verified:
        _send_verification_link(db, user)
    return {
        "message": "If that address has an unverified DealWatch account, a new link has been sent.",
    }


@app.post("/api/auth/verify-email")
def verify_email(body: VerifyEmailRequest, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    verification = db.get(EmailVerification, token_hash)
    if not verification:
        raise HTTPException(status_code=400, detail="This verification link is invalid or has already been used.")
    if verification.used_at:
        return {"status": "verified", "message": "Your email is already verified. A manager must still approve your account."}
    expires_at = verification.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        db.delete(verification)
        db.commit()
        raise HTTPException(status_code=410, detail="This verification link has expired. Request a new one.")
    user = db.get(User, verification.user_id)
    if not user:
        db.delete(verification)
        db.commit()
        raise HTTPException(status_code=404, detail="The account for this link no longer exists.")
    user.email_verified = True
    verification.used_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "verified", "message": "Email verified. A manager must still approve your account."}


@app.post("/api/auth/login")
@limiter.limit("10/minute")
def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    email = _normalized_email(body.email)
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user or not _verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Verify your email address before signing in.")
    if user.status == "pending":
        raise HTTPException(status_code=403, detail="Your account is waiting for manager approval.")
    if user.status != "approved":
        raise HTTPException(status_code=403, detail="This account is not active.")
    _issue_session(db, user, response)
    return _public_user(user)


@app.post("/api/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        session = db.get(LoginSession, token_hash)
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
    )


@app.get("/api/auth/me")
def current_user(user: User = Depends(get_current_user)):
    return _public_user(user)


@app.get("/api/admin/registrations")
def pending_registrations(
    db: Session = Depends(get_db),
    _: User = Depends(require_manager),
):
    users = (
        db.query(User)
        .filter(User.status == "pending", User.email_verified.is_(True))
        .order_by(User.created_at.asc())
        .all()
    )
    return [_public_user(user) for user in users]


@app.patch("/api/admin/users/{user_id}")
def decide_user(
    user_id: str,
    body: UserDecision,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Account not found.")
    if body.status == "approved" and not user.email_verified:
        raise HTTPException(status_code=409, detail="The user must verify their email before approval.")
    if user.role == "manager" and user.status == "approved" and (
        body.role != "manager" or body.status != "approved"
    ):
        remaining_managers = (
            db.query(User)
            .filter(
                User.role == "manager",
                User.status == "approved",
                User.id != user.id,
            )
            .count()
        )
        if remaining_managers == 0:
            raise HTTPException(status_code=409, detail="At least one approved manager is required.")
    user.status = body.status
    user.role = body.role
    db.commit()
    return _public_user(user)


@app.get("/api/scans/latest")
def latest_scan(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    scan = db.query(ScanRun).order_by(ScanRun.started_at.desc()).first()
    if not scan:
        return {
            "scan": None,
            "records": [],
            "schedule": {"frequency": "weekdays", "time": "09:00", "timezone": TEAM_TIMEZONE},
        }
    records = _visible_records(db, scan.id, user)
    return {
        "scan": {
            "id": scan.id,
            "status": scan.status,
            "started_at": scan.started_at.isoformat(),
            "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
            "error_message": scan.error_message,
            "record_count": len(records),
        },
        "records": [_record_result(record) for record in records],
        "schedule": {"frequency": "weekdays", "time": "09:00", "timezone": TEAM_TIMEZONE},
    }


@app.post("/api/scans/run")
@limiter.limit("3/hour")
def run_scan_now(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        scan_id = _run_scan()
    except RuntimeError as exc:
        if str(exc) == "A scan is already running.":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        logger.exception("Could not start a manual DealWatch scan.")
        raise HTTPException(status_code=500, detail="Could not start the scan.") from exc

    scan = db.get(ScanRun, scan_id)
    if not scan:
        raise HTTPException(status_code=500, detail="Scan finished without a saved result.")
    if scan.status == "failed":
        raise HTTPException(
            status_code=502,
            detail="The scan failed. Check the latest scan status and backend configuration.",
        )

    records = _visible_records(db, scan.id, user)
    return {
        "scan": {
            "id": scan.id,
            "status": scan.status,
            "started_at": scan.started_at.isoformat(),
            "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
            "error_message": scan.error_message,
            "record_count": len(records),
        },
        "records": [_record_result(record) for record in records],
        "schedule": {"frequency": "weekdays", "time": "09:00", "timezone": TEAM_TIMEZONE},
    }


@app.get("/api/scans/history")
def scan_history(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    scans = db.query(ScanRun).order_by(ScanRun.started_at.desc()).limit(100).all()
    result = []
    for scan in scans:
        records = _visible_records(db, scan.id, user)
        result.append({
            "id": scan.id,
            "status": scan.status,
            "started_at": scan.started_at.isoformat(),
            "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
            "record_count": len(records),
            "pending_count": sum(record.action_status == "needs_approval" for record in records),
        })
    return result


@app.get("/api/scans/{scan_id}")
def scan_details(
    scan_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    scan = db.get(ScanRun, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found.")
    records = _visible_records(db, scan.id, user)
    return _scan_result(scan, records)


@app.post("/api/records/{item_id}/approve")
def approve_record(
    item_id: str,
    body: ApproveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = db.get(ScanRecord, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Record not found.")
    if not _can_view_record(user, item):
        raise HTTPException(status_code=403, detail="You can only approve records assigned to you.")
    if item.action_status != "needs_approval":
        raise HTTPException(status_code=409, detail="This record has already been handled.")

    draft_data = dict(item.draft)
    draft_data["task_subject"] = body.task_subject.strip()
    draft_data["task_description"] = body.task_description.strip()
    if not draft_data["task_subject"] or not draft_data["task_description"]:
        raise HTTPException(status_code=422, detail="Task subject and description are required.")
    draft = Draft(**draft_data)
    priority = Priority(**item.priority)
    record = dict(item.payload)
    try:
        sf = get_sf()
        task_id = create_task(sf, record, draft, priority)
    except Exception as exc:
        item.action_status = "failed"
        item.action_error = str(exc)[:1000]
        db.commit()
        logger.exception("Could not create Salesforce task for record %s.", item.salesforce_id)
        raise HTTPException(status_code=502, detail="Salesforce task creation failed.") from exc

    if task_id is None:
        item.action_status = "duplicate"
        db.commit()
        return _record_result(item)

    item.action_status = "approved"
    item.task_id = task_id
    if item.owner_email:
        try:
            item.email_status = (
                "sent"
                if send_email_alert(
                    sf,
                    record,
                    draft,
                    priority,
                    recipient=item.owner_email,
                )
                else "failed"
            )
        except Exception as exc:
            item.email_status = "failed"
            item.action_error = f"Task created; email failed: {str(exc)[:900]}"
            logger.exception("Email alert failed for record %s.", item.salesforce_id)
    else:
        item.email_status = "not_sent"
        item.action_error = "Task created, but the Salesforce record owner has no email address."
    db.commit()
    return _record_result(item)


@app.post("/api/records/{item_id}/skip")
def skip_record(
    item_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = db.get(ScanRecord, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Record not found.")
    if not _can_view_record(user, item):
        raise HTTPException(status_code=403, detail="You can only skip records assigned to you.")
    if item.action_status != "needs_approval":
        raise HTTPException(status_code=409, detail="This record has already been handled.")
    item.action_status = "skipped"
    db.commit()
    return _record_result(item)
