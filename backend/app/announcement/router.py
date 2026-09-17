"""Thin authorized HTTP adapters for announcement use cases."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.auth.dependencies import require_any_permission
from app.core.database import get_db
from app.core.response import ok
from app.knowledge.router import _call
from app.knowledge.schemas import MembersReplace
from app.announcement import service, settings_service, weekly, delivery, channel_test
from app.announcement.models import WeeklyReport, Delivery
from app.announcement.schemas import AnnouncementInput, CategoryInput, ReviewInput, ReasonInput, PinInput, ConfigInput, RetryInput, WeeklyInput, VerifyInput

router = APIRouter()
READ = ('announcement:read', 'announcement:write', 'announcement:admin')
WRITE = ('announcement:write', 'announcement:admin')
ADMIN = ('announcement:admin',)


@router.get('/config')
def get_config(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(settings_service.get_config, db, user))


@router.post('/initialize')
def initialize(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    _call(service.initialize, db, user)
    return ok(_call(settings_service.get_config, db, user))


@router.put('/config')
def configure(payload: ConfigInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    return ok(_call(settings_service.update_config, db, user, payload.model_dump()))


@router.get('/members')
def members(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    return ok(_call(settings_service.members, db, user))


@router.get('/member-candidates')
def member_candidates(q: str = Query('', max_length=50), db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    return ok(_call(settings_service.members, db, user, query=q))


@router.put('/members')
def replace_members(payload: MembersReplace, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    return ok(_call(settings_service.members, db, user, values=[m.model_dump() for m in payload.members]))


@router.post('/channel-test')
def test_channel(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    return ok(_call(channel_test.request_test, db, user))


@router.post('/channel-verify')
def verify_channel(payload: VerifyInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    _call(channel_test.verify, db, user, payload.test_key)
    return ok({'verified': True})


@router.get('/categories')
def categories(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(service.categories, db, user))


@router.post('/categories')
def create_category(payload: CategoryInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    row = _call(service.save_category, db, user, **payload.model_dump())
    return ok({'id': row.id, 'title': row.title})


@router.put('/categories/{category_id}')
def update_category(category_id: int, payload: CategoryInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    row = _call(service.save_category, db, user, category_id=category_id, **payload.model_dump())
    return ok({'id': row.id, 'title': row.title})


@router.get('/weekly')
def weekly_history(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(weekly.history, db, user))


@router.post('/weekly')
def generate_weekly(payload: WeeklyInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    row = _call(weekly.request_report, db, user, regenerate=payload.regenerate)
    return ok({'id': row.id, 'status': row.status})


@router.post('/weekly/{report_id}/send')
def send_weekly(report_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    _call(weekly.send_report, db, user, report_id)
    return ok({'queued': True})


@router.get('/deliveries')
def deliveries(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    return ok(_call(service.list_deliveries, db, user))


@router.post('/deliveries/{task_id}/retry')
def retry_delivery(task_id: int, payload: RetryInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    _call(delivery.retry, db, user, task_id, **payload.model_dump())
    return ok({'updated': True})


@router.get('')
def list_announcements(q: str = Query('', max_length=128), category_id: int | None = None, status: str | None = None,
                       page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                       db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(service.list_announcements, db, user, q=q, category_id=category_id, status=status, page=page, page_size=page_size))


@router.post('')
def create(payload: AnnouncementInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    row = _call(service.save_announcement, db, user, **payload.model_dump())
    return ok({'id': row.document_id})


@router.get('/{document_id}')
def detail(document_id: int, edit: bool = False, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(service.detail, db, user, document_id, edit=edit))


@router.get('/{document_id}/preview')
def preview(document_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(service.preview, db, user, document_id))


@router.put('/{document_id}')
def save(document_id: int, payload: AnnouncementInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    row = _call(service.save_announcement, db, user, document_id=document_id, **payload.model_dump())
    return ok({'id': row.document_id})


@router.delete('/{document_id}')
def delete(document_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    return ok(_call(service.delete_draft, db, user, document_id))


@router.post('/{document_id}/submit')
def submit(document_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    row = _call(service.submit, db, user, document_id)
    return ok({'id': row.id, 'status': row.status})


@router.post('/{document_id}/review')
def review(document_id: int, payload: ReviewInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission('knowledge:review', 'knowledge:admin', 'announcement:admin'))):
    return ok(_call(service.review, db, user, document_id, **payload.model_dump()))


@router.post('/{document_id}/withdraw')
def withdraw(document_id: int, payload: ReasonInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    _call(service.withdraw, db, user, document_id, payload.reason)
    return ok({'withdrawn': True})


@router.put('/{document_id}/pin')
def pin(document_id: int, payload: PinInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*ADMIN))):
    _call(settings_service.pin, db, user, document_id, payload.pinned)
    return ok({'pinned': payload.pinned})
