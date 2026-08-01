import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('../src/components/Pages.tsx', import.meta.url), 'utf8')

test('goal planner requests current AI consent before generation', () => {
  assert.match(source, /api<AIConsent>\('\/settings\/ai-consent'\)/)
  assert.match(source, /consent\.required&&!consent\.active/)
  assert.match(source, /setConsentRequest\(\{goal,regenerate,consent\}\)/)
})

test('GigaChat consent is explicit and continues plan generation', () => {
  assert.match(source, /const \[checked,setChecked\]=useState\(false\)/)
  assert.match(source, /Согласиться и составить план/)
  assert.match(source, /void runGenerate\(request\.goal,request\.regenerate\)/)
  assert.doesNotMatch(source, /если Ollama уже готова/)
  assert.doesNotMatch(source, /AI-план готовится автоматически/)
})
