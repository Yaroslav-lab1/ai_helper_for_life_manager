import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8')
const shell = await readFile(new URL('../src/components/PremiumShell.tsx', import.meta.url), 'utf8')
const requisites = await readFile(new URL('../src/components/RequisitesPage.tsx', import.meta.url), 'utf8')

test('requisites route stays inside the current application shell', () => {
  assert.match(app, /window\.history\.pushState\(\{axelRoute:'requisites'\},'', '\/requisites'\)/)
  assert.match(app, /window\.addEventListener\('popstate',syncRoute\)/)
  assert.match(app, /<RequisitesPage onBack=\{closeRequisites\}\/>/)
  assert.doesNotMatch(requisites, /window\.location\.assign/)
  assert.doesNotMatch(requisites, /<a href="\/" className="requisites-back"/)
})

test('both visible requisites links use the in-app route', () => {
  assert.match(app, /href="\/requisites" onClick=\{event=>\{event\.preventDefault\(\);onRequisites\(\)\}\}>Контакты и реквизиты/)
  assert.match(shell, /href="\/requisites" onClick=\{event=>\{event\.preventDefault\(\);onRequisites\(\)\}\}/)
})
