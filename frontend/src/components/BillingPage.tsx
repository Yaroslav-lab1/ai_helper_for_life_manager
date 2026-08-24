import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Check, CreditCard, Crown, RefreshCw, ShieldCheck, Sparkles, X } from 'lucide-react'
import { api } from '../lib/api'
import type { BillingAction, BillingCatalog, BillingInterval, BillingPayment, BillingPlan, PlanCode, Subscription } from '../types'
import { Empty, Loading, Modal, PageHeader } from './UI'

const money=(value:string,currency='RUB')=>new Intl.NumberFormat('ru-RU',{style:'currency',currency,minimumFractionDigits:2}).format(Number(value))
const date=(value?:string)=>value?new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'long',year:'numeric'}).format(new Date(value)):'—'
const statusLabel:Record<string,string>={free:'Бесплатный',pending:'Ожидает оплаты',active:'Активна',past_due:'Проблема с оплатой',cancel_scheduled:'Автопродление отключено',canceled:'Отменена',expired:'Истекла'}

export function BillingPage({subscription,onSubscription,redirect=(url:string)=>window.location.assign(url)}:{subscription:Subscription|null;onSubscription:(value:Subscription)=>void;redirect?:(url:string)=>void}) {
  const [catalog,setCatalog]=useState<BillingCatalog|null>(null)
  const [current,setCurrent]=useState<Subscription|null>(subscription)
  const [interval,setInterval]=useState<BillingInterval>('monthly')
  const [loading,setLoading]=useState(!subscription)
  const [working,setWorking]=useState<PlanCode|null>(null)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const load=async()=>{setLoading(true);setError('');try{const [plans,sub]=await Promise.all([api<BillingCatalog>('/billing/plans'),api<Subscription>('/billing/subscription')]);setCatalog(plans);setCurrent(sub);onSubscription(sub)}catch(err){setError(err instanceof Error?err.message:'Не удалось загрузить подписку')}finally{setLoading(false)}}
  useEffect(()=>{void load()},[])
  const update=(value:Subscription)=>{setCurrent(value);onSubscription(value)}
  const checkout=async(plan:BillingPlan)=>{setWorking(plan.code);setError('');setNotice('');try{
    const result=await api<{payment_id:number;confirmation_url:string}>('/billing/checkout',{method:'POST',body:JSON.stringify({plan_code:plan.code,billing_interval:interval})})
    sessionStorage.setItem('axel_billing_payment_id',String(result.payment_id))
    redirect(result.confirmation_url)
  }catch(err){setError(err instanceof Error?err.message:'Не удалось перейти к оплате');setWorking(null)}}
  const schedule=async(plan:BillingPlan)=>{setWorking(plan.code);setError('');try{const result=await api<BillingAction>('/billing/change-plan',{method:'POST',body:JSON.stringify({plan_code:plan.code,billing_interval:interval})});update(result.subscription);setNotice(result.message)}catch(err){setError(err instanceof Error?err.message:'Не удалось запланировать смену')}finally{setWorking(null)}}
  const choose=async(plan:BillingPlan)=>{
    if(plan.code==='free'){await cancel();return}
    if(current?.effective_plan_code==='free')await checkout(plan);else await schedule(plan)
  }
  const cancel=async()=>{if(!confirm('Отключить автопродление? Оплаченный доступ сохранится до конца периода.'))return;setWorking('free');setError('');try{const result=await api<BillingAction>('/billing/cancel',{method:'POST'});update(result.subscription);setNotice(result.message)}catch(err){setError(err instanceof Error?err.message:'Не удалось отключить автопродление')}finally{setWorking(null)}}
  const resume=async()=>{setWorking(current?.plan_code||'pro');setError('');try{const result=await api<BillingAction>('/billing/resume',{method:'POST'});update(result.subscription);setNotice(result.message)}catch(err){setError(err instanceof Error?err.message:'Не удалось возобновить подписку')}finally{setWorking(null)}}
  if(loading&&!catalog)return <Loading/>
  if(error&&!catalog)return <div className="page"><Empty icon={AlertTriangle} title="Подписка недоступна" text={error}/><button className="primary billing-retry" onClick={()=>void load()}><RefreshCw/> Повторить</button></div>
  const plans=catalog?.plans||[]
  if(!plans.length)return <div className="page"><Empty icon={CreditCard} title="Тарифы пока не опубликованы" text="Попробуйте обновить страницу позже."/></div>
  return <div className="page billing-page"><PageHeader eyebrow="Планы Axel One" title="Подписка" description="Цена и доступные возможности определяются сервером. Смена платного тарифа применяется без двойного списания — со следующего периода."/>
    <section className="billing-summary" aria-live="polite"><div><span>Текущий тариф</span><b>{current?.effective_plan_code.toUpperCase()}</b><small>{statusLabel[current?.status||'free']||current?.status}</small></div><div><span>{current?.cancel_at_period_end?'Доступ до':'Следующее списание'}</span><b>{date(current?.cancel_at_period_end?current.access_until:current?.next_billing_at)}</b><small>{current?.scheduled_plan_code&&`Затем ${current.scheduled_plan_code.toUpperCase()}`}</small></div>{current?.status==='past_due'&&<div className="billing-warning"><AlertTriangle/><span><b>Не удалось продлить подписку</b><small>Доступ сохранён на льготный период. Следующая попытка: {date(current.next_retry_at)}</small></span></div>}</section>
    <div className="billing-toggle" role="group" aria-label="Интервал оплаты"><button className={interval==='monthly'?'active':''} aria-pressed={interval==='monthly'} onClick={()=>setInterval('monthly')}>Месячная оплата</button><button className={interval==='yearly'?'active':''} aria-pressed={interval==='yearly'} onClick={()=>setInterval('yearly')}>Годовая оплата <em>−17%</em></button></div>
    {!catalog?.checkout_available&&current?.effective_plan_code==='free'&&<div className="billing-availability" role="status"><AlertTriangle/><span><b>Оплата пока недоступна</b><small>{catalog?.checkout_unavailable_message||'Платёжный провайдер ещё не настроен.'}</small></span></div>}
    {error&&<div className="form-error" role="alert">{error}</div>}{notice&&<div className="form-success" role="status">{notice}</div>}
    <section className="plan-grid" aria-label="Тарифные планы">{plans.map(plan=><PlanCard key={plan.code} plan={plan} interval={interval} current={current} working={working===plan.code} checkoutAvailable={Boolean(catalog?.checkout_available)} onChoose={()=>void choose(plan)}/>)}</section>
    {current?.cancel_at_period_end&&current.effective_plan_code!=='free'&&<section className="billing-renew card"><div><ShieldCheck/><span><b>Автопродление отключено</b><small>Доступ сохранится до {date(current.current_period_end)}. До этой даты подписку можно возобновить.</small></span></div><button className="primary" onClick={()=>void resume()} disabled={Boolean(working)}>Возобновить подписку</button></section>}
    {current?.effective_plan_code!=='free'&&!current?.cancel_at_period_end&&<button className="billing-cancel" onClick={()=>void cancel()} disabled={Boolean(working)}>Отменить автопродление</button>}
    <p className="billing-note"><ShieldCheck/> Данные карты обрабатывает ЮKassa. Axel One не получает и не хранит номер карты или CVC.</p>
  </div>
}

function PlanCard({plan,interval,current,working,checkoutAvailable,onChoose}:{plan:BillingPlan;interval:BillingInterval;current:Subscription|null;working:boolean;checkoutAvailable:boolean;onChoose:()=>void}){
  const selected=current?.effective_plan_code===plan.code
  const price=interval==='monthly'?plan.monthly_price:plan.yearly_price
  const button=selected?'Текущий тариф':plan.code==='free'?'Перейти на FREE':plan.code==='pro'?'Попробовать PRO':'Получить EXECUTIVE'
  const checkoutBlocked=current?.effective_plan_code==='free'&&plan.code!=='free'&&!checkoutAvailable
  const buttonText=working?'Подождите…':!plan.available?'Скоро':checkoutBlocked?'Оплата недоступна':button
  return <article className={`plan-card ${plan.code==='pro'?'popular':''} ${selected?'current':''}`} aria-label={`Тариф ${plan.name}`}>{plan.code==='pro'&&<span className="popular-label"><Sparkles/> Самый популярный</span>}<header><span className={`plan-symbol ${plan.code}`}>{plan.code==='executive'?<Crown/>:plan.code==='pro'?<Sparkles/>:<Check/>}</span><div><h2>{plan.name}</h2><small>{plan.code==='free'?'Для спокойного старта':plan.code==='pro'?'AI для ежедневной ясности':'Контур расширенной аналитики'}</small></div></header><div className="plan-price"><b>{money(price,plan.currency)}</b><span>{plan.code==='free'?'навсегда':interval==='monthly'?'/ месяц':'списание за год'}</span></div>{interval==='yearly'&&plan.code!=='free'&&<div className="yearly-breakdown"><span>≈ {money(plan.yearly_monthly_equivalent,plan.currency)} в месяц</span><b>Экономия {money(plan.yearly_savings,plan.currency)}</b></div>}<ul>{plan.features.map(feature=><li key={feature}><Check/>{feature}</li>)}</ul>{plan.code==='executive'&&<p className="executive-note">Глубокие Executive-модули подключаются по мере выпуска. Карточка не обещает ещё не реализованные отчёты.</p>}<button className={plan.code==='pro'?'primary':'secondary'} disabled={selected||working||!plan.available||checkoutBlocked} onClick={onChoose} aria-label={`${buttonText}, ${interval==='monthly'?'месячная':'годовая'} оплата`}>{buttonText}</button>{current?.scheduled_plan_code===plan.code&&<small className="scheduled-label">Запланировано с {date(current.scheduled_change_at)}</small>}</article>
}

export function BillingReturnPage({onSubscription,onOpenBilling}:{onSubscription:(value:Subscription)=>void;onOpenBilling:()=>void}){
  const [state,setState]=useState<'checking'|'pending'|'succeeded'|'canceled'|'error'>('checking')
  const [message,setMessage]=useState('Проверяем подтверждение от ЮKassa…')
  const paymentId=useMemo(()=>new URLSearchParams(location.search).get('payment_id')||sessionStorage.getItem('axel_billing_payment_id'),[])
  useEffect(()=>{if(!paymentId){setState('error');setMessage('Не найден идентификатор платежа. Откройте раздел подписки.');return}
    let stopped=false;let timer:number|undefined;let attempts=0
    const poll=async()=>{try{const payment=await api<BillingPayment>(`/billing/payments/${paymentId}`);if(stopped)return
      if(payment.status==='succeeded'||payment.status==='refunded'){const sub=await api<Subscription>('/billing/subscription');if(stopped)return;onSubscription(sub);sessionStorage.removeItem('axel_billing_payment_id');setState('succeeded');setMessage('Оплата подтверждена. Возможности тарифа уже доступны.');return}
      if(payment.status==='canceled'){setState('canceled');setMessage('Платёж отменён. Деньги не списаны.');return}
      attempts+=1;setState('pending');setMessage('ЮKassa ещё обрабатывает платёж. Доступ включится только после подтверждённого уведомления.');if(attempts<20)timer=window.setTimeout(()=>void poll(),2000)
    }catch(err){if(!stopped){setState('error');setMessage(err instanceof Error?err.message:'Не удалось проверить платёж')}}}
    void poll();return()=>{stopped=true;if(timer)clearTimeout(timer)}
  },[paymentId])
  return <main className="billing-return"><section className={`return-card ${state}`} aria-live="polite">{state==='checking'||state==='pending'?<span className="return-spinner"><RefreshCw/></span>:state==='succeeded'?<span className="return-success"><Check/></span>:<span className="return-error"><X/></span>}<h1>{state==='succeeded'?'Оплата подтверждена':state==='canceled'?'Платёж отменён':state==='error'?'Не удалось проверить оплату':'Проверяем оплату'}</h1><p>{message}</p><button className="primary" onClick={onOpenBilling}>{state==='pending'?'Проверить в разделе подписки':'Перейти к подписке'}</button><small>Открытие этой страницы само по себе не активирует тариф.</small></section></main>
}

export function SubscriptionSettingsCard({subscription,onOpen}:{subscription:Subscription|null;onOpen:()=>void}){
  return <section className="card settings-section subscription-settings"><div className="settings-title"><span><CreditCard/></span><div><h3>Подписка</h3><p>{subscription?`${subscription.effective_plan_code.toUpperCase()} · ${statusLabel[subscription.status]||subscription.status}`:'Загружаем состояние подписки…'}</p></div></div><div className="account-row"><div><b>{subscription?.cancel_at_period_end?'Доступ оплачен до':'Следующее списание'}</b><p>{date(subscription?.cancel_at_period_end?subscription.access_until:subscription?.next_billing_at)}</p></div><button type="button" className="secondary" onClick={onOpen}>Управлять подпиской</button></div></section>
}

export function SubscriptionUpsell({requiredPlan='PRO',onClose,onOpen}:{requiredPlan?:string;onClose:()=>void;onOpen:()=>void}){
  return <Modal title="Возможность входит в подписку" onClose={onClose}><div className="subscription-upsell"><Sparkles/><h3>Нужен тариф {requiredPlan}</h3><p>Ваши данные останутся на месте. После оплаты доступ включится только по подтверждённому уведомлению ЮKassa.</p><div className="modal-actions"><button className="secondary" onClick={onClose}>Не сейчас</button><button className="primary" onClick={onOpen}>Посмотреть тарифы</button></div></div></Modal>
}
