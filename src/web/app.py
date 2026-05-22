"""FastAPI organizer web application for TelegramTaskChecker."""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from src.bot.models import Campaign, CampaignType, Review, Submission, SubmissionFormat, SubmissionStatus, User, UserRole
from src.db.engine import get_session

try:
    from openpyxl import Workbook
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("openpyxl is required for XLSX export") from exc

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"

app = FastAPI(
    title="TelegramTaskChecker Organizer Web",
    version="1.0.0",
    description="Organizer dashboard and JSON API for TelegramTaskChecker.",
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

DbSession = Annotated[AsyncSession, Depends(get_session)]

class CampaignCreatePayload(BaseModel):
    """Payload for creating a campaign."""

    title: str = Field(min_length=1, max_length=500)
    type: CampaignType
    min_score: int = 0
    max_score: int = 100
    ttl_minutes: int = 1440
    campaign_deadline_at: datetime | None = None
    is_expert_anon: bool = False
    p2p_reviews_required: int = 3
    voting_type: str | None = None
    submission_format: SubmissionFormat = SubmissionFormat.DOCUMENT
    allowed_extensions: str | None = None
    criteria_text: str | None = None
    allow_resubmission_after_review: bool = False
    allow_resubmission_before_review: bool = False
    is_active: bool = True

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be empty")
        return value

    @field_validator("max_score")
    @classmethod
    def validate_scores(cls, value: int, info) -> int:
        min_score = info.data.get("min_score", 0)
        if value < min_score:
            raise ValueError("max_score cannot be less than min_score")
        return value

class CampaignUpdatePayload(BaseModel):
    """Payload for updating a campaign."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    type: CampaignType | None = None
    min_score: int | None = None
    max_score: int | None = None
    ttl_minutes: int | None = None
    campaign_deadline_at: datetime | None = None
    is_expert_anon: bool | None = None
    p2p_reviews_required: int | None = None
    voting_type: str | None = None
    submission_format: SubmissionFormat | None = None
    allowed_extensions: str | None = None
    criteria_text: str | None = None
    allow_resubmission_after_review: bool | None = None
    allow_resubmission_before_review: bool | None = None
    is_active: bool | None = None

    @field_validator("title")
    @classmethod
    def validate_optional_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be empty")
        return value

class BanPayload(BaseModel):
    """Payload for ban/unban action."""

    is_banned: bool

class DashboardStats(BaseModel):
    active_campaigns: int
    submissions_in_queue: int
    waiting_review: int
    without_reviewer: int
    reviewed_submissions: int
    banned_users: int
    api_status: str
    db_status: str

class DashboardCampaignCard(BaseModel):
    id: int
    title: str
    type: str
    submission_format: str
    is_active: bool
    deadline_at: str | None
    queue_count: int
    reviewed_count: int
    completion_percent: int

class DashboardResponse(BaseModel):
    stats: DashboardStats
    campaigns: list[DashboardCampaignCard]

class CampaignListItem(BaseModel):
    id: int
    title: str
    type: str
    submission_format: str
    min_score: int
    max_score: int
    ttl_minutes: int
    campaign_deadline_at: str | None
    is_expert_anon: bool
    p2p_reviews_required: int
    voting_type: str | None
    allowed_extensions: str | None
    criteria_text: str | None
    allow_resubmission_after_review: bool
    allow_resubmission_before_review: bool
    is_active: bool
    created_at: str
    updated_at: str
    submissions_total: int
    queue_count: int
    reviewed_count: int
    average_score: float | None

class UserListItem(BaseModel):
    tg_id: int
    full_name: str
    study_group: str | None
    role: str
    is_banned: bool
    campaign_id: int | None
    campaign_title: str | None
    registered_by_code: bool
    invite_role: str | None
    created_at: str
    updated_at: str

class ReportCampaignItem(BaseModel):
    id: int
    title: str
    type: str
    is_active: bool
    completed: bool
    submissions_total: int
    uploaded_count: int
    in_review_count: int
    reviewed_count: int
    rejected_count: int
    average_score: float | None

class HealthResponse(BaseModel):
    status: str
    database: str
    timestamp: str

@dataclass(frozen=True)
class ExportFieldDefinition:
    key: str
    label: str

EXPORT_FIELDS: list[ExportFieldDefinition] = [
    ExportFieldDefinition("campaign_id", "ID кампании"),
    ExportFieldDefinition("campaign_title", "Название кампании"),
    ExportFieldDefinition("campaign_type", "Тип кампании"),
    ExportFieldDefinition("submission_id", "ID работы"),
    ExportFieldDefinition("submission_status", "Статус работы"),
    ExportFieldDefinition("submission_created_at", "Дата отправки работы"),
    ExportFieldDefinition("author_tg_id", "Telegram ID автора"),
    ExportFieldDefinition("author_full_name", "Автор"),
    ExportFieldDefinition("author_study_group", "Учебная группа"),
    ExportFieldDefinition("reviewer_tg_id", "Telegram ID проверяющего"),
    ExportFieldDefinition("reviewer_full_name", "Проверяющий"),
    ExportFieldDefinition("score", "Оценка"),
    ExportFieldDefinition("comment_text", "Комментарий"),
    ExportFieldDefinition("ban_comment", "Причина бана"),
    ExportFieldDefinition("review_created_at", "Дата проверки"),
    ExportFieldDefinition("criteria_scores", "Критерии и баллы"),
]

def serialize_dt(value: datetime | None) -> str | None:
    """Serialize datetime to ISO-like string."""
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()

def build_campaign_item(payload: dict[str, Any]) -> CampaignListItem:
    """Build campaign response object from query payload."""
    return CampaignListItem(
        id=payload["id"],
        title=payload["title"],
        type=payload["type"].value if isinstance(payload["type"], CampaignType) else str(payload["type"]),
        submission_format=payload["submission_format"].value
        if isinstance(payload["submission_format"], SubmissionFormat)
        else str(payload["submission_format"]),
        min_score=payload["min_score"],
        max_score=payload["max_score"],
        ttl_minutes=payload["ttl_minutes"],
        campaign_deadline_at=serialize_dt(payload["campaign_deadline_at"]),
        is_expert_anon=payload["is_expert_anon"],
        p2p_reviews_required=payload["p2p_reviews_required"],
        voting_type=payload["voting_type"],
        allowed_extensions=payload["allowed_extensions"],
        criteria_text=payload["criteria_text"],
        allow_resubmission_after_review=payload["allow_resubmission_after_review"],
        allow_resubmission_before_review=payload["allow_resubmission_before_review"],
        is_active=payload["is_active"],
        created_at=serialize_dt(payload["created_at"]) or "",
        updated_at=serialize_dt(payload["updated_at"]) or "",
        submissions_total=payload["submissions_total"] or 0,
        queue_count=payload["queue_count"] or 0,
        reviewed_count=payload["reviewed_count"] or 0,
        average_score=round(float(payload["average_score"]), 2) if payload["average_score"] is not None else None,
    )

async def get_campaign_or_404(session: AsyncSession, campaign_id: int) -> Campaign:
    """Fetch campaign or raise 404."""
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign

def campaign_completion_percent(submissions_total: int, reviewed_count: int) -> int:
    """Calculate completion percentage."""
    if submissions_total <= 0:
        return 0
    return min(100, round(reviewed_count / submissions_total * 100))

def report_completion(is_active: bool, deadline: datetime | None, in_review: int, uploaded: int) -> bool:
    """Infer whether campaign can be considered completed."""
    deadline_passed = deadline is not None and deadline <= datetime.now(timezone.utc)
    return (not is_active or deadline_passed) and in_review == 0 and uploaded == 0

async def get_web_access_user_or_404(session: AsyncSession, access_token: str) -> User:
    """Validate organizer web access token and return owner user."""
    result = await session.execute(select(User).where(User.web_access_token == access_token))
    user = result.scalar_one_or_none()
    if user is None or user.role not in {UserRole.ORGANIZER, UserRole.EXPERT_ORGANIZER}:
        raise HTTPException(status_code=404, detail="Web access link not found")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="Access denied")
    return user

@app.get("/", include_in_schema=False, response_model=None)
async def index() -> Response:
    """Serve access denied stub on the main address."""
    return HTMLResponse(
        """
        <!DOCTYPE html>
        <html lang="ru">
        <head>
          <meta charset="UTF-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1.0" />
          <title>Доступ запрещён</title>
          <style>
            body {
              margin: 0;
              min-height: 100vh;
              display: flex;
              align-items: center;
              justify-content: center;
              background: #0f172a;
              color: #e2e8f0;
              font-family: Arial, sans-serif;
            }
            .card {
              max-width: 560px;
              padding: 32px;
              margin: 24px;
              border-radius: 20px;
              background: #111827;
              border: 1px solid #334155;
              box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
              text-align: center;
            }
            h1 {
              margin: 0 0 16px;
              font-size: 32px;
            }
            p {
              margin: 0;
              color: #94a3b8;
              line-height: 1.6;
            }
          </style>
        </head>
        <body>
          <div class="card">
            <h1>Доступ запрещён</h1>
            <p>Эта страница доступна только по персональной ссылке организатора.</p>
          </div>
        </body>
        </html>
        """
    )

@app.get("/organizer/{access_token}", include_in_schema=False, response_model=None)
async def organizer_index(access_token: str, session: DbSession) -> Response:
    """Serve organizer UI only by unique organizer link."""
    await get_web_access_user_or_404(session, access_token)
    if not INDEX_FILE.exists():
        return JSONResponse(
            {
                "message": "Organizer UI is not generated yet.",
                "hint": "Create src/web/static/index.html to enable the web interface.",
            },
            status_code=503,
        )
    return FileResponse(INDEX_FILE)

@app.get("/organizer/{access_token}/health", response_model=HealthResponse)
async def health(access_token: str, session: DbSession) -> HealthResponse:
    """Healthcheck endpoint."""
    await get_web_access_user_or_404(session, access_token)
    await session.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok",
        database="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

@app.get("/organizer/{access_token}/api/dashboard", response_model=DashboardResponse)
async def get_dashboard(access_token: str, session: DbSession) -> DashboardResponse:
    """Return dashboard aggregates."""
    await get_web_access_user_or_404(session, access_token)
    active_campaigns = await session.scalar(select(func.count()).select_from(Campaign).where(Campaign.is_active.is_(True))) or 0
    submissions_in_queue = await session.scalar(
        select(func.count()).select_from(Submission).where(
            Submission.status.in_([SubmissionStatus.UPLOADED, SubmissionStatus.IN_REVIEW])
        )
    ) or 0
    waiting_review = await session.scalar(
        select(func.count()).select_from(Submission).where(Submission.status == SubmissionStatus.UPLOADED)
    ) or 0
    reviewed_submissions = await session.scalar(
        select(func.count()).select_from(Submission).where(Submission.status == SubmissionStatus.REVIEWED)
    ) or 0
    banned_users = await session.scalar(
        select(func.count()).select_from(User).where(User.is_banned.is_(True))
    ) or 0

    reviewer_alias = aliased(Review)
    without_reviewer = await session.scalar(
        select(func.count())
        .select_from(Submission)
        .outerjoin(reviewer_alias, reviewer_alias.submission_id == Submission.id)
        .where(
            Submission.status.in_([SubmissionStatus.UPLOADED, SubmissionStatus.IN_REVIEW]),
            reviewer_alias.id.is_(None),
        )
    ) or 0

    campaigns_stmt = (
        select(
            Campaign.id,
            Campaign.title,
            Campaign.type,
            Campaign.submission_format,
            Campaign.is_active,
            Campaign.campaign_deadline_at,
            func.count(Submission.id).label("submissions_total"),
            func.sum(
                case(
                    (Submission.status.in_([SubmissionStatus.UPLOADED, SubmissionStatus.IN_REVIEW]), 1),
                    else_=0,
                )
            ).label("queue_count"),
            func.sum(
                case((Submission.status == SubmissionStatus.REVIEWED, 1), else_=0)
            ).label("reviewed_count"),
        )
        .outerjoin(Submission, Submission.campaign_id == Campaign.id)
        .group_by(Campaign.id)
        .order_by(Campaign.is_active.desc(), Campaign.created_at.desc())
        .limit(8)
    )
    campaign_rows = (await session.execute(campaigns_stmt)).mappings().all()

    return DashboardResponse(
        stats=DashboardStats(
            active_campaigns=int(active_campaigns),
            submissions_in_queue=int(submissions_in_queue),
            waiting_review=int(waiting_review),
            without_reviewer=int(without_reviewer),
            reviewed_submissions=int(reviewed_submissions),
            banned_users=int(banned_users),
            api_status="ok",
            db_status="ok",
        ),
        campaigns=[
            DashboardCampaignCard(
                id=row["id"],
                title=row["title"],
                type=row["type"].value if isinstance(row["type"], CampaignType) else str(row["type"]),
                submission_format=row["submission_format"].value
                if isinstance(row["submission_format"], SubmissionFormat)
                else str(row["submission_format"]),
                is_active=row["is_active"],
                deadline_at=serialize_dt(row["campaign_deadline_at"]),
                queue_count=row["queue_count"] or 0,
                reviewed_count=row["reviewed_count"] or 0,
                completion_percent=campaign_completion_percent(
                    row["submissions_total"] or 0,
                    row["reviewed_count"] or 0,
                ),
            )
            for row in campaign_rows
        ],
    )

@app.get("/organizer/{access_token}/api/campaigns", response_model=list[CampaignListItem])
async def get_campaigns(access_token: str, session: DbSession) -> list[CampaignListItem]:
    """Return campaigns with lightweight metrics."""
    await get_web_access_user_or_404(session, access_token)
    stmt = (
        select(
            Campaign.id,
            Campaign.title,
            Campaign.type,
            Campaign.submission_format,
            Campaign.min_score,
            Campaign.max_score,
            Campaign.ttl_minutes,
            Campaign.campaign_deadline_at,
            Campaign.is_expert_anon,
            Campaign.p2p_reviews_required,
            Campaign.voting_type,
            Campaign.allowed_extensions,
            Campaign.criteria_text,
            Campaign.allow_resubmission_after_review,
            Campaign.allow_resubmission_before_review,
            Campaign.is_active,
            Campaign.created_at,
            Campaign.updated_at,
            func.count(Submission.id).label("submissions_total"),
            func.sum(
                case(
                    (Submission.status.in_([SubmissionStatus.UPLOADED, SubmissionStatus.IN_REVIEW]), 1),
                    else_=0,
                )
            ).label("queue_count"),
            func.sum(case((Submission.status == SubmissionStatus.REVIEWED, 1), else_=0)).label("reviewed_count"),
            func.avg(Review.score).label("average_score"),
        )
        .outerjoin(Submission, Submission.campaign_id == Campaign.id)
        .outerjoin(Review, Review.submission_id == Submission.id)
        .group_by(Campaign.id)
        .order_by(Campaign.is_active.desc(), Campaign.created_at.desc())
    )
    rows = (await session.execute(stmt)).mappings().all()
    return [build_campaign_item(row) for row in rows]

@app.post("/organizer/{access_token}/api/campaigns", response_model=CampaignListItem, status_code=201)
async def create_campaign(access_token: str, payload: CampaignCreatePayload, session: DbSession) -> CampaignListItem:
    """Create a new campaign."""
    await get_web_access_user_or_404(session, access_token)
    campaign = Campaign(
        title=payload.title,
        type=payload.type,
        min_score=payload.min_score,
        max_score=payload.max_score,
        ttl_minutes=payload.ttl_minutes,
        campaign_deadline_at=payload.campaign_deadline_at,
        is_expert_anon=payload.is_expert_anon,
        p2p_reviews_required=payload.p2p_reviews_required,
        voting_type=payload.voting_type,
        submission_format=payload.submission_format,
        allowed_extensions=payload.allowed_extensions,
        criteria_text=payload.criteria_text,
        allow_resubmission_after_review=payload.allow_resubmission_after_review,
        allow_resubmission_before_review=payload.allow_resubmission_before_review,
        is_active=payload.is_active,
    )
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)

    return build_campaign_item(
        {
            "id": campaign.id,
            "title": campaign.title,
            "type": campaign.type,
            "submission_format": campaign.submission_format,
            "min_score": campaign.min_score,
            "max_score": campaign.max_score,
            "ttl_minutes": campaign.ttl_minutes,
            "campaign_deadline_at": campaign.campaign_deadline_at,
            "is_expert_anon": campaign.is_expert_anon,
            "p2p_reviews_required": campaign.p2p_reviews_required,
            "voting_type": campaign.voting_type,
            "allowed_extensions": campaign.allowed_extensions,
            "criteria_text": campaign.criteria_text,
            "allow_resubmission_after_review": campaign.allow_resubmission_after_review,
            "allow_resubmission_before_review": campaign.allow_resubmission_before_review,
            "is_active": campaign.is_active,
            "created_at": campaign.created_at,
            "updated_at": campaign.updated_at,
            "submissions_total": 0,
            "queue_count": 0,
            "reviewed_count": 0,
            "average_score": None,
        }
    )

@app.patch("/organizer/{access_token}/api/campaigns/{campaign_id}", response_model=CampaignListItem)
async def update_campaign(
    access_token: str,
    campaign_id: int,
    payload: CampaignUpdatePayload,
    session: DbSession,
) -> CampaignListItem:
    """Update campaign."""
    await get_web_access_user_or_404(session, access_token)
    campaign = await get_campaign_or_404(session, campaign_id)

    changes = payload.model_dump(exclude_unset=True)
    if "min_score" in changes or "max_score" in changes:
        new_min = changes.get("min_score", campaign.min_score)
        new_max = changes.get("max_score", campaign.max_score)
        if new_max < new_min:
            raise HTTPException(status_code=422, detail="max_score cannot be less than min_score")

    for field_name, value in changes.items():
        setattr(campaign, field_name, value)

    await session.commit()
    await session.refresh(campaign)

    metrics_stmt = (
        select(
            func.count(Submission.id).label("submissions_total"),
            func.sum(
                case(
                    (Submission.status.in_([SubmissionStatus.UPLOADED, SubmissionStatus.IN_REVIEW]), 1),
                    else_=0,
                )
            ).label("queue_count"),
            func.sum(case((Submission.status == SubmissionStatus.REVIEWED, 1), else_=0)).label("reviewed_count"),
            func.avg(Review.score).label("average_score"),
        )
        .outerjoin(Review, Review.submission_id == Submission.id)
        .where(Submission.campaign_id == campaign.id)
    )
    metrics = (await session.execute(metrics_stmt)).mappings().one()

    return build_campaign_item(
        {
            "id": campaign.id,
            "title": campaign.title,
            "type": campaign.type,
            "submission_format": campaign.submission_format,
            "min_score": campaign.min_score,
            "max_score": campaign.max_score,
            "ttl_minutes": campaign.ttl_minutes,
            "campaign_deadline_at": campaign.campaign_deadline_at,
            "is_expert_anon": campaign.is_expert_anon,
            "p2p_reviews_required": campaign.p2p_reviews_required,
            "voting_type": campaign.voting_type,
            "allowed_extensions": campaign.allowed_extensions,
            "criteria_text": campaign.criteria_text,
            "allow_resubmission_after_review": campaign.allow_resubmission_after_review,
            "allow_resubmission_before_review": campaign.allow_resubmission_before_review,
            "is_active": campaign.is_active,
            "created_at": campaign.created_at,
            "updated_at": campaign.updated_at,
            "submissions_total": metrics["submissions_total"] or 0,
            "queue_count": metrics["queue_count"] or 0,
            "reviewed_count": metrics["reviewed_count"] or 0,
            "average_score": metrics["average_score"],
        }
    )

@app.get("/organizer/{access_token}/api/users", response_model=list[UserListItem])
async def get_users(
    access_token: str,
    session: DbSession,
    role: UserRole | None = None,
    study_group: str | None = None,
    is_banned: bool | None = None,
    search: str | None = None,
) -> list[UserListItem]:
    """Return users with filters."""
    await get_web_access_user_or_404(session, access_token)
    stmt = (
        select(User, Campaign.title.label("campaign_title"))
        .outerjoin(Campaign, Campaign.id == User.campaign_id)
        .order_by(User.created_at.desc())
    )

    conditions = []
    if role is not None:
        conditions.append(User.role == role)
    if study_group:
        conditions.append(User.study_group == study_group)
    if is_banned is not None:
        conditions.append(User.is_banned.is_(is_banned))
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                User.full_name.ilike(pattern),
                User.study_group.ilike(pattern),
                func.cast(User.tg_id, literal("TEXT").type).ilike(pattern),
            )
        )

    if conditions:
        stmt = stmt.where(*conditions)

    rows = (await session.execute(stmt)).all()
    return [
        UserListItem(
            tg_id=user.tg_id,
            full_name=user.full_name,
            study_group=user.study_group,
            role=user.role.value if isinstance(user.role, UserRole) else str(user.role),
            is_banned=user.is_banned,
            campaign_id=user.campaign_id,
            campaign_title=campaign_title,
            registered_by_code=user.registered_by_code,
            invite_role=user.invite_role,
            created_at=serialize_dt(user.created_at) or "",
            updated_at=serialize_dt(user.updated_at) or "",
        )
        for user, campaign_title in rows
    ]

@app.patch("/organizer/{access_token}/api/users/{tg_id}/ban", response_model=UserListItem)
async def set_user_ban_status(
    access_token: str,
    tg_id: int,
    payload: BanPayload,
    session: DbSession,
) -> UserListItem:
    """Ban or unban user."""
    await get_web_access_user_or_404(session, access_token)
    stmt = (
        select(User, Campaign.title.label("campaign_title"))
        .outerjoin(Campaign, Campaign.id == User.campaign_id)
        .where(User.tg_id == tg_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    user, campaign_title = row
    user.is_banned = payload.is_banned
    await session.commit()
    await session.refresh(user)

    return UserListItem(
        tg_id=user.tg_id,
        full_name=user.full_name,
        study_group=user.study_group,
        role=user.role.value if isinstance(user.role, UserRole) else str(user.role),
        is_banned=user.is_banned,
        campaign_id=user.campaign_id,
        campaign_title=campaign_title,
        registered_by_code=user.registered_by_code,
        invite_role=user.invite_role,
        created_at=serialize_dt(user.created_at) or "",
        updated_at=serialize_dt(user.updated_at) or "",
    )

@app.get("/organizer/{access_token}/api/reports/campaigns")
async def get_report_campaigns(access_token: str, session: DbSession) -> dict[str, Any]:
    """Return campaign report cards and available export fields."""
    await get_web_access_user_or_404(session, access_token)
    stmt = (
        select(
            Campaign.id,
            Campaign.title,
            Campaign.type,
            Campaign.is_active,
            Campaign.campaign_deadline_at,
            func.count(Submission.id).label("submissions_total"),
            func.sum(case((Submission.status == SubmissionStatus.UPLOADED, 1), else_=0)).label("uploaded_count"),
            func.sum(case((Submission.status == SubmissionStatus.IN_REVIEW, 1), else_=0)).label("in_review_count"),
            func.sum(case((Submission.status == SubmissionStatus.REVIEWED, 1), else_=0)).label("reviewed_count"),
            func.sum(case((Submission.status == SubmissionStatus.REJECTED, 1), else_=0)).label("rejected_count"),
            func.avg(Review.score).label("average_score"),
        )
        .outerjoin(Submission, Submission.campaign_id == Campaign.id)
        .outerjoin(Review, Review.submission_id == Submission.id)
        .group_by(Campaign.id)
        .order_by(Campaign.created_at.desc())
    )
    rows = (await session.execute(stmt)).mappings().all()

    campaigns = [
        ReportCampaignItem(
            id=row["id"],
            title=row["title"],
            type=row["type"].value if isinstance(row["type"], CampaignType) else str(row["type"]),
            is_active=row["is_active"],
            completed=report_completion(
                row["is_active"],
                row["campaign_deadline_at"],
                row["in_review_count"] or 0,
                row["uploaded_count"] or 0,
            ),
            submissions_total=row["submissions_total"] or 0,
            uploaded_count=row["uploaded_count"] or 0,
            in_review_count=row["in_review_count"] or 0,
            reviewed_count=row["reviewed_count"] or 0,
            rejected_count=row["rejected_count"] or 0,
            average_score=round(float(row["average_score"]), 2) if row["average_score"] is not None else None,
        )
        for row in rows
    ]

    return {
        "campaigns": [campaign.model_dump() for campaign in campaigns],
        "available_fields": [{"key": field.key, "label": field.label} for field in EXPORT_FIELDS],
    }

@app.get("/organizer/{access_token}/api/reports/campaigns/{campaign_id}/export.xlsx")
async def export_campaign_xlsx(
    access_token: str,
    campaign_id: int,
    session: DbSession,
    fields: Annotated[list[str] | None, Query()] = None,
) -> StreamingResponse:
    """Export campaign results to XLSX."""
    await get_web_access_user_or_404(session, access_token)
    campaign = await session.get(
        Campaign,
        campaign_id,
        options=[selectinload(Campaign.submissions).selectinload(Submission.author)],
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    selected_fields = {field.key for field in EXPORT_FIELDS}
    if fields:
        requested = {field for field in fields if field in selected_fields}
        selected_fields = requested or selected_fields

    reviewer_alias = aliased(User)
    stmt = (
        select(
            Submission.id.label("submission_id"),
            Submission.status.label("submission_status"),
            Submission.created_at.label("submission_created_at"),
            Submission.author_id.label("author_tg_id"),
            User.full_name.label("author_full_name"),
            User.study_group.label("author_study_group"),
            Review.reviewer_id.label("reviewer_tg_id"),
            reviewer_alias.full_name.label("reviewer_full_name"),
            Review.score.label("score"),
            Review.comment_text.label("comment_text"),
            Review.ban_comment.label("ban_comment"),
            Review.created_at.label("review_created_at"),
            Review.criteria_scores.label("criteria_scores"),
        )
        .join(User, User.tg_id == Submission.author_id)
        .outerjoin(Review, Review.submission_id == Submission.id)
        .outerjoin(reviewer_alias, reviewer_alias.tg_id == Review.reviewer_id)
        .where(Submission.campaign_id == campaign_id)
        .order_by(Submission.created_at.asc(), Submission.id.asc())
    )
    rows = (await session.execute(stmt)).mappings().all()

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = f"campaign_{campaign_id}"

    active_fields = [field for field in EXPORT_FIELDS if field.key in selected_fields]
    worksheet.append([field.label for field in active_fields])

    for row in rows:
        record = {
            "campaign_id": campaign.id,
            "campaign_title": campaign.title,
            "campaign_type": campaign.type.value if isinstance(campaign.type, CampaignType) else str(campaign.type),
            "submission_id": row["submission_id"],
            "submission_status": row["submission_status"].value
            if isinstance(row["submission_status"], SubmissionStatus)
            else str(row["submission_status"]),
            "submission_created_at": serialize_dt(row["submission_created_at"]),
            "author_tg_id": row["author_tg_id"],
            "author_full_name": row["author_full_name"],
            "author_study_group": row["author_study_group"],
            "reviewer_tg_id": row["reviewer_tg_id"],
            "reviewer_full_name": row["reviewer_full_name"],
            "score": row["score"],
            "comment_text": row["comment_text"],
            "ban_comment": row["ban_comment"],
            "review_created_at": serialize_dt(row["review_created_at"]),
            "criteria_scores": row["criteria_scores"],
        }
        worksheet.append([record[field.key] for field in active_fields])

    for column in worksheet.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        worksheet.column_dimensions[column_letter].width = min(max(max_length + 2, 14), 48)

    stream = io.BytesIO()
    workbook.save(stream)
    stream.seek(0)

    filename = f"campaign_{campaign_id}_results.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )