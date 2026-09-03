export type ChatLanguageStore = {
  getLanguage: (chatTitle: string) => Promise<string>
  setLanguage: (chatTitle: string, targetLanguage: string) => Promise<string>
}

export async function resolveTargetLanguage(store: ChatLanguageStore, chatTitle: string): Promise<string> {
  return store.getLanguage(chatTitle)
}

export async function updateTargetLanguage(
  store: ChatLanguageStore,
  chatTitle: string,
  targetLanguage: string,
): Promise<string> {
  return store.setLanguage(chatTitle, targetLanguage)
}
