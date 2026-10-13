import { bearerMatches } from './crypto.js'

export function connectorConfig(env) {
  const apiKey = (env.WHATSAPP_CONNECTOR_API_KEY || '').trim()
  if (!apiKey) throw new Error('WHATSAPP_CONNECTOR_API_KEY is required')
  return { apiKey, host: env.WHATSAPP_CONNECTOR_HOST || '127.0.0.1' }
}

export function authenticateWith(apiKey) {
  if (!apiKey) throw new Error('Connector authentication requires an API key')
  return (req, res, next) => {
    if (!bearerMatches(req.headers.authorization, apiKey)) {
      return res.status(401).json({ code: 401, message: 'unauthorized' })
    }
    next()
  }
}
