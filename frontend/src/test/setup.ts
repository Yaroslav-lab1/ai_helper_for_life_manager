import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

class MemoryStorage implements Storage {
  private values = new Map<string, string>()
  get length() { return this.values.size }
  clear() { this.values.clear() }
  getItem(key: string) { return this.values.get(key) ?? null }
  key(index: number) { return [...this.values.keys()][index] ?? null }
  removeItem(key: string) { this.values.delete(key) }
  setItem(key: string, value: string) { this.values.set(key, String(value)) }
}

// Node can expose its own disabled experimental localStorage. Keep browser tests deterministic.
Object.defineProperty(globalThis, 'localStorage', {configurable:true,value:new MemoryStorage()})
Object.defineProperty(globalThis, 'sessionStorage', {configurable:true,value:new MemoryStorage()})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  sessionStorage.clear()
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.removeAttribute('style')
})

Object.defineProperty(window, 'scrollTo', { configurable: true, value: vi.fn() })
Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })

if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: () => ({
      matches: false,
      media: '',
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  })
}
