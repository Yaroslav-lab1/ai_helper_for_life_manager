import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const api = await readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8')
const chatPanel = await readFile(new URL('../src/components/ChatPanel.tsx', import.meta.url), 'utf8')
const calendarPlanner = await readFile(new URL('../src/components/CalendarPlanner.tsx', import.meta.url), 'utf8')
const premiumShell = await readFile(new URL('../src/components/PremiumShell.tsx', import.meta.url), 'utf8')

test('all frontend chats use the unified streaming AI endpoint', () => {
  assert.match(api, /fetch\(`\$\{API_URL\}\/ai\/chat`/)
  assert.doesNotMatch(api, /\/chat\/stream/)
  assert.doesNotMatch(api, /export async function streamChat/)
  assert.match(chatPanel, /streamAIChat\(\{message,conversation_id:conversationId\}/)
  assert.match(calendarPlanner, /streamAIChat\(\{message,conversation_id:conversationId,selected_date:selectedDate,auto_execute_actions:true\}/)
  assert.match(calendarPlanner, /\/ai\/conversations\/\$\{saved\}\/messages/)
})

test('legacy assistant implementation and legacy history are removed', () => {
  assert.doesNotMatch(calendarPlanner, /\/chat\/history|streamChat/)
  assert.doesNotMatch(premiumShell, /\/chat\/history|streamChat|LegacyAIAssistantPanel/)
  assert.match(premiumShell, /return open\?<ChatPanel/)
})

test('calendar chat requests explicit GigaChat consent in place', () => {
  assert.match(calendarPlanner, /api<AIConsent>\('\/settings\/ai-consent'\)/)
  assert.match(calendarPlanner, /consent\.required&&!consent\.active/)
  assert.match(calendarPlanner, /Согласиться и продолжить/)
  assert.match(calendarPlanner, /Я явно соглашаюсь на передачу описанного контекста/)
})

test('visible chat message is finalized with server-sanitized LLM text', () => {
  assert.match(chatPanel, /content:event\.text\?\?item\.content,proposals:event\.proposals/)
  assert.match(calendarPlanner, /content:event\.text\?\?item\.content,proposals:event\.proposals/)
})

test('calendar action proposals require confirmation and refresh the calendar', () => {
  assert.match(calendarPlanner, /updateProposal\(proposal,'confirm'\)/)
  assert.match(calendarPlanner, /Подтвердить/)
  assert.match(calendarPlanner, /if\(action==='confirm'\)onCalendarChanged\(\)/)
})

test('calendar chat automatically executes explicit calendar proposals', () => {
  assert.match(calendarPlanner, /auto_execute_actions:true/)
  assert.match(calendarPlanner, /proposal\.type==='calendar_action_proposal'&&proposal\.status==='confirmed'/)
  assert.match(calendarPlanner, /if\(event\.action_error\)setError\(event\.action_error\)/)
})

test('retry replaces the failed request instead of duplicating it', () => {
  assert.match(chatPanel, /send\(last\.content,true\)/)
  assert.match(calendarPlanner, /send\(lastMessage,true\)/)
})
