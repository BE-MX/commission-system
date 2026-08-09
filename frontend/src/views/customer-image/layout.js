export const MOBILE_FLOW_TEMPLATE = '"logo" "options" "requirement" "preview" "history" "spacer"'

export function mobileFlowAreas() {
  return [...MOBILE_FLOW_TEMPLATE.matchAll(/"([a-z-]+)"/g)].map(match => match[1])
}
