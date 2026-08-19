import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({api:vi.fn(),stream:vi.fn()}))
vi.mock('../lib/api', () => ({api:transport.api,streamAIChat:transport.stream}))

import { ChatPanel } from './ChatPanel'

let consent = {required:false,active:true,policy_version:'2026-01'}
let conversations: {id:number;title:string;created_at:string;updated_at:string}[] = []
let initialMessages: unknown[] = []

beforeEach(() => {
  consent = {required:false,active:true,policy_version:'2026-01'}
  conversations = []
  initialMessages = []
  transport.stream.mockReset()
  transport.api.mockReset()
  transport.api.mockImplementation(async (path: string) => {
    if (path === '/ai/status') return {available:true,provider:'ollama',model:'local',message:'ok'}
    if (path === '/settings/ai-consent') return consent
    if (path === '/ai/conversations') return conversations
    if (path.includes('/messages')) return initialMessages
    return undefined
  })
})

it('blocks chat behind explicit AI consent when the provider requires it', async () => {
  consent = {required:true,active:false,policy_version:'2026-01'}
  render(<ChatPanel onClose={()=>undefined}/>)

  expect(await screen.findByRole('heading', {name:'Нужно ваше согласие'})).toBeInTheDocument()
  expect(screen.queryByPlaceholderText(/Спросите о планах/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', {name:'Согласиться и продолжить'})).toBeDisabled()
})

it('renders streamed chunks and replaces them with the final done payload', async () => {
  transport.stream.mockImplementation(async (_payload, onEvent) => {
    onEvent({event:'chunk',text:'Привет'})
    onEvent({event:'chunk',text:', мир'})
    onEvent({event:'done',text:'Готовый ответ',message_id:10,conversation_id:4})
  })
  const actor = userEvent.setup()
  render(<ChatPanel onClose={()=>undefined}/>)
  const input = await screen.findByPlaceholderText(/Спросите о планах/)
  await actor.type(input, 'Мой вопрос')
  fireEvent.keyDown(input, {key:'Enter'})

  expect(await screen.findByText('Готовый ответ')).toBeInTheDocument()
  expect(screen.queryByText('Привет, мир')).not.toBeInTheDocument()
})

it('shows an SSE error and retries the last user message without duplicating it', async () => {
  transport.stream
    .mockRejectedValueOnce(new Error('Поток оборвался'))
    .mockImplementationOnce(async (_payload, onEvent) => onEvent({event:'done',text:'Ответ после повтора'}))
  const actor = userEvent.setup()
  render(<ChatPanel onClose={()=>undefined}/>)
  const input = await screen.findByPlaceholderText(/Спросите о планах/)
  await actor.type(input, 'Повтори')
  fireEvent.keyDown(input, {key:'Enter'})
  await actor.click(await screen.findByRole('button', {name:/Повторить/}))

  expect(await screen.findByText('Ответ после повтора')).toBeInTheDocument()
  expect(screen.getAllByText('Повтори')).toHaveLength(1)
  expect(transport.stream).toHaveBeenCalledTimes(2)
})

it('requires and sends explicit confirmation for an AI action proposal', async () => {
  conversations = [{id:2,title:'План',created_at:'2026-01-01',updated_at:'2026-01-01'}]
  initialMessages = [{id:1,role:'assistant',content:'Предлагаю действие',proposals:[{id:9,type:'task_create',title:'Создать задачу',description:'Добавить задачу',status:'pending',requires_confirmation:true}]}]
  transport.api.mockImplementation(async (path: string) => {
    if (path === '/ai/status') return {available:true,provider:'ollama',model:'local',message:'ok'}
    if (path === '/settings/ai-consent') return consent
    if (path === '/ai/conversations') return conversations
    if (path.endsWith('/messages')) return initialMessages
    if (path === '/ai/action-proposals/9/confirm') return {...(initialMessages[0] as {proposals:{id:number}[]}).proposals[0],status:'confirmed'}
    return undefined
  })
  const actor = userEvent.setup()
  render(<ChatPanel onClose={()=>undefined}/>)
  await actor.click(await screen.findByRole('button', {name:'Подтвердить'}))

  expect(await screen.findByText('Подтверждено')).toBeInTheDocument()
  expect(transport.api).toHaveBeenCalledWith('/ai/action-proposals/9/confirm', {method:'POST'})
})
