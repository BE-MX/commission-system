/** Public mount inside Ark; persisted catalog/source asset paths remain unchanged. */
export const WORKBENCH_PATH = '/api/colorwork/workbench';

export function workbenchUrl(path: string | null | undefined): string {
  if (!path) return "";
  if (!path.startsWith('/') || path.startsWith('//') ||
      path === WORKBENCH_PATH || path.startsWith(`${WORKBENCH_PATH}/`)) return path;
  return `${WORKBENCH_PATH}${path}`;
}

export function workbenchFetch(path: string, init?: RequestInit) {
  return fetch(workbenchUrl(path), init);
}
