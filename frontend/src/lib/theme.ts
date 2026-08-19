export type ThemePreference = 'light' | 'dark' | 'system'
export type ResolvedTheme = Exclude<ThemePreference, 'system'>

export const THEME_STORAGE_KEY = 'axel_theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

export function storedTheme(storage: Pick<Storage, 'getItem'> = localStorage): ThemePreference {
  const value = storage.getItem(THEME_STORAGE_KEY)
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'dark'
}

export function resolveTheme(preference: ThemePreference, prefersDark: boolean): ResolvedTheme {
  return preference === 'system' ? (prefersDark ? 'dark' : 'light') : preference
}

export function applyResolvedTheme(theme: ResolvedTheme, root: HTMLElement = document.documentElement): void {
  root.dataset.theme = theme
  root.style.colorScheme = theme
}

export function persistTheme(preference: ThemePreference, storage: Pick<Storage, 'setItem'> = localStorage): void {
  storage.setItem(THEME_STORAGE_KEY, preference)
}

/** Apply a preference and keep system mode synchronized with OS changes. */
export function bindTheme(
  preference: ThemePreference,
  root: HTMLElement = document.documentElement,
  media: MediaQueryList = window.matchMedia(DARK_QUERY),
): () => void {
  const update = () => applyResolvedTheme(resolveTheme(preference, media.matches), root)
  update()
  if (preference !== 'system') return () => undefined
  media.addEventListener('change', update)
  return () => media.removeEventListener('change', update)
}
