import { useEffect, useRef, useState } from 'react'
import {
  Activity, ArrowUp, BarChart3, Bell, CalendarDays, CheckSquare2, ChevronLeft,
  ChevronRight, CircleDot, Diamond, Goal, HeartPulse, LayoutDashboard, LogOut,
  Menu, Moon, Send, Sparkles, Target, X, Zap,
} from 'lucide-react'
import type { Page } from '../App'
import { api, streamChat } from '../lib/api'
import type { CalendarView, ChatMessage as ChatMessageType, Dashboard, EnergyForecast, EnergyPoint, EnergyRecommendation, EventItem, Recommendation, User } from '../types'
import { ChatPanel } from './ChatPanel'

export function Logo({onClick}:{onClick?:()=>void}) {
  return <button className="axel-logo" onClick={onClick} aria-label="Axel One — главная">
    <span>A</span><span>X</span><span className="gold-letter">E</span><span>L</span><i/><span>O</span><span>N</span><span>E</span>
  </button>
}

export function Badge({children,tone='gold'}:{children:React.ReactNode;tone?:'gold'|'green'|'blue'|'red'|'purple'|'neutral'}) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

export function AppHeader({page,user,calendarView='week',onCalendarView,onMenu,onAssistant,onHome}:{page:Page;user:User;calendarView?:CalendarView;onCalendarView?:(view:CalendarView)=>void;onMenu:()=>void;onAssistant:()=>void;onHome:()=>void}) {
  const calendar = page === 'calendar'
  const date = new Intl.DateTimeFormat('ru-RU',{weekday:'short',day:'numeric',month:'long'}).format(new Date())
  return <header className={`app-header ${calendar?'calendar-header':''}`}>
    <button className="header-menu" onClick={onMenu} aria-label="Открыть меню"><Menu/></button>
    <Logo onClick={onHome}/>
    {calendar ? <div className="view-switch" aria-label="Вид календаря">
      {([['day','День'],['week','Неделя'],['month','Месяц']] as [CalendarView,string][]).map(([id,label])=><button key={id} className={calendarView===id?'active':''} aria-pressed={calendarView===id} onClick={()=>onCalendarView?.(id)}>{label}</button>)}
    </div> : <div className="header-section-name">Персональная система управления</div>}
    <div className="header-actions">
      {calendar ? <button className="primary compact" onClick={()=>window.dispatchEvent(new Event('axel:add-event'))}>+ Событие</button> : <span className="date-chip">{date}</span>}
      <button className="header-icon" aria-label="Уведомления"><Bell/></button>
      <button className="avatar round" aria-label={user.name} style={{background:user.avatar_color}}>{user.name.slice(0,1).toUpperCase()}</button>
      <button className="assistant-mobile-trigger" onClick={onAssistant} aria-label="Открыть AI-ассистента"><Sparkles/></button>
    </div>
  </header>
}

type NavEntry = {id:Page;label:string;icon:typeof LayoutDashboard;count?:number}
const overview:NavEntry[] = [
  {id:'dashboard',label:'Главная',icon:LayoutDashboard},
  {id:'calendar',label:'Календарь',icon:CalendarDays},
  {id:'goals',label:'Цели',icon:Goal},
  {id:'habits',label:'Привычки',icon:Diamond},
]
const analytics:NavEntry[] = [
  {id:'analytics',label:'Баланс жизни',icon:Target},
  {id:'analytics',label:'Здоровье',icon:HeartPulse},
  {id:'analytics',label:'Продуктивность',icon:BarChart3},
]
const system:NavEntry[] = [
  {id:'tasks',label:'Решения',icon:CircleDot},
  {id:'settings',label:'Профиль',icon:ChevronLeft},
]

export function SidebarItem({item,active,onClick}:{item:NavEntry;active:boolean;onClick:()=>void}) {
  const Icon=item.icon
  return <button className={`sidebar-item ${active?'active':''}`} onClick={onClick}>
    <Icon/><span>{item.label}</span>{item.count!=null&&<b>{item.count}</b>}
  </button>
}

export function Sidebar({page,user,open,navigate,onClose,onLogout,onAssistant}:{page:Page;user:User;open:boolean;navigate:(page:Page)=>void;onClose:()=>void;onLogout:()=>void;onAssistant:()=>void}) {
  const group=(label:string,entries:NavEntry[])=><div className="nav-group"><p>{label}</p>{entries.map((item,index)=><SidebarItem key={`${label}-${item.label}`} item={item} active={page===item.id&&(item.id!=='analytics'||index===0)} onClick={()=>navigate(item.id)}/>)}</div>
  return <aside className={`sidebar premium-sidebar ${open?'open':''}`}>
    <div className="sidebar-mobile-head"><Logo onClick={()=>navigate('dashboard')}/><button className="icon-btn" onClick={onClose}><X/></button></div>
    <nav>{group('Обзор',overview)}{group('Аналитика',analytics)}{group('Система',system)}</nav>
    <button className="assistant-status" onClick={onAssistant}><i/><div><b>AI-Ассистент</b><span>Открыть локальный AI-чат</span></div></button>
    <div className="sidebar-account">
      <span className="avatar" style={{background:user.avatar_color}}>{user.name.slice(0,1)}</span>
      <div><b>{user.name}</b><small>{user.occupation||user.email}</small></div>
      <button className="icon-btn" onClick={onLogout} aria-label="Выйти"><LogOut/></button>
    </div>
  </aside>
}

export function ChatMessage({message}:{message:ChatMessageType}) {
  return <div className={`premium-message ${message.role}`}><div>{message.content||<span className="typing"><b/><b/><b/></span>}</div></div>
}

function LegacyAIAssistantPanel({open,onClose}:{open:boolean;onClose:()=>void}) {
  const [dashboard,setDashboard]=useState<Dashboard|null>(null)
  const [recommendations,setRecommendations]=useState<Recommendation[]>([])
  const [messages,setMessages]=useState<ChatMessageType[]>([])
  const [text,setText]=useState('')
  const [sending,setSending]=useState(false)
  const endRef=useRef<HTMLDivElement>(null)
  useEffect(()=>{void Promise.all([
    api<Dashboard>('/dashboard').then(setDashboard),
    api<Recommendation[]>('/recommendations').then(setRecommendations),
    api<ChatMessageType[]>('/chat/history').then(setMessages),
  ]).catch(()=>undefined)},[])
  const send=async(value=text)=>{
    const message=value.trim();if(!message||sending)return
    setText('');setSending(true);setMessages(prev=>[...prev,{role:'user',content:message},{role:'assistant',content:''}]);setTimeout(()=>endRef.current?.scrollIntoView({behavior:'smooth'}),0)
    try{await streamChat(message,chunk=>setMessages(prev=>{const next=[...prev];next[next.length-1]={...next[next.length-1],content:next[next.length-1].content+chunk};return next}))}
    catch(err){setMessages(prev=>{const next=[...prev];next[next.length-1]={role:'assistant',content:err instanceof Error?err.message:'Не удалось ответить'};return next})}
    finally{setSending(false)}
  }
  const currentRecommendation=recommendations.find(item=>item.status==='new')
  return <aside className={`ai-panel ${open?'open':''}`}>
    <div className="ai-panel-head"><span className="ai-sign"><Diamond/></span><div><b>AI-Ассистент</b><small><i/> Онлайн</small></div><button className="icon-btn close-ai" onClick={onClose}><X/></button></div>
    <div className="ai-scroll">
      <section className="ai-summary-card">
        <h3>Ваш день — в одном взгляде</h3>
        <p>{dashboard?.overload.level==='high'?'Нагрузка выше обычной. Оставьте буфер между важными делами.':'Темп выглядит устойчиво — есть пространство для главного.'}</p>
        <div className="signal-list">
          <span><i>▥</i> Индекс фокуса <b className="positive">{dashboard?.focus_score??'—'}%</b></span>
          <span><i>◎</i> Выполнено задач <b className="positive">{dashboard?.completed_today??'—'}</b></span>
          <span><i>◫</i> Событий сегодня <b>{dashboard?.events_today.length??'—'}</b></span>
          <span><i>⚡</i> Нагрузка <b className={dashboard?.overload.level==='high'?'negative':'positive'}>{dashboard?.overload.score??'—'}</b></span>
          <span><i>◌</i> Ритм привычек <b className="positive">{dashboard?`${Math.round(dashboard.habit_rate)}%`:'—'}</b></span>
        </div>
        {currentRecommendation&&<div className="ai-recommendation"><b>Рекомендация</b><p>{currentRecommendation.body}</p></div>}
      </section>
      <span className="message-time">сейчас</span>
      {messages.length===0?<section className="ai-question"><h3>Хотите, чтобы я спланировал завтрашний день?</h3></section>:messages.slice(-5).map((item,index)=><ChatMessage key={index} message={item}/>)}
      <div ref={endRef}/>
    </div>
    <div className="quick-prompts">{['Да, давай','Улучшить сон','Мой стресс'].map(item=><button key={item} onClick={()=>send(item)}>{item}</button>)}</div>
    <form className="assistant-input" onSubmit={event=>{event.preventDefault();void send()}}><input value={text} onChange={event=>setText(event.target.value)} placeholder="Напишите сообщение…"/><button disabled={!text.trim()||sending} aria-label="Отправить"><Send/></button></form>
  </aside>
}

export function AIAssistantPanel({open,onClose}:{open:boolean;onClose:()=>void}) {
  return open?<ChatPanel onClose={onClose}/>:null
}

export function CalendarSidebar({events,selectedDate=new Date(),onSelect}:{events:EventItem[];selectedDate?:Date;onSelect?:(date:Date)=>void}) {
  const now=new Date();const year=selectedDate.getFullYear();const month=selectedDate.getMonth();const first=new Date(year,month,1);const startOffset=(first.getDay()+6)%7
  const days=Array.from({length:42},(_,index)=>new Date(year,month,index-startOffset+1))
  const counts=events.reduce<Record<string,number>>((acc,event)=>{acc[event.category]=(acc[event.category]||0)+1;return acc},{})
  const categories=[['work','Работа','blue'],['personal','Личное','green'],['focus','Фокус','gold'],['health','Здоровье','red'],['ai','AI-план','purple']]
  return <aside className="calendar-sidebar">
    <div className="mini-calendar"><div className="mini-title"><b>{new Intl.DateTimeFormat('ru-RU',{month:'long',year:'numeric'}).format(selectedDate)}</b><span>‹　›</span></div><div className="mini-weekdays">{['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map(day=><b key={day}>{day}</b>)}</div><div className="mini-days">{days.map((day,index)=><button key={index} onClick={()=>onSelect?.(day)} className={`${day.getMonth()!==month?'outside':''} ${day.toDateString()===now.toDateString()?'today':''} ${day.toDateString()===selectedDate.toDateString()?'selected':''}`}>{day.getDate()}</button>)}</div></div>
    <div className="calendar-listing"><h4>Мои календари</h4>{categories.map(([id,label,tone])=><div key={id}><i className={tone}/><span>{label}</span><b>{counts[id]||0}</b></div>)}</div>
    <div className="calendar-insights"><h4>AI-инсайты</h4><article><Zap/><b>Пик энергии</b><p>Лучший фокус — в первой половине дня. Сохраните это окно для главного.</p><button>Посмотреть план →</button></article><article><Activity/><b>Ровный ритм</b><p>В плане {events.length} событий. Между встречами полезно оставить короткие паузы.</p><button>Оптимизировать →</button></article></div>
  </aside>
}

export {AIPlannerPanel,RecommendationCard} from './CalendarPlanner'

export function MobileScrim({visible,onClick}:{visible:boolean;onClick:()=>void}) {return visible?<button className="premium-scrim" onClick={onClick} aria-label="Закрыть"/>:null}
