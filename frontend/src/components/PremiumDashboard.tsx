import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CalendarDays, CheckCircle2, CircleDot, Diamond, ListTodo, Plus, Target, Triangle, X } from 'lucide-react'
import type { Page } from '../App'
import { api } from '../lib/api'
import type { Balance, Dashboard, EventItem, Goal } from '../types'
import { Badge } from './PremiumShell'
import { Loading, Modal } from './UI'

const localTime=(value:string)=>new Intl.DateTimeFormat('ru-RU',{hour:'2-digit',minute:'2-digit'}).format(new Date(value))
const localInput=(date=new Date())=>{const value=new Date(date.getTime()-date.getTimezoneOffset()*60000);return value.toISOString().slice(0,16)}

export function ProgressRing({value}:{value:number}) {
  const safe=Math.max(0,Math.min(100,Math.round(value)))
  return <div className="premium-ring" style={{'--ring-value':`${safe*3.6}deg`} as React.CSSProperties}><span>{safe}%</span></div>
}

export function StatCard({icon:Icon,value,label,badge,tone='green'}:{icon:typeof Target;value:React.ReactNode;label:string;badge:string;tone?:'green'|'red'|'gold'|'blue'|'purple'}) {
  return <article className="stat-card"><Icon/><strong>{value}</strong><span>{label}</span><Badge tone={tone}>{badge}</Badge></article>
}

const categoryTone=(category:string):'green'|'red'|'gold'|'blue'|'purple'=>category==='work'?'blue':category==='focus'?'gold':category==='health'?'red':category==='ai'?'purple':'green'
const categoryName=(category:string)=>({work:'Работа',personal:'Личное',focus:'Фокус',health:'Здоровье',ai:'AI-план'}[category]||category)

export function ScheduleCard({events,onAdd}:{events:EventItem[];onAdd:()=>void}) {
  return <section className="premium-card schedule-card"><header><h2>Расписание сегодня</h2><button onClick={onAdd}>+ Добавить</button></header><div className="schedule-list">
    {events.length?events.map(event=><div className={`schedule-row ${event.category==='focus'?'active':''}`} key={event.id}><time>{localTime(event.start_at)}</time><i className={`dot ${categoryTone(event.category)}`}/><b>{event.title}</b><Badge tone={categoryTone(event.category)}>{categoryName(event.category)}</Badge></div>):<div className="premium-empty"><CalendarDays/><b>Сегодня свободный день</b><span>Добавьте событие или оставьте пространство для восстановления.</span></div>}
  </div></section>
}

type BalanceScoreKey='health'|'career'|'growth'|'finance'|'relationships'|'recreation'
const balanceMeta:[BalanceScoreKey,string,string][]=[['health','Здоровье','green'],['career','Карьера','blue'],['growth','Развитие','gold'],['finance','Финансы','purple'],['relationships','Отношения','red'],['recreation','Отдых','cyan']]

export function LifeBalanceCard({balance,navigate}:{balance?:Balance;navigate:()=>void}) {
  return <section className="premium-card compact-analysis"><header><h2>Баланс жизни</h2><button onClick={navigate}>Детали →</button></header>{balance?<div className="balance-compact">{balanceMeta.map(([key,label,color])=><div key={key}><span>{label}</span><div><i className={color} style={{width:`${balance[key]*10}%`}}/></div><b>{balance[key]}/10</b></div>)}</div>:<div className="premium-empty small"><CircleDot/><b>Пока нет оценки</b><span>Оцените ключевые сферы в аналитике.</span></div>}</section>
}

export function GoalsCard({goals,navigate}:{goals:Goal[];navigate:()=>void}) {
  return <section className="premium-card compact-analysis"><header><h2>Активные цели</h2><button onClick={navigate}>+ Цель</button></header><div className="premium-goals">{goals.length?goals.slice(0,4).map((goal,index)=><div key={goal.id}><span><i>{['◆','↗','◌','◇'][index]||'◇'}</i><b>{goal.title}</b><em>{goal.progress}%</em></span><div><i style={{width:`${goal.progress}%`}}/></div></div>):<div className="premium-empty small"><Target/><b>Нет активных целей</b><span>Добавьте ориентир, чтобы отслеживать прогресс.</span></div>}</div></section>
}

export default function PremiumDashboardPage({navigate,onChanged}:{navigate:(page:Page)=>void;onChanged:()=>void}) {
  const [data,setData]=useState<Dashboard|null>(null)
  const [balance,setBalance]=useState<Balance[]>([])
  const [error,setError]=useState('')
  const [taskModal,setTaskModal]=useState(false)
  const [eventModal,setEventModal]=useState(false)
  const load=()=>Promise.all([api<Dashboard>('/dashboard'),api<Balance[]>('/balance')]).then(([dashboard,items])=>{setData(dashboard);setBalance(items);setError('')}).catch(err=>setError(err instanceof Error?err.message:'Не удалось загрузить данные'))
  useEffect(()=>{void load()},[])
  const completedHabits=data?.habits.filter(item=>item.completed_today).length||0
  const overall=useMemo(()=>data?Math.round((data.focus_score+data.habit_rate+(data.goals.length?data.goals.reduce((sum,goal)=>sum+goal.progress,0)/data.goals.length:0))/3):0,[data])
  if(!data&&!error)return <Loading/>
  if(error)return <div className="error-state"><AlertTriangle/><h3>Не удалось загрузить ваш день</h3><p>{error}</p><button onClick={()=>void load()}>Повторить</button></div>
  if(!data)return null
  const avg=balance[0]?.average
  return <div className="page dashboard-page premium-dashboard">
    <header className="dashboard-intro"><h1>{data.greeting} 👋</h1><p>{data.date_label} — {data.overload.level==='high'?'сегодня особенно важен спокойный темп':'хороший уровень энергии'}</p></header>
    <section className="premium-stats">
      <article className="progress-card"><ProgressRing value={overall}/><div><b>Общий прогресс</b><span>Текущий уровень системы</span></div></article>
      <StatCard icon={Target} value={data.goals.length} label="Активных целей" badge="в движении"/>
      <StatCard icon={Diamond} value={`${completedHabits}/${data.habits.length}`} label="Привычки сегодня" badge={`${Math.round(data.habit_rate)}% выполнено`}/>
      <StatCard icon={Triangle} value={avg?avg>=7?'Хор.':avg>=5?'Сред.':'Низ.':'—'} label="Баланс жизни" badge={avg?`${avg.toFixed(1)} из 10`:'нужна оценка'} tone="green"/>
      <StatCard icon={ListTodo} value={data.tasks_due} label="Задач сегодня" badge={`${data.overload.urgent_tasks} срочных`} tone={data.overload.urgent_tasks?'red':'green'}/>
    </section>
    {data.overload.level==='high'&&<div className="premium-alert"><AlertTriangle/><div><b>Высокая плотность дня</b><span>{data.overload.suggestion}</span></div><button onClick={()=>navigate('tasks')}>Разгрузить план</button></div>}
    <ScheduleCard events={data.events_today} onAdd={()=>setEventModal(true)}/>
    <div className="dashboard-analysis-grid"><LifeBalanceCard balance={balance[0]} navigate={()=>navigate('analytics')}/><GoalsCard goals={data.goals} navigate={()=>navigate('goals')}/></div>
    <button className="floating-quick-task" onClick={()=>setTaskModal(true)}><Plus/> Быстрая задача</button>
    {taskModal&&<QuickTaskModal onClose={()=>setTaskModal(false)} onSaved={()=>{setTaskModal(false);void load();onChanged()}}/>}
    {eventModal&&<QuickEventModal onClose={()=>setEventModal(false)} onSaved={()=>{setEventModal(false);void load();onChanged()}}/>}
  </div>
}

function QuickTaskModal({onClose,onSaved}:{onClose:()=>void;onSaved:()=>void}) {
  const [form,setForm]=useState({title:'',due_at:localInput(),priority:'medium',estimate_minutes:30,energy:'medium',project:''})
  const [saving,setSaving]=useState(false);const [error,setError]=useState('')
  const submit=async(event:React.FormEvent)=>{event.preventDefault();setSaving(true);setError('');try{await api('/tasks',{method:'POST',body:JSON.stringify({...form,due_at:new Date(form.due_at).toISOString().slice(0,19)})});onSaved()}catch(err){setError(err instanceof Error?err.message:'Ошибка')}finally{setSaving(false)}}
  return <Modal title="Новая задача" onClose={onClose}><form className="modal-form" onSubmit={submit}><label className="full">Что нужно сделать?<input autoFocus required value={form.title} onChange={event=>setForm({...form,title:event.target.value})} placeholder="Например, подготовить презентацию"/></label><label>Срок<input type="datetime-local" value={form.due_at} onChange={event=>setForm({...form,due_at:event.target.value})}/></label><label>Приоритет<select value={form.priority} onChange={event=>setForm({...form,priority:event.target.value})}><option value="low">Низкий</option><option value="medium">Обычный</option><option value="high">Важный</option><option value="urgent">Срочный</option></select></label><label>Оценка, минут<input type="number" min="5" value={form.estimate_minutes} onChange={event=>setForm({...form,estimate_minutes:+event.target.value})}/></label><label>Проект<input value={form.project} onChange={event=>setForm({...form,project:event.target.value})}/></label>{error&&<div className="form-error full">{error}</div>}<div className="modal-actions full"><button type="button" className="secondary" onClick={onClose}>Отмена</button><button className="primary" disabled={saving}>{saving?'Сохраняем…':'Создать'}</button></div></form></Modal>
}

export function QuickEventModal({initialStart,eventToEdit,onClose,onSaved}:{initialStart?:Date;eventToEdit?:EventItem;onClose:()=>void;onSaved:()=>void}) {
  const start=eventToEdit?new Date(eventToEdit.start_at):initialStart?new Date(initialStart):new Date();start.setSeconds(0,0);if(!eventToEdit&&!initialStart){start.setMinutes(0);start.setHours(start.getHours()+1)}const end=eventToEdit?new Date(eventToEdit.end_at):new Date(start);if(!eventToEdit)end.setHours(end.getHours()+1)
  const [form,setForm]=useState({title:eventToEdit?.title||'',description:eventToEdit?.description||'',start_at:localInput(start),end_at:localInput(end),category:eventToEdit?.category||'personal',location:eventToEdit?.location||'',color:eventToEdit?.color||'#4fc28b',reminder_minutes:eventToEdit?.reminder_minutes??10,recurrence_rule:eventToEdit?.recurrence_rule||''})
  const [saving,setSaving]=useState(false);const [error,setError]=useState('')
  const colors:Record<string,string>={personal:'#4fc28b',work:'#5b9df5',focus:'#d3ae43',health:'#ef6267',ai:'#a681df'}
  const submit=async(event:React.FormEvent)=>{event.preventDefault();setSaving(true);setError('');try{const payload={...form,description:form.description.trim()||null,location:form.location.trim()||null,color:colors[form.category]||form.color,start_at:`${form.start_at}:00`,end_at:`${form.end_at}:00`,recurrence_rule:form.recurrence_rule||null};await api(eventToEdit?`/events/${eventToEdit.id}`:'/events',{method:eventToEdit?'PATCH':'POST',body:JSON.stringify(payload)});onSaved()}catch(err){setError(err instanceof Error?err.message:'Ошибка')}finally{setSaving(false)}}
  return <Modal title={eventToEdit?'Редактировать событие':'Новое событие'} onClose={onClose}><form className="modal-form" onSubmit={submit}><label className="full">Название<input autoFocus required value={form.title} onChange={event=>setForm({...form,title:event.target.value})} placeholder="Что запланировано?"/></label><label className="full">Описание<textarea rows={3} value={form.description} onChange={event=>setForm({...form,description:event.target.value})} placeholder="Необязательно"/></label><label>Начало<input required type="datetime-local" value={form.start_at} onChange={event=>setForm({...form,start_at:event.target.value})}/></label><label>Окончание<input required type="datetime-local" value={form.end_at} onChange={event=>setForm({...form,end_at:event.target.value})}/></label><label>Категория<select value={form.category} onChange={event=>setForm({...form,category:event.target.value})}><option value="personal">Личное</option><option value="work">Работа</option><option value="focus">Фокус</option><option value="health">Здоровье</option><option value="ai">AI-план</option></select></label><label>Место<input value={form.location} onChange={event=>setForm({...form,location:event.target.value})} placeholder="Необязательно"/></label><label>Повтор<select value={form.recurrence_rule} onChange={event=>setForm({...form,recurrence_rule:event.target.value})}><option value="">Не повторять</option><option value="FREQ=DAILY">Каждый день</option><option value="FREQ=WEEKLY">Каждую неделю</option></select></label><label>Напомнить<select value={form.reminder_minutes} onChange={event=>setForm({...form,reminder_minutes:+event.target.value})}><option value="0">В момент события</option><option value="10">За 10 минут</option><option value="30">За 30 минут</option><option value="60">За час</option></select></label>{error&&<div className="form-error full">{error}</div>}<div className="modal-actions full"><button type="button" className="secondary" onClick={onClose}>Отмена</button><button className="primary" disabled={saving}>{saving?'Сохраняем…':eventToEdit?'Сохранить':'Добавить'}</button></div></form></Modal>
}
