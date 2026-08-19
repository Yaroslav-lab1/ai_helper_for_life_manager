import {
  Activity, BarChart3, Bell, CalendarDays, ChevronLeft, CircleDot, Diamond,
  Goal, HeartPulse, LayoutDashboard, LogOut, Menu, ReceiptText, Sparkles, Target, X, Zap,
} from 'lucide-react'
import type { Page } from '../App'
import { LEGAL_DETAILS } from '../legal'
import type { CalendarView, EventItem, NotificationSummary, User } from '../types'
import { api } from '../lib/api'
import { useEffect, useState } from 'react'
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
  const [notifications,setNotifications]=useState<NotificationSummary|null>(null)
  const [notificationsOpen,setNotificationsOpen]=useState(false)
  const loadNotifications=()=>api<NotificationSummary>('/notifications').then(setNotifications).catch(()=>undefined)
  useEffect(()=>{void loadNotifications()},[user.id])
  const markRead=async(id:number)=>setNotifications(await api<NotificationSummary>(`/notifications/${id}/read`,{method:'POST'}))
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
      <div className="notification-menu"><button className="header-icon" aria-label="Уведомления" aria-expanded={notificationsOpen} onClick={()=>{setNotificationsOpen(value=>!value);if(!notificationsOpen)void loadNotifications()}}><Bell/>{Boolean(notifications?.unread)&&<i>{notifications!.unread}</i>}</button>{notificationsOpen&&<div className="notification-popover"><header><b>Уведомления</b><span>{notifications?.unread||0} новых</span></header>{notifications?.items.length?notifications.items.map(item=><button key={item.id} className={item.read_at?'read':''} onClick={()=>void markRead(item.id)}><b>{item.title}</b><span>{item.body}</span><small>{item.status==='sent'?'Отправлено':item.status==='failed'?'Ошибка доставки':'Запланировано'}</small></button>):<p>Новых уведомлений нет.</p>}</div>}</div>
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

export function Sidebar({page,user,open,navigate,onClose,onLogout,onAssistant,onRequisites}:{page:Page;user:User;open:boolean;navigate:(page:Page)=>void;onClose:()=>void;onLogout:()=>void;onAssistant:()=>void;onRequisites:()=>void}) {
  const group=(label:string,entries:NavEntry[])=><div className="nav-group"><p>{label}</p>{entries.map((item,index)=><SidebarItem key={`${label}-${item.label}`} item={item} active={page===item.id&&(item.id!=='analytics'||index===0)} onClick={()=>navigate(item.id)}/>)}</div>
  return <aside className={`sidebar premium-sidebar ${open?'open':''}`}>
    <div className="sidebar-mobile-head"><Logo onClick={()=>navigate('dashboard')}/><button className="icon-btn" onClick={onClose}><X/></button></div>
    <nav>{group('Обзор',overview)}{group('Аналитика',analytics)}<div className="nav-group"><p>Система</p>{system.map(item=><SidebarItem key={`Система-${item.label}`} item={item} active={page===item.id} onClick={()=>navigate(item.id)}/>)}<a className="sidebar-item sidebar-requisites" href="/requisites" onClick={event=>{event.preventDefault();onRequisites()}}><ReceiptText/><span><strong>Реквизиты</strong><small>ИНН {LEGAL_DETAILS.taxId}</small></span></a></div></nav>
    <button className="assistant-status" onClick={onAssistant}><i/><div><b>AI-Ассистент</b><span>Открыть AI-чат</span></div></button>
    <div className="sidebar-account">
      <span className="avatar" style={{background:user.avatar_color}}>{user.name.slice(0,1)}</span>
      <div><b>{user.name}</b><small>{user.occupation||user.email}</small></div>
      <button className="icon-btn" onClick={onLogout} aria-label="Выйти"><LogOut/></button>
    </div>
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
