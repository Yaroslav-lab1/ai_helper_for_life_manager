const dateParts = (date: Date, timeZone: string) => {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date)
  return Object.fromEntries(parts.map(part => [part.type, part.value]))
}

/** Calendar date for an instant in an explicit IANA timezone. */
export function calendarDateInTimeZone(timeZone: string, date = new Date()): string {
  const parts = dateParts(date, timeZone)
  return `${parts.year}-${parts.month}-${parts.day}`
}

/** Value suitable for an HTML datetime-local input in an explicit profile timezone. */
export function dateTimeLocalValue(date = new Date(), timeZone?: string): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  if (timeZone) {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone,
      year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit',
      hourCycle:'h23',
    }).formatToParts(date)
    const values = Object.fromEntries(parts.map(part => [part.type, part.value]))
    return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}`
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/**
 * Preserve the wall-clock value from datetime-local as a naive ISO datetime.
 * The backend interprets this value in the authenticated user's IANA timezone.
 */
export function naiveDateTimeFromInput(value: string): string {
  if (!value) return value
  return value.length === 16 ? `${value}:00` : value
}
