import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const css = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8')

test('mobile calendar drops the 216px sidebar column', () => {
  assert.match(css, /\.calendar-workspace\{width:100%;grid-template-columns:minmax\(0,1fr\)\}/)
  assert.match(css, /\.calendar-sidebar\{display:none\}/)
  assert.match(css, /\.calendar-main\{width:100%;min-width:0\}/)
  assert.ok(css.lastIndexOf('@media(max-width:899px)') > css.lastIndexOf('@media(max-width:1199px)'))
})

test('narrow month view can shrink to the viewport', () => {
  assert.match(css, /\.month-calendar\{min-width:0\}/)
  assert.match(css, /\.month-grid\{grid-template-columns:repeat\(7,minmax\(0,1fr\)\)/)
})
