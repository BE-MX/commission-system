import { env } from 'cloudflare:workers';
import { createCosFiles } from './cos-files';

export function getFiles() {
  if (!env.ARK_STORAGE_ENDPOINT) return env.FILES;
  if (!env.ARK_STORAGE_SECRET) throw new Error('Cloud storage secret is missing');
  return createCosFiles({ endpoint: env.ARK_STORAGE_ENDPOINT, secret: env.ARK_STORAGE_SECRET, staging: env.FILES });
}
