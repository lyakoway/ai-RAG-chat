/**
 * Initial-preference resolution with URL override.
 *
 * Priority: URL query param (?lang=en&theme=light) → localStorage → fallback.
 * A valid URL value is persisted to localStorage so it "sticks", and the param
 * is later stripped from the address bar (see stripPrefParams) so the user's
 * own toggles stay in control after the first load.
 */
export function initialPref<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): T {
  const isValid = (v: string | null): v is T => !!v && (allowed as readonly string[]).includes(v)

  try {
    const fromUrl = new URLSearchParams(window.location.search).get(key)
    if (isValid(fromUrl)) {
      localStorage.setItem(key, fromUrl)
      return fromUrl
    }
    const stored = localStorage.getItem(key)
    if (isValid(stored)) return stored
  } catch {
    /* localStorage / URL unavailable — fall through */
  }
  return fallback
}

/** Remove the given query params from the URL without a reload. */
export function stripPrefParams(keys: string[]): void {
  try {
    const url = new URL(window.location.href)
    let changed = false
    for (const k of keys) {
      if (url.searchParams.has(k)) {
        url.searchParams.delete(k)
        changed = true
      }
    }
    if (changed) {
      const qs = url.searchParams.toString()
      window.history.replaceState({}, '', url.pathname + (qs ? `?${qs}` : '') + url.hash)
    }
  } catch {
    /* ignore */
  }
}
