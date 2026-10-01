import { buildPlanPayload } from './customerWorkspaceController.js'
import { parseApiDateTime } from '../../utils/datetime.js'

const sameRef = (left, right) => left.type === right.type && left.id === right.id && left.revision === right.revision
const requireSource = (rows, id, key, label, mustBeSelectable = true) => {
  const row = rows?.find(value => value[key] === id)
  if (!row || (mustBeSelectable && row.selectable !== true)) throw new Error(`${label}已失效或不可见，请刷新来源后重新选择`)
  return row
}
export function buildSourcedPlanPayload(planType, form, sources, { customerId, campaigns = [], campaignPreview = null, samples = [], now = Date.now() } = {}) {
  let input = { ...form }
  if (planType === 'birthday') {
    const contact = requireSource(sources?.contacts, form.contact_id, 'contact_id', '联系人')
    const birthdayRefs = contact.birthday_evidence_refs || []
    if (!form.evidence_refs?.some(ref => ref.type === 'fact' && ref.revision != null && birthdayRefs.some(source => sameRef(source, ref)))) throw new Error('生日计划需要这个联系人的确证生日事实依据')
    const month = Number(form.month), day = Number(form.day)
    const maximumDays = [31,29,31,30,31,30,31,31,30,31,30,31]
    if (!Number.isInteger(month) || month < 1 || month > 12 || !Number.isInteger(day) || day < 1 || day > maximumDays[month - 1]) throw new Error('请填写有效的生日月日')
    if ((contact.birthday_month != null && month !== contact.birthday_month) || (contact.birthday_day != null && day !== contact.birthday_day)) throw new Error('所填生日与确证来源不一致，请先修订真实生日事实')
  } else if (planType === 'campaign') {
    const campaign = campaigns.find(row => row.id === form.campaign_id && row.status === 'active')
    if (!campaign || campaign.campaign_version == null) throw new Error('请选择当前生效且版本明确的活动')
    if (!campaignPreview || campaignPreview.campaign_id !== campaign.id || campaignPreview.campaign_version !== campaign.campaign_version || !campaignPreview.preview_version) throw new Error('请先重新预览所选活动的适用性')
    if (!campaignPreview.eligible?.some(row => row.customer_id === customerId)) throw new Error('这个客户不在活动适用受众范围内')
    if ((parseApiDateTime(campaignPreview.expires_at)?.getTime() || 0) <= now) throw new Error('活动适用性预览已过期，请重新核验')
    input.campaign_version = campaign.campaign_version
    input.audience_decision_ref = campaignPreview.preview_version
  } else if (planType === 'shipping') {
    const event = requireSource(sources?.shipment_events, form.shipment_event_id, 'shipment_event_id', '物流事件')
    if (!event.trigger_event_type || !event.source_revision) throw new Error('物流事件缺少明确来源版本，请刷新后核验')
    if (!form.shipment_order_link_ids?.length) throw new Error('请选择这个物流事件关联的已确认订单')
    for (const id of form.shipment_order_link_ids) {
      const link = requireSource(sources?.shipment_links, id, 'id', '物流订单关联')
      if (link.state !== 'active' || link.shipment_id !== event.shipment_id || !event.shipment_order_link_ids?.includes(id)) throw new Error('所选订单关联与物流事件不匹配或已撤销')
    }
    input.trigger_event_type = event.trigger_event_type
    input.evidence_refs = event.evidence_refs || []
  } else if (planType === 'sample') {
    requireSource(samples, form.sample_case_id, 'id', '样品事项', false)
  }
  return buildPlanPayload(planType, input)
}
export function birthdayFormFromContact(contact) {
  return { contact_id: contact.contact_id, month: contact.birthday_month ?? null, day: contact.birthday_day ?? null, evidence_refs: [...(contact.birthday_evidence_refs || [])], leap_day_policy: contact.birthday_month === 2 && contact.birthday_day === 29 ? '' : 'skip' }
}
export function shippingFormFromEvent(event) {
  return { shipment_event_id: event.shipment_event_id, shipment_order_link_ids: [...(event.shipment_order_link_ids || [])], trigger_event_type: event.trigger_event_type, evidence_refs: [...(event.evidence_refs || [])] }
}
