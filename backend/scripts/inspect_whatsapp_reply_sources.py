"""Read-only source binding preparation; does not approve disclosure or edit KB.

Run from backend: python -m scripts.inspect_whatsapp_reply_sources --user-id N
--document-id N [--document-id N ...]. Optional --env-file selects an existing
configuration without copying credentials. Default output is metadata only.
"""

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.auth.service import get_live_user_authorization
from app.core.config import Settings
from app.knowledge import service
from app.knowledge.reply_sources import content_hash, sections


def inspect_sources(db, user_id, document_ids, show_text=False):
    roles, permissions = get_live_user_authorization(db, user_id)
    actor = {"sub": str(user_id), "roles": roles, "permissions": permissions}
    result = []
    for document_id in document_ids:
        try:
            document = service.get_published_document(db, actor, document_id)
        except (service.NotFoundError, service.ForbiddenError):
            result.append({"document_id": document_id, "accessible": False})
            continue
        for index, text in enumerate(sections(document["content_json"])):
            item = {
                "document_id": document_id, "revision_id": document["revision_id"],
                "version_no": document["version_no"], "section_index": index,
                "content_hash": content_hash(text), "chars": len(text),
                "within_budget": 0 < len(text) <= 1200,
                "purpose": "blocked", "mandatory": False,
                "policy_version": "review-required",
            }
            if show_text:
                item["text"] = text
            result.append(item)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, type=int)
    parser.add_argument("--document-id", required=True, action="append", type=int)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--show-text", action="store_true", help="Display authorized knowledge, never chat or credentials")
    args = parser.parse_args()
    settings = Settings(_env_file=args.env_file) if args.env_file else Settings()
    engine = create_engine(settings.commission_db_url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
            connection.commit()
            with Session(bind=connection) as db:
                result = inspect_sources(db, args.user_id, args.document_id, args.show_text)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                db.rollback()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
