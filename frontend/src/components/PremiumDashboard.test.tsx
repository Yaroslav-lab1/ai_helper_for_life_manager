import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())
vi.mock('../lib/api', () => ({api:apiMock}))

import PremiumDashboardPage from './PremiumDashboard'

const dashboard = {
  greeting:'Добрый день, User',date_label:'19.08.2026',focus_score:80,tasks_due:0,completed_today:0,habit_rate:0,
  events_today:[],priority_tasks:[],goals:[],habits:[],
  overload:{level:'low',score:10,scheduled_minutes:0,open_tasks:0,urgent_tasks:0,signals:[],suggestion:'Буфер есть'},
}

beforeEach(() => {
  apiMock.mockReset()
  apiMock.mockImplementation(async (path: string) => path === '/dashboard' ? dashboard : path === '/balance' ? [] : undefined)
})

it('submits the dashboard quick task without a Moscow-to-UTC double shift', async () => {
  const actor = userEvent.setup()
  render(<PremiumDashboardPage timezone="Europe/Moscow" navigate={()=>undefined} onChanged={()=>undefined}/>)
  await actor.click(await screen.findByRole('button', {name:/Быстрая задача/}))
  await actor.type(screen.getByLabelText('Что нужно сделать?'), 'Quick task')
  fireEvent.change(screen.getByLabelText('Срок'), {target:{value:'2026-08-20T09:15'}})
  fireEvent.change(screen.getByLabelText('Напомнить'), {target:{value:'2026-08-20T08:45'}})
  await actor.click(screen.getByRole('button', {name:'Создать'}))

  await waitFor(() => expect(apiMock).toHaveBeenCalledWith('/tasks', expect.objectContaining({method:'POST'})))
  const create = apiMock.mock.calls.find(([path, options]) => path === '/tasks' && options?.method === 'POST')
  expect(JSON.parse(create?.[1]?.body as string)).toEqual(expect.objectContaining({
    due_at:'2026-08-20T09:15:00',
    reminder_at:'2026-08-20T08:45:00',
  }))
})
