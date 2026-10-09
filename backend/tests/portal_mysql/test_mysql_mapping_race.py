"""Two authorized editors publish one mapping base on independent MySQL connections."""
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import ArkRole, ArkUser, ArkUserRole
from app.portal import mapping_service
from app.portal.models import AuditEvent, CustomerAccess, MappingRevision, Quote
from app.portal.schemas import MappingInput
from test_mysql_services import compete


@pytest.mark.parametrize('commit_first', [True, False])
def test_two_mapping_editors_serialize_without_lost_update(trade, commit_first):
    ctx = trade
    with Session(ctx.engine) as db:
        editor = ArkUser(username='mapping-editor-' + uuid4().hex[:12],
            password_hash='test-only-not-a-login', real_name='Second editor', is_active=True)
        db.add(editor)
        db.flush()
        role = db.scalar(select(ArkRole).where(ArkRole.name == 'super_admin'))
        db.add(ArkUserRole(user_id=editor.id, role_id=role.id))
        second_actor = editor.id
        access = db.get(CustomerAccess, ctx.access_id)
        public_id, expected, base = access.public_id, access.row_version, access.mapping_version
        db.commit()

    def body(label):
        return MappingInput(base_version=base, entries=[{
            'kind': 'sku', 'source_key': ctx.item_id, 'item_id': ctx.item_id,
            'display_value': label}])

    first, second = compete(ctx,
        lambda db: mapping_service.publish(db, ctx.admin, public_id, expected, body('First Silk')),
        lambda db: mapping_service.publish(db, second_actor, public_id, expected, body('Second Silk')),
        finalize=lambda db: db.commit() if commit_first else db.rollback())
    if commit_first:
        assert second == {'error': 'VERSION_CONFLICT', 'status': 409}
        assert first['mapping_version'] == base + 1
    else:
        assert second['mapping_version'] == base + 1
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess, ctx.access_id)
        assert access.mapping_version == base + 1
        assert access.row_version == expected + 1
        revisions = db.scalars(select(MappingRevision).where(MappingRevision.access_id == ctx.access_id)).all()
        assert len(revisions) == 1
        winner = ctx.admin if commit_first else second_actor
        label = 'First Silk' if commit_first else 'Second Silk'
        assert revisions[0].created_by == winner
        assert revisions[0].base_version == base
        assert revisions[0].snapshot_json['entries'][0]['display_value'] == label
        assert mapping_service.current_projection(db, access)[0]['model_name'] == label
        audits = db.scalars(select(AuditEvent).where(
            AuditEvent.access_id == ctx.access_id, AuditEvent.action == 'mapping_published')).all()
        assert len(audits) == 1 and audits[0].actor_id == winner
        quotes = db.scalars(select(Quote).where(Quote.access_id == ctx.access_id)).all()
        assert quotes and all(quote.status == 'expired' for quote in quotes)
