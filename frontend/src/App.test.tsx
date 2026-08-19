import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'

vi.mock('./components/PremiumDashboard', () => ({default:()=> <div>Dashboard ready</div>}))
vi.mock('./components/PremiumCalendar', () => ({default:()=> <div>Calendar ready</div>}))
vi.mock('./components/Pages', () => ({
  AnalyticsPage:()=>null, GoalsPage:()=>null, HabitsPage:()=>null, SettingsPage:()=>null, TasksPage:()=>null,
}))
vi.mock('./components/PremiumShell', () => ({
  AIAssistantPanel:()=>null,
  AppHeader:()=>null,
  CalendarSidebar:()=>null,
  Logo:()=> <div>Axel logo</div>,
  MobileScrim:()=>null,
  Sidebar:()=>null,
}))

import App from './App'

const user = {id:1,email:'user@example.com',name:'User',timezone:'Europe/Moscow',avatar_color:'#000',email_verified:true,created_at:'2026-01-01T00:00:00Z'}
const settings = {theme:'light',language:'ru',notifications_enabled:true,daily_digest_time:'08:00',workday_start:'09:00',workday_end:'18:00',weekly_focus_hours:20,compact_mode:false,ai_tone:'supportive'}
const json = (body: unknown, status=200) => new Response(JSON.stringify(body), {status,headers:{'Content-Type':'application/json'}})

beforeEach(() => {
  window.history.replaceState({}, '', '/')
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/auth/login')) return json({access_token:'access',refresh_token:'refresh',expires_in:900,user})
    if (url.endsWith('/auth/me')) return json(user)
    if (url.endsWith('/settings')) return json(settings)
    return json({detail:'not found'}, 404)
  }))
})

it('logs in, stores the session, and applies the profile theme', async () => {
  const actor = userEvent.setup()
  render(<App/>)
  await actor.type(screen.getByLabelText('Email'), 'user@example.com')
  await actor.type(screen.getByLabelText('Пароль'), 'password')
  await actor.click(screen.getByRole('button', {name:/Войти в Axel One/}))

  expect(await screen.findByText('Dashboard ready')).toBeInTheDocument()
  expect(sessionStorage.getItem('axel_access')).toBe('access')
  await waitFor(() => expect(document.documentElement.dataset.theme).toBe('light'))
  expect(localStorage.getItem('axel_theme')).toBe('light')
})

it('restores an existing access session before showing the application', async () => {
  sessionStorage.setItem('axel_access', 'existing-access')
  render(<App/>)

  expect(await screen.findByText('Dashboard ready')).toBeInTheDocument()
  const calls = vi.mocked(fetch).mock.calls.map(([url]) => String(url))
  expect(calls.some(url => url.endsWith('/auth/me'))).toBe(true)
  expect(calls.some(url => url.endsWith('/settings'))).toBe(true)
})
