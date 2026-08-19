import { describe, expect, it, vi } from 'vitest'
import { bindTheme, persistTheme, storedTheme } from './theme'

function media(initial: boolean) {
  let listener: (() => void) | undefined
  return {
    query: {
      matches: initial,
      addEventListener: vi.fn((_type: string, next: () => void) => { listener = next }),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList,
    change(matches: boolean) {
      Object.defineProperty(this.query, 'matches', { configurable: true, value: matches })
      listener?.()
    },
  }
}

describe('theme binding', () => {
  it.each(['light', 'dark'] as const)('applies and persists %s mode', preference => {
    const match = media(false)
    bindTheme(preference, document.documentElement, match.query)
    persistTheme(preference)
    expect(document.documentElement.dataset.theme).toBe(preference)
    expect(document.documentElement.style.colorScheme).toBe(preference)
    expect(storedTheme()).toBe(preference)
  })

  it('tracks operating-system changes in system mode and removes its listener', () => {
    const match = media(false)
    const unbind = bindTheme('system', document.documentElement, match.query)
    expect(document.documentElement.dataset.theme).toBe('light')
    match.change(true)
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.style.colorScheme).toBe('dark')
    unbind()
    expect(match.query.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function))
  })

  it('restores a valid local preference and rejects stale values', () => {
    expect(storedTheme()).toBe('dark')
    localStorage.setItem('axel_theme', 'dark')
    expect(storedTheme()).toBe('dark')
    localStorage.setItem('axel_theme', 'sepia')
    expect(storedTheme()).toBe('dark')
  })
})
