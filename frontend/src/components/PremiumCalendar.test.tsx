import { act, render } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { CalendarGrid } from './PremiumCalendar'

it('switches the week grid to three navigable days on a mobile viewport', () => {
  let listener: (() => void) | undefined
  const media = {
    matches: false,
    media: '(max-width: 767px)',
    onchange: null,
    addEventListener: vi.fn((_type: string, callback: () => void) => { listener = callback }),
    removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  }
  vi.spyOn(window, 'matchMedia').mockReturnValue(media as MediaQueryList)
  const {container} = render(<CalendarGrid events={[]} weekStart={new Date(2026,7,17)} onOpen={()=>undefined} onDelete={()=>undefined} onCreate={()=>undefined}/>)
  expect(container.querySelectorAll('.week-grid-head > div')).toHaveLength(7)

  act(() => {
    media.matches = true
    listener?.()
  })

  expect(container.querySelectorAll('.week-grid-head > div')).toHaveLength(3)
  expect(container.querySelector('.week-grid-head')).toHaveStyle({gridTemplateColumns:'54px repeat(3, minmax(0, 1fr))'})
})
