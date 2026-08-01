import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, CalendarPlus, Check, Diamond, RefreshCw, Send, Trash2, X } from 'lucide-react'
import { api, streamChat } from '../lib/api'
import type { ChatMessage, EnergyForecast, EnergyPoint, EnergyRecommendation, EventItem } from '../types'

type PlannerTab='plan'|'energy'|'chat'
type PlanStatus='idle'|'loading'|'added'|'dismissed'|'error'
const tabs:{id:PlannerTab;label:string}[]=[{id:'plan',label:'План дня'},{id:'energy',label:'Энергия'},{id:'chat',label:'Чат'}]
const toDateKey=(value:Date)=>value.toLocaleDateString('sv-SE')
const localDateTime=(value:Date)=>new Date(value.getTime()-value.getTimezoneOffset()*60000).toISOString().slice(0,19)
const PlannerBadge=({children,tone}:{children:React.ReactNode;tone:'gold'|'green'|'blue'})=><span className={`badge badge-${tone}`}>{children}</span>

export function RecommendationCard({recommendation,date,status='idle',time,onTime,onAdd,onDismiss}:{recommendation:EnergyRecommendation;date:string;status?:PlanStatus;time:string;onTime:(value:string)=>void;onAdd:()=>void;onDismiss:()=>void}) {
  const [editing,setEditing]=useState(false)
  return <article className={`planner-card recommendation-${recommendation.kind} ${status}`}>
    <time>{editing?<input type="time" value={time} onChange={event=>onTime(event.target.value)} aria-label="Время рекомендации"/>:time}</time>
    <div><b>{recommendation.kind==='focus'?'⚡ ':recommendation.kind==='health'?'◐ ':''}{recommendation.title}</b><p>{recommendation.body}</p><PlannerBadge tone={recommendation.kind==='focus'?'gold':recommendation.kind==='health'||recommendation.kind==='recovery'?'green':'blue'}>{recommendation.kind==='focus'?'AI-рекомендация':recommendation.kind==='health'?'Здоровье':'План'}</PlannerBadge>
      <div className="planner-card-actions">
        {status==='added'?<span className="plan-success"><Check/> Добавлено</span>:<button onClick={onAdd} disabled={status==='loading'||status==='dismissed'}><CalendarPlus/>{status==='loading'?'Добавляем…':status==='error'?'Повторить':'В календарь'}</button>}
        <button onClick={()=>setEditing(value=>!value)} disabled={status==='added'||status==='dismissed'}>{editing?'Готово':'Изменить время'}</button>
        <button onClick={onDismiss} disabled={status==='added'||status==='dismissed'}>Скрыть</button>
      </div>{status==='error'&&<span className="plan-error"><AlertTriangle/> Не удалось добавить событие</span>}
    </div>
  </article>
}

function EnergyGraph({points}:{points:EnergyPoint[]}) {
  const [active,setActive]=useState<EnergyPoint|null>(null)
  return <div className="energy-chart-wrap"><div className="energy-chart" role="img" aria-label="График энергии с 06:00 до 23:00">{points.map(point=><button key={point.hour} className={point.kind} style={{'--energy':`${point.level}%`} as React.CSSProperties} onMouseEnter={()=>setActive(point)} onFocus={()=>setActive(point)} onMouseLeave={()=>setActive(null)} aria-label={`${String(point.hour).padStart(2,'0')}:00 — энергия ${point.level}%`}><i/><span>{point.hour%3===0?String(point.hour).padStart(2,'0'):''}</span></button>)}</div><div className={`energy-tooltip ${active?'visible':''}`}>{active?<><b>{String(active.hour).padStart(2,'0')}:00 · {active.level}%</b><span>{active.activity}</span><p>{active.recommendation}</p></>:<><b>Наведите на график</b><span>Увидите прогноз и рекомендацию для каждого часа.</span></>}</div></div>
}

function EnergyPanel({forecast,loading,error,period,onPeriod,reload}:{forecast:EnergyForecast|null;loading:boolean;error:string;period:'today'|'tomorrow'|'week';onPeriod:(period:'today'|'tomorrow'|'week')=>void;reload:()=>void}) {
  return <div className="energy-panel-content"><div className="energy-period">{([['today','Сегодня'],['tomorrow','Завтра'],['week','Неделя']] as const).map(([id,label])=><button key={id} className={period===id?'active':''} onClick={()=>onPeriod(id)}>{label}</button>)}</div>
    {loading?<div className="planner-loading"><i/><span>Строим прогноз…</span></div>:error?<div className="planner-error"><AlertTriangle/><b>Прогноз недоступен</b><span>{error}</span><button onClick={reload}><RefreshCw/> Повторить</button></div>:forecast&&<>
      <section className="energy-score"><div><strong>{forecast.score}</strong><span>/100</span></div><div><b>{forecast.status}</b><span>Пик концентрации {forecast.peak_start}–{forecast.peak_end}</span></div></section>
      <EnergyGraph points={forecast.points}/>
      <section className="energy-legend"><span><i className="peak"/> Пик</span><span><i className="dip"/> Спад</span><span><i className="recovery"/> Восстановление</span></section>
      <section className="energy-factors"><h4>Факторы прогноза</h4>{forecast.factors.map(item=><div key={item.label}><span>{item.label}<small>{item.impact}</small></span><b className={item.tone}>{item.value}</b></div>)}</section>
      <section className="energy-advice"><h4>AI-рекомендации</h4>{forecast.recommendations.map(item=><div key={`${item.time}-${item.title}`}><time>{item.time}</time><span><b>{item.title}</b><small>{item.body}</small></span></div>)}</section>
    </>}
  </div>
}

function PlannerChat({selectedDate}:{selectedDate:string}) {
  const [messages,setMessages]=useState<ChatMessage[]>([]);const [text,setText]=useState('');const [sending,setSending]=useState(false);const [error,setError]=useState('');const [lastMessage,setLastMessage]=useState('');const endRef=useRef<HTMLDivElement>(null)
  useEffect(()=>{void api<ChatMessage[]>('/chat/history').then(setMessages).catch(err=>setError(err instanceof Error?err.message:'История недоступна'))},[])
  useEffect(()=>{endRef.current?.scrollIntoView({behavior:'smooth'})},[messages])
  const send=async(value=text)=>{const message=value.trim();if(!message||sending)return;setText('');setError('');setLastMessage(message);setSending(true);setMessages(prev=>[...prev,{role:'user',content:message,created_at:new Date().toISOString()},{role:'assistant',content:'',created_at:new Date().toISOString()}]);try{await streamChat(message,chunk=>setMessages(prev=>{const next=[...prev];next[next.length-1]={...next[next.length-1],content:next[next.length-1].content+chunk};return next}),{selected_date:selectedDate})}catch(err){setError(err instanceof Error?err.message:'Не удалось получить ответ');setMessages(prev=>prev.slice(0,-1))}finally{setSending(false)}}
  const clear=async()=>{await api('/chat/history',{method:'DELETE'});setMessages([]);setError('')}
  const prompts=['Оптимизируй мой день','Когда лучше выполнить сложную задачу?','Найди время для тренировки','У меня слишком много встреч?','Составь план на завтра']
  return <div className="planner-chat"><div className="planner-chat-tools"><span>Контекст: {new Date(`${selectedDate}T12:00`).toLocaleDateString('ru-RU',{day:'numeric',month:'long'})}</span><button onClick={()=>void clear()} disabled={!messages.length}><Trash2/> Очистить</button></div><div className="planner-messages">{!messages.length&&!error&&<div className="chat-empty"><Diamond/><b>Спросите о вашем расписании</b><span>AI учтёт события, свободные окна, цели, привычки, энергию и нагрузку.</span></div>}{messages.map((message,index)=><div key={message.id||index} className={`planner-message ${message.role}`}><div>{message.content||<span className="typing"><b/><b/><b/></span>}</div><time>{message.created_at?new Date(message.created_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}):''}</time></div>)}<div ref={endRef}/></div>{error&&<div className="chat-error"><AlertTriangle/><span>{error}</span><button onClick={()=>void send(lastMessage)}>Повторить</button></div>}<div className="planner-prompts">{prompts.map(prompt=><button key={prompt} onClick={()=>void send(prompt)} disabled={sending}>{prompt}</button>)}</div><form className="planner-chat-input" onSubmit={event=>{event.preventDefault();void send()}}><textarea rows={2} value={text} onChange={event=>setText(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();void send()}}} placeholder="Спросите о плане…"/><button disabled={!text.trim()||sending} aria-label="Отправить"><Send/></button></form></div>
}

export function AIPlannerPanel({events,selectedDate,open,onClose,onCalendarChanged}:{events:EventItem[];selectedDate:string;open:boolean;onClose:()=>void;onCalendarChanged:()=>void}) {
  const [tab,setTabState]=useState<PlannerTab>(()=>{const saved=localStorage.getItem('axel_planner_tab');return saved==='energy'||saved==='chat'?saved:'plan'})
  const [period,setPeriod]=useState<'today'|'tomorrow'|'week'>('today');const [forecast,setForecast]=useState<EnergyForecast|null>(null);const [loading,setLoading]=useState(true);const [error,setError]=useState('');const [statuses,setStatuses]=useState<Record<string,PlanStatus>>({});const [times,setTimes]=useState<Record<string,string>>({})
  const setTab=(next:PlannerTab)=>{setTabState(next);localStorage.setItem('axel_planner_tab',next)}
  const energyDate=useMemo(()=>{const date=new Date(`${selectedDate}T12:00`);if(period==='tomorrow')date.setDate(date.getDate()+1);return date},[selectedDate,period])
  const loadEnergy=async()=>{setLoading(true);setError('');try{if(period==='week'){const forecasts=await Promise.all(Array.from({length:7},(_,index)=>{const day=new Date(energyDate);day.setDate(day.getDate()+index);return api<EnergyForecast>(`/energy?date=${toDateKey(day)}`)}));const base=forecasts[0];setForecast({...base,score:Math.round(forecasts.reduce((sum,item)=>sum+item.score,0)/forecasts.length),status:'Среднее за неделю',points:base.points.map((point,index)=>({...point,level:Math.round(forecasts.reduce((sum,item)=>sum+item.points[index].level,0)/forecasts.length)}))})}else setForecast(await api<EnergyForecast>(`/energy?date=${toDateKey(energyDate)}`))}catch(err){setError(err instanceof Error?err.message:'Не удалось загрузить прогноз')}finally{setLoading(false)}}
  useEffect(()=>{void loadEnergy()},[selectedDate,period])
  const recommendations=forecast?.recommendations||[]
  const addRecommendation=async(item:EnergyRecommendation,index:number)=>{const key=`${item.kind}-${index}`;setStatuses(value=>({...value,[key]:'loading'}));try{const start=new Date(`${selectedDate}T${times[key]||item.time}:00`);const end=new Date(start);end.setMinutes(end.getMinutes()+(item.kind==='focus'?90:45));const category=item.kind==='focus'?'focus':item.kind==='health'||item.kind==='recovery'?'health':'personal';const colors:Record<string,string>={focus:'#d3ae43',health:'#ef6267',personal:'#4fc28b'};await api('/events',{method:'POST',body:JSON.stringify({title:item.title,description:item.body,start_at:localDateTime(start),end_at:localDateTime(end),category,color:colors[category],reminder_minutes:10})});setStatuses(value=>({...value,[key]:'added'}));onCalendarChanged()}catch{setStatuses(value=>({...value,[key]:'error'}))}}
  const onTabKey=(event:React.KeyboardEvent<HTMLDivElement>)=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();const current=tabs.findIndex(item=>item.id===tab);const next=event.key==='ArrowRight'?(current+1)%tabs.length:(current-1+tabs.length)%tabs.length;setTab(tabs[next].id);(event.currentTarget.querySelectorAll('[role="tab"]')[next] as HTMLButtonElement | undefined)?.focus()}
  return <aside className={`planner-panel ${open?'open':''}`}><div className="ai-panel-head"><span className="ai-sign"><Diamond/></span><div><b>AI-Планировщик</b><small><i/> Анализирует ваш день</small></div><button className="icon-btn planner-close" onClick={onClose} aria-label="Закрыть AI-планировщик"><X/></button></div><div className="planner-tabs" role="tablist" aria-label="Разделы AI-планировщика" onKeyDown={onTabKey}>{tabs.map(item=><button key={item.id} id={`planner-tab-${item.id}`} role="tab" aria-selected={tab===item.id} aria-controls={`planner-panel-${item.id}`} tabIndex={tab===item.id?0:-1} className={tab===item.id?'active':''} onClick={()=>setTab(item.id)}>{item.label}</button>)}</div><div className="planner-scroll" role="tabpanel" id={`planner-panel-${tab}`} aria-labelledby={`planner-tab-${tab}`}>
    {tab==='plan'&&<><h4>Рекомендованный план · {new Date(`${selectedDate}T12:00`).toLocaleDateString('ru-RU',{day:'numeric',month:'long'})}</h4>{loading?<div className="planner-loading"><i/><span>Анализируем свободные окна…</span></div>:error?<div className="planner-error"><AlertTriangle/><span>{error}</span><button onClick={()=>void loadEnergy()}>Повторить</button></div>:recommendations.map((item,index)=>{const key=`${item.kind}-${index}`;if(statuses[key]==='dismissed')return null;return <RecommendationCard key={key} recommendation={item} date={selectedDate} status={statuses[key]} time={times[key]||item.time} onTime={time=>setTimes(value=>({...value,[key]:time}))} onAdd={()=>void addRecommendation(item,index)} onDismiss={()=>setStatuses(value=>({...value,[key]:'dismissed'}))}/>})}</>}
    {tab==='energy'&&<EnergyPanel forecast={forecast} loading={loading} error={error} period={period} onPeriod={setPeriod} reload={()=>void loadEnergy()}/>} 
    {tab==='chat'&&<PlannerChat selectedDate={selectedDate}/>} 
  </div></aside>
}
