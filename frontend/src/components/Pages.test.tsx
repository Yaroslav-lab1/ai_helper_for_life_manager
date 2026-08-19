import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => vi.fn())
vi.mock('../lib/api', async importOriginal => {
  const original = await importOriginal<typeof import('../lib/api')>()
  return {...original, api: apiMock}
})

import { HabitsPage, TasksPage } from './Pages'

beforeEach(() => {
  apiMock.mockReset()
  apiMock.mockImplementation(async (path: string) => path === '/tasks' ? [] : undefined)
})

it('creates a task with the unchanged datetime-local wall clock', async () => {
  const user = userEvent.setup()
  render(<TasksPage timezone="Europe/Moscow" onChanged={() => undefined}/>)
  await user.click(await screen.findByRole('button', {name:/Новая задача/}))
  await user.type(screen.getByLabelText('Что нужно сделать?'), 'DST-safe task')
  fireEvent.change(screen.getByLabelText('Срок'), {target:{value:'2026-10-25T01:30'}})
  await user.click(screen.getByRole('button', {name:'Создать задачу'}))

  await waitFor(() => expect(apiMock).toHaveBeenCalledWith('/tasks', expect.objectContaining({method:'POST'})))
  const create = apiMock.mock.calls.find(([path, options]) => path === '/tasks' && options?.method === 'POST')
  expect(JSON.parse(create?.[1]?.body as string).due_at).toBe('2026-10-25T01:30:00')
})

it('checks in a habit using the profile date near UTC midnight', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-08-19T21:30:00Z'))
  apiMock.mockImplementation(async (path: string) => path === '/habits' ? [{
    id:3,title:'Прогулка',emoji:'🚶',cadence:'daily',target_per_week:7,color:'#238760',archived:false,
    current_streak:0,best_streak:0,completed_today:false,week_count:0,
  }] : undefined)
  render(<HabitsPage timezone="Europe/Moscow" onChanged={()=>undefined}/>)
  await act(async () => undefined)
  fireEvent.click(screen.getByRole('button', {name:/Отметить выполнение/}))
  await act(async () => undefined)

  expect(apiMock).toHaveBeenCalledWith('/habits/3/checkins', {
    method:'POST',
    body:JSON.stringify({checkin_date:'2026-08-20'}),
  })
  vi.useRealTimers()
})
