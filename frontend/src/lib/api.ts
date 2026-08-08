import type { Tokens } from '../types'

const API_URL = import.meta.env.VITE_API_URL || '/api/v1'

export const session = {
  get access() { return sessionStorage.getItem('axel_access') },
  get refresh() { return sessionStorage.getItem('axel_refresh') },
  save(tokens: Tokens) {
    sessionStorage.setItem('axel_access', tokens.access_token)
    if(tokens.refresh_token)sessionStorage.setItem('axel_refresh', tokens.refresh_token)
    else sessionStorage.removeItem('axel_refresh')
  },
  clear() { sessionStorage.removeItem('axel_access'); sessionStorage.removeItem('axel_refresh') },
}

async function renew(): Promise<boolean> {
  const response = await fetch(`${API_URL}/auth/refresh`, {
    method: 'POST', credentials:'include', headers: {'Content-Type':'application/json'}, body: JSON.stringify({refresh_token: session.refresh||null}),
  })
  if (!response.ok) { session.clear(); return false }
  session.save(await response.json())
  return true
}

export async function api<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (session.access) headers.set('Authorization', `Bearer ${session.access}`)
  const response = await fetch(`${API_URL}${path}`, {...options, credentials:'include', headers})
  if (response.status === 401 && retry && await renew()) return api<T>(path, options, false)
  if (!response.ok) {
    let message = 'Не удалось выполнить запрос'
    try { const payload = await response.json(); message = payload.detail || message } catch { /* empty response */ }
    throw new Error(typeof message === 'string' ? message : 'Проверьте введённые данные')
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export async function downloadAccountExport(): Promise<void> {
  const response = await fetch(`${API_URL}/account/export`, {
    credentials:'include',
    headers: {Authorization:`Bearer ${session.access}`},
  })
  if (response.status === 401 && await renew()) return downloadAccountExport()
  if (!response.ok) throw new Error('Не удалось подготовить экспорт')
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'axel-one-export.json'
  anchor.click()
  URL.revokeObjectURL(url)
}

export type AIStreamEvent = {
  event:'meta'|'chunk'|'done'|'error'
  text?:string
  message?:string
  conversation_id?:number
  message_id?:number
  proposals?:import('../types').AIActionProposal[]
  action_error?:string|null
}

export async function streamAIChat(
  payload: {message:string;conversation_id?:number;selected_date?:string;auto_execute_actions?:boolean},
  onEvent: (event:AIStreamEvent)=>void,
  signal?: AbortSignal,
  retry = true,
): Promise<void> {
  const response = await fetch(`${API_URL}/ai/chat`, {
    method:'POST', credentials:'include', signal,
    headers:{'Content-Type':'application/json', Authorization:`Bearer ${session.access}`},
    body:JSON.stringify(payload),
  })
  if (response.status === 401 && retry && await renew()) return streamAIChat(payload,onEvent,signal,false)
  if (!response.ok || !response.body) {
    let message='Чат временно недоступен'
    try { const data=await response.json(); if(typeof data.detail==='string')message=data.detail } catch { /* empty */ }
    throw new Error(message)
  }
  const reader=response.body.getReader();const decoder=new TextDecoder();let buffer=''
  while(true){
    const {done,value}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done})
    const blocks=buffer.split(/\r?\n\r?\n/);buffer=blocks.pop()||''
    for(const block of blocks){
      const data=block.split(/\r?\n/).filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trim()).join('')
      if(!data)continue
      const event=JSON.parse(data) as AIStreamEvent;onEvent(event)
      if(event.event==='error')throw new Error(event.message||'Не удалось получить ответ')
    }
    if(done)break
  }
}
