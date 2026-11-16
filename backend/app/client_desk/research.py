"""Private-desk research status and on-demand scheduling."""

from fastapi import HTTPException

from app.client_desk import service
from app.client_desk.board import research_report
from app.client_desk.private_scope import user_id
from app.client_desk.read_scope import scope_request
from app.client_desk.sources import research_customer_id, research_sources
from app.sales_automation import private_research_service
from app.sales_automation.service import ConflictError, NotFoundError, SalesAutomationError


@scope_request(read_only=True)
def status(db, user, company_id):
    actor = service.scoped(db, user, company_id)
    customer_id = research_customer_id(db, company_id)
    if customer_id is None:
        return {
            "status": "unavailable",
            "last_run_at": None,
            "cooldown_until": None,
            "cooldown_remaining_seconds": 0,
            "can_rerun": False,
            "report": {"status": "none"},
        }
    return {
        **private_research_service.private_research_status(db, customer_id=customer_id),
        "report": research_report(research_sources(db, actor, company_id)),
    }


@scope_request()
def rerun(db, user, company_id):
    actor = service.scoped(db, user, company_id, write=True)
    customer_id = research_customer_id(db, company_id)
    if customer_id is None:
        raise HTTPException(409, "客户档案尚未建立可核验的关联")
    try:
        result = private_research_service.rerun_private_research(
            db, customer_id=customer_id, owner_user_id=user_id(actor)
        )
    except NotFoundError as exc:
        raise HTTPException(404, "客户不存在或已转出") from exc
    except (ConflictError, SalesAutomationError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        **result,
        "report": research_report(research_sources(db, actor, company_id)),
    }
