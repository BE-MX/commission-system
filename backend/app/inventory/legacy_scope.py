"""Keep original-provider goods outside every native physical pilot scope.

There is no verified mapping from a provider warehouse to a local warehouse.
An external numeric warehouse ID therefore cannot prove disjoint stock. Until
that mapping exists, assigning any bucket of a mapped SKU excludes that whole
SKU from legacy outbound effects. Unknown SKU identity fails closed whenever
the platform has a native/frozen SKU pilot to protect.
"""
from sqlalchemy import or_, select

from app.catalog.models import CatalogExternalIdentity
from app.commerce_transition import service as transition
from app.commerce_transition.models import ResourceScope
from app.core.config import get_settings


def require_legacy_outbound_scope(db, operation, payload):
    """Call inside the original claim transaction, before durable send intent."""
    if 'outbound' not in operation or operation.endswith('_remove'):
        return
    transition.lock_policy(db)
    scopes = db.scalars(select(ResourceScope).where(ResourceScope.resource_kind == 'sku')
        .with_for_update().execution_options(populate_existing=True)).all()
    protected = {row.resource_key for row in scopes if row.route != 'legacy' or row.state != 'active'}
    if not protected:
        return
    # A stale/invalid phase must never reopen a scope already assigned native.
    namespace = get_settings().PORTAL_OKKI_NAMESPACE.strip()
    if not namespace:
        raise ValueError('旧出库缺少当前小满租户身份，无法排除本地实物范围')
    rows = payload.get('record_list') if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError('旧出库缺少冻结实物明细，无法排除本地实物范围')
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('旧出库实物明细身份不完整')
        product, sku = str(row.get('product_id') or ''), str(row.get('sku_id') or '')
        if not product or not sku:
            raise ValueError('旧出库实物产品或SKU身份缺失')
        aliases = db.scalars(select(CatalogExternalIdentity).where(
            CatalogExternalIdentity.source == 'okki', CatalogExternalIdentity.tenant == namespace,
            CatalogExternalIdentity.external_product_id == product,
            CatalogExternalIdentity.external_sku_id == sku)
            .with_for_update().execution_options(populate_existing=True)).all()
        mapped = {str(alias.sku_id) for alias in aliases}
        if len(mapped) != 1:
            raise ValueError('旧出库SKU缺少当前租户唯一实物映射，禁止绕过本地排他范围')
        if mapped.intersection(protected):
            raise ValueError('该SKU已有本地或冻结实物范围，旧出库不能再次占用或释放')


def require_material_scope_ready(db, resource_key):
    """Known old material uncertainty cannot be erased by a pilot attestation."""
    from app.semifinished.models import InvoiceAllocation
    transition.lock_policy(db)
    query = select(InvoiceAllocation.id).where(or_(InvoiceAllocation.status == 'pending',
        InvoiceAllocation.pending_delta_grams != 0, InvoiceAllocation.operation_key.is_not(None),
        InvoiceAllocation.pending_at.is_not(None)))
    key = str(resource_key)
    if (len(key) <= 19 and key.isascii() and key.isdecimal()
            and 0 < int(key) <= 9223372036854775807 and key == str(int(key))):
        query = query.where(InvoiceAllocation.material_id == int(key))
    # Unknown/noncanonical keys cannot prove exclusion from any known pending
    # material. Do not guess an alias, clear a token, or mark the old send failed.
    if db.scalar(query.limit(1).with_for_update()) is not None:
        raise ValueError('原物料仍有未决扣量或发送责任，核清原请求后才能分配本地实物范围')
