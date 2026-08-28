import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'

const apiMock=vi.hoisted(()=>vi.fn())
vi.mock('../lib/api',()=>({api:apiMock}))

import { BillingPage, BillingReturnPage, SubscriptionUpsell } from './BillingPage'
import type { BillingCatalog, Subscription } from '../types'

const catalog:BillingCatalog={checkout_available:true,checkout_unavailable_message:null,recurring_payments_available:true,plans:[
  {code:'free',name:'FREE',available:true,currency:'RUB',monthly_price:'0.00',yearly_price:'0.00',yearly_monthly_equivalent:'0.00',yearly_savings:'0.00',yearly_discount_percent:17,features:['Календарь','Задачи'],entitlements:['calendar','tasks']},
  {code:'pro',name:'PRO',available:true,currency:'RUB',monthly_price:'399.00',yearly_price:'3974.04',yearly_monthly_equivalent:'331.17',yearly_savings:'813.96',yearly_discount_percent:17,features:['Всё из FREE','AI-ассистент'],entitlements:['calendar','ai_assistant']},
  {code:'executive',name:'EXECUTIVE',available:true,currency:'RUB',monthly_price:'990.00',yearly_price:'9860.40',yearly_monthly_equivalent:'821.70',yearly_savings:'2019.60',yearly_discount_percent:17,features:['Всё из PRO','Архитектура Executive-возможностей'],entitlements:['ai_assistant','life_report']},
]}
const free:Subscription={plan_code:'free',status:'free',effective_plan_code:'free',entitlements:['calendar'],cancel_at_period_end:false,retry_count:0}
const pro:Subscription={plan_code:'pro',billing_interval:'monthly',status:'active',effective_plan_code:'pro',entitlements:['calendar','ai_assistant'],current_period_start:'2026-08-01T00:00:00Z',current_period_end:'2026-09-01T00:00:00Z',next_billing_at:'2026-09-01T00:00:00Z',cancel_at_period_end:false,retry_count:0}

beforeEach(()=>{apiMock.mockReset();sessionStorage.clear();window.history.replaceState({},'', '/')})

it('renders three server plans and switches monthly/yearly prices with 17% savings',async()=>{
  apiMock.mockImplementation(async(path:string)=>path==='/billing/plans'?catalog:free)
  render(<BillingPage subscription={free} onSubscription={()=>undefined}/>)
  expect(await screen.findByRole('heading',{name:'FREE'})).toBeInTheDocument()
  expect(screen.getByRole('heading',{name:'PRO'})).toBeInTheDocument()
  expect(screen.getByRole('heading',{name:'EXECUTIVE'})).toBeInTheDocument()
  expect(screen.getByText('Самый популярный')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button',{name:/Годовая оплата/}))
  expect(screen.getByRole('button',{name:/Годовая оплата/})).toHaveAttribute('aria-pressed','true')
  expect(screen.getByText(/Экономия.*813,96/)).toBeInTheDocument()
  expect(screen.getByRole('button',{name:/Попробовать PRO, годовая оплата/})).toBeInTheDocument()
})

it('redirects checkout only to the confirmation URL returned by backend',async()=>{
  const redirect=vi.fn()
  apiMock.mockImplementation(async(path:string)=>{
    if(path==='/billing/plans')return catalog
    if(path==='/billing/subscription')return free
    if(path==='/billing/checkout')return {payment_id:42,confirmation_url:'https://yookassa.test/safe-confirm'}
  })
  render(<BillingPage subscription={free} onSubscription={()=>undefined} redirect={redirect}/>)
  await userEvent.click(await screen.findByRole('button',{name:/Попробовать PRO, месячная оплата/}))
  await waitFor(()=>expect(redirect).toHaveBeenCalledWith('https://yookassa.test/safe-confirm'))
  expect(sessionStorage.getItem('axel_billing_payment_id')).toBe('42')
  expect(apiMock).toHaveBeenCalledWith('/billing/checkout',{method:'POST',body:JSON.stringify({plan_code:'pro',billing_interval:'monthly'})})
})

it('explains disabled payments before checkout and does not call the endpoint',async()=>{
  const unavailable={...catalog,checkout_available:false,checkout_unavailable_message:'Оплата временно отключена администратором.'}
  apiMock.mockImplementation(async(path:string)=>path==='/billing/plans'?unavailable:free)
  render(<BillingPage subscription={free} onSubscription={()=>undefined}/>)
  expect(await screen.findByText('Оплата пока недоступна')).toBeInTheDocument()
  expect(screen.getByText('Оплата временно отключена администратором.')).toBeInTheDocument()
  const buttons=screen.getAllByRole('button',{name:/Оплата недоступна, месячная оплата/})
  expect(buttons).toHaveLength(2)
  expect(buttons[0]).toBeDisabled()
  expect(buttons[1]).toBeDisabled()
  await userEvent.click(buttons[0])
  expect(apiMock).not.toHaveBeenCalledWith('/billing/checkout',expect.anything())
})

it('discloses one-period checkout before purchase when recurring payments are unavailable',async()=>{
  apiMock.mockImplementation(async(path:string)=>path==='/billing/plans'?{...catalog,recurring_payments_available:false}:free)
  render(<BillingPage subscription={free} onSubscription={()=>undefined}/>)
  expect(await screen.findByText('Оплата без автопродления')).toBeInTheDocument()
  expect(screen.getByText(/Карта не сохраняется/)).toBeInTheDocument()
})

it('shows current and past-due state and confirms cancellation',async()=>{
  const pastDue={...pro,status:'past_due',next_retry_at:'2026-09-02T00:00:00Z'}
  const canceled={...pro,status:'cancel_scheduled',cancel_at_period_end:true,scheduled_plan_code:'free' as const}
  apiMock.mockImplementation(async(path:string)=>{
    if(path==='/billing/plans')return catalog
    if(path==='/billing/subscription')return pastDue
    if(path==='/billing/cancel')return {subscription:canceled,message:'Автопродление отключено.'}
  })
  vi.stubGlobal('confirm',vi.fn(()=>true))
  const changed=vi.fn()
  render(<BillingPage subscription={pastDue} onSubscription={changed}/>)
  expect(await screen.findByText('Не удалось продлить подписку')).toBeInTheDocument()
  expect(screen.getByRole('button',{name:/Текущий тариф/})).toBeDisabled()
  await userEvent.click(screen.getByRole('button',{name:'Отменить автопродление'}))
  await waitFor(()=>expect(apiMock).toHaveBeenCalledWith('/billing/cancel',{method:'POST'}))
  expect(confirm).toHaveBeenCalled()
  expect(changed).toHaveBeenCalledWith(canceled)
})

it('explains a one-period purchase without offering unavailable auto-renewal',async()=>{
  const onePeriod={...pro,status:'cancel_scheduled',cancel_at_period_end:true,can_resume:false,next_billing_at:undefined,access_until:'2026-09-01T00:00:00Z'}
  apiMock.mockImplementation(async(path:string)=>path==='/billing/plans'?catalog:onePeriod)
  render(<BillingPage subscription={onePeriod} onSubscription={()=>undefined}/>)
  expect(await screen.findByText('Оплачен один период')).toBeInTheDocument()
  expect(screen.getByText(/Следующий период можно будет оплатить отдельно/)).toBeInTheDocument()
  expect(screen.queryByRole('button',{name:'Возобновить подписку'})).not.toBeInTheDocument()
  expect(screen.getAllByRole('button',{name:/После окончания периода, месячная оплата/})).toHaveLength(2)
  expect(screen.getAllByRole('button',{name:/После окончания периода, месячная оплата/}).every(button=>button.hasAttribute('disabled'))).toBe(true)
})

it('return screen polls the internal payment and refreshes subscription after success',async()=>{
  sessionStorage.setItem('axel_billing_payment_id','77')
  apiMock.mockImplementation(async(path:string)=>{
    if(path==='/billing/payments/77')return {id:77,status:'succeeded'}
    if(path==='/billing/subscription')return pro
  })
  const updated=vi.fn()
  render(<BillingReturnPage onSubscription={updated} onOpenBilling={()=>undefined}/>)
  expect(await screen.findByText('Оплата подтверждена')).toBeInTheDocument()
  expect(apiMock).toHaveBeenCalledWith('/billing/payments/77')
  expect(updated).toHaveBeenCalledWith(pro)
  expect(sessionStorage.getItem('axel_billing_payment_id')).toBeNull()
})

it('return screen keeps pending and canceled states explicit without activating access',async()=>{
  sessionStorage.setItem('axel_billing_payment_id','88')
  apiMock.mockResolvedValue({id:88,status:'pending'})
  const pending=render(<BillingReturnPage onSubscription={()=>undefined} onOpenBilling={()=>undefined}/>)
  expect(await screen.findByText('ЮKassa ещё обрабатывает платёж. Сервер повторно проверит статус и включит доступ после подтверждения оплаты.')).toBeInTheDocument()
  pending.unmount()
  apiMock.mockResolvedValue({id:88,status:'canceled'})
  render(<BillingReturnPage onSubscription={()=>undefined} onOpenBilling={()=>undefined}/>)
  expect(await screen.findByText('Платёж отменён')).toBeInTheDocument()
})

it('shows a PRO upsell for a gated feature',async()=>{
  const open=vi.fn()
  render(<SubscriptionUpsell requiredPlan="PRO" onClose={()=>undefined} onOpen={open}/>)
  expect(screen.getByRole('heading',{name:'Нужен тариф PRO'})).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button',{name:'Посмотреть тарифы'}))
  expect(open).toHaveBeenCalledOnce()
})
