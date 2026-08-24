import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'

const apiMock=vi.hoisted(()=>vi.fn())
vi.mock('../lib/api',()=>({api:apiMock}))
vi.mock('./CalendarPlanner',()=>({
  AIPlannerPanel:({onClose}:{onClose:()=>void})=><aside data-testid="ai-planner"><button onClick={onClose}>Закрыть AI-планировщик</button></aside>,
  RecommendationCard:()=>null,
}))

import PremiumCalendarPage, { CalendarGrid } from './PremiumCalendar'

beforeEach(()=>{
  apiMock.mockImplementation(async(path:string)=>path.startsWith('/events')?[]:{points:[]})
})

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

it('keeps the calendar expanded without a paid AI entitlement and delegates the PRO offer',async()=>{
  const open=vi.fn()
  const {container}=render(<PremiumCalendarPage view="week" onView={()=>undefined} plannerOpen={false} onPlannerOpen={open} onPlannerClose={()=>undefined} onChanged={()=>undefined} canUseAI={false}/>)
  expect(container.querySelector('.calendar-workspace')).toHaveClass('planner-collapsed')
  expect(container.querySelector('.calendar-workspace')).not.toHaveClass('planner-open')
  expect(screen.queryByTestId('ai-planner')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button',{name:'AI-план · PRO'}))
  expect(open).toHaveBeenCalledOnce()
})

it('adds the planner column only while a paid user has the planner open',async()=>{
  const close=vi.fn()
  const props={view:'week' as const,onView:()=>undefined,onPlannerOpen:()=>undefined,onPlannerClose:close,onChanged:()=>undefined,canUseAI:true}
  const {container,rerender}=render(<PremiumCalendarPage {...props} plannerOpen={false}/>)
  expect(container.querySelector('.calendar-workspace')).toHaveClass('planner-collapsed')
  expect(screen.queryByTestId('ai-planner')).not.toBeInTheDocument()

  rerender(<PremiumCalendarPage {...props} plannerOpen/>)
  expect(container.querySelector('.calendar-workspace')).toHaveClass('planner-open')
  expect(screen.getByTestId('ai-planner')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button',{name:'Закрыть AI-планировщик'}))
  expect(close).toHaveBeenCalledOnce()
})
