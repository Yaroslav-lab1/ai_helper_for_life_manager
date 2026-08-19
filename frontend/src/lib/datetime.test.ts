import { describe, expect, it } from 'vitest'
import { calendarDateInTimeZone, dateTimeLocalValue, naiveDateTimeFromInput } from './datetime'

describe('calendarDateInTimeZone', () => {
  it('uses the profile day east of UTC near midnight', () => {
    const instant = new Date('2026-08-19T21:30:00Z')
    expect(calendarDateInTimeZone('Europe/Moscow', instant)).toBe('2026-08-20')
  })

  it('uses the previous profile day for a negative UTC offset', () => {
    const instant = new Date('2026-08-19T02:30:00Z')
    expect(calendarDateInTimeZone('America/Los_Angeles', instant)).toBe('2026-08-18')
  })
})

it('preserves a datetime-local wall clock without converting it to UTC', () => {
  expect(naiveDateTimeFromInput('2026-10-25T01:30')).toBe('2026-10-25T01:30:00')
})

it('formats an initial datetime-local value in the profile timezone', () => {
  expect(dateTimeLocalValue(new Date('2026-08-19T21:30:00Z'), 'Europe/Moscow')).toBe('2026-08-20T00:30')
})
