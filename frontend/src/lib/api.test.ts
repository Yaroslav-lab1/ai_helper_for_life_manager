import { beforeEach, describe, expect, it, vi } from 'vitest'

const json = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status,
  headers: { 'Content-Type': 'application/json' },
})

describe('authenticated API transport', () => {
  beforeEach(() => vi.resetModules())

  it('coalesces parallel 401 responses into one refresh and retries all requests', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/refresh')) {
        await new Promise(resolve => setTimeout(resolve, 5))
        return json({ access_token: 'new-access', refresh_token: 'new-refresh', expires_in: 900 })
      }
      const authorization = new Headers(init?.headers).get('Authorization')
      return authorization === 'Bearer new-access' ? json({ path: url }) : json({ detail: 'expired' }, 401)
    })
    vi.stubGlobal('fetch', fetchMock)
    const { api, session } = await import('./api')
    session.save({access_token:'old-access',refresh_token:'old-refresh',expires_in:1,user:null as never})

    const result = await Promise.all([api('/tasks'), api('/events'), api('/dashboard')])

    expect(result).toHaveLength(3)
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/auth/refresh'))).toHaveLength(1)
    expect(session.access).toBe('new-access')
  })

  it('clears one failed token family once and never retries refresh recursively', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/auth/refresh')
      ? json({detail:'revoked'}, 401)
      : json({detail:'expired'}, 401))
    vi.stubGlobal('fetch', fetchMock)
    const { api, session } = await import('./api')
    session.save({access_token:'old-access',refresh_token:'old-refresh',expires_in:1,user:null as never})
    const clear = vi.spyOn(session, 'clear')

    const results = await Promise.allSettled([api('/tasks'), api('/events'), api('/dashboard')])

    expect(results.every(result => result.status === 'rejected')).toBe(true)
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/auth/refresh'))).toHaveLength(1)
    expect(clear).toHaveBeenCalledTimes(1)
  })

  it('parses SSE chunk and done events and surfaces an SSE error', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response([
        'data: {"event":"chunk","text":"Привет"}\n\n',
        'data: {"event":"done","text":"Привет!","message_id":7}\n\n',
      ].join(''), {status:200,headers:{'Content-Type':'text/event-stream'}}))
      .mockResolvedValueOnce(new Response('data: {"event":"error","message":"provider down"}\n\n', {status:200,headers:{'Content-Type':'text/event-stream'}}))
    vi.stubGlobal('fetch', fetchMock)
    const { streamAIChat } = await import('./api')
    const events: string[] = []

    await streamAIChat({message:'test'}, event => events.push(`${event.event}:${event.text||''}`))
    expect(events).toEqual(['chunk:Привет', 'done:Привет!'])
    await expect(streamAIChat({message:'test'}, () => undefined)).rejects.toThrow('provider down')
  })
})
