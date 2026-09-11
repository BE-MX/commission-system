"""Read-only validation of a reviewed profile; optional local deployment fragment.

Never refresh hashes automatically: changed published content requires review.
No model requests or production writes are performed.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.auth.service import get_live_user_authorization
from app.core.config import Settings
from app.knowledge.reply_sources import parse_bindings, resolve_binding, retrieve_reply_sources


def validate_profile(db, actor, profile):
    bindings = parse_bindings(profile)
    documents = {}
    invalid = [{"document_id": b.document_id, "section_index": b.section_index}
               for b in bindings if resolve_binding(db, actor, b, documents=documents) is None]
    queries = [["single donor"], ["custom colors"], ["实验室"], ["silicone"], ["acid"]]
    checks = []
    for query in queries:
        selected, policies = retrieve_reply_sources(db, actor, bindings, query)
        checks.append({"query": query[0], "policies_available": policies,
                       "fact_count": sum(item["purpose"] == "public_fact" for item in selected),
                       "source_count": len(selected)})
    return {"valid": not invalid and all(c["policies_available"] and c["fact_count"] for c in checks),
            "counts": dict(Counter(b.purpose for b in bindings)), "invalid": invalid, "retrieval": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--user-id", required=True, type=int)
    parser.add_argument("--write-fragment", type=Path)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    settings = Settings(_env_file=args.env_file)
    engine = create_engine(settings.commission_db_url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
            connection.commit()
            with Session(bind=connection) as db:
                roles, permissions = get_live_user_authorization(db, args.user_id)
                result = validate_profile(db, {"sub": str(args.user_id), "roles": roles, "permissions": permissions}, profile)
                db.rollback()
        if args.write_fragment and result["valid"]:
            target = args.write_fragment.resolve()
            if target == args.env_file.resolve() or target.name == ".env":
                raise ValueError("refusing to overwrite an environment file")
            target.parent.mkdir(parents=True, exist_ok=True)
            # JSON is single-quoted for dotenv; reject an ambiguous apostrophe.
            encoded = json.dumps(profile, ensure_ascii=False, separators=(",", ":"))
            if "'" in encoded:
                raise ValueError("profile cannot be represented as a single-quoted dotenv value")
            target.write_text("WHATSAPP_REPLY_MEMORY_ENABLED=true\nWHATSAPP_REPLY_MEMORY_RETENTION_DAYS=30\nWHATSAPP_REPLY_SOURCE_BINDINGS='" + encoded + "'\n", encoding="utf-8")
            result["fragment_written"] = True
        print(json.dumps(result, ensure_ascii=False))
        if not result["valid"]:
            raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
