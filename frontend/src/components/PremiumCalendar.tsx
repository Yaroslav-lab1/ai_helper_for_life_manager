import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, CalendarPlus, ChevronLeft, ChevronRight, Clock3, MapPin, Pencil, Plus, Trash2 } from 'lucide-react'
import { api } from '../lib/api'
import type { CalendarView, EnergyForecast, EventItem } from '../types'
import { Loading, Modal } from './UI'
import { CalendarSidebar } from './PremiumShell'
import { AIPlannerPanel } from './CalendarPlanner'
import { QuickEventModal } from './PremiumDashboard'

const startOfWeek=(source:Date)=>{const day=new Date(source);const offset=(day.getDay()+6)%7;day.setDate(day.getDate()-offset);day.setHours(0,0,0,0);return day}
const endOfDay=(source:Date)=>{const value=new Date(source);value.setHours(23,59,59,999);return value}
const dayKey=(value:Date|string)=>new Date(value).toLocaleDateString('sv-SE')
const localDateTime=(value:Date)=>new Date(value.getTime()-value.getTimezoneOffset()*60000).toISOString().slice(0,19)
const eventTone=(category:string)=>category==='work'?'blue':category==='focus'?'gold':category==='health'?'red':category==='ai'?'purple':'green'
const eventIcon=(category:string)=>category==='focus'?'⚡':category==='health'?'◐':category==='work'?'◇':category==='ai'?'✦':'•'
const categoryLabel=(category:string)=>({work:'Работа',focus:'Фокус',health:'Здоровье',ai:'AI-план',personal:'Личное'}[category]||category)

const viewRange=(view:CalendarView,anchor:Date)=>{
  if(view==='day'){const start=new Date(anchor);start.setHours(0,0,0,0);return {start,end:endOfDay(anchor)}}
  if(view==='week'){const start=startOfWeek(anchor);const end=new Date(start);end.setDate(end.getDate()+6);return {start,end:endOfDay(end)}}
  const monthStart=new Date(anchor.getFullYear(),anchor.getMonth(),1);const start=startOfWeek(monthStart);const end=new Date(start);end.setDate(end.getDate()+41);return {start,end:endOfDay(end)}
}

export function CalendarEvent({event,onOpen,onDelete,startHour=6}:{event:EventItem;onOpen:(event:EventItem)=>void;onDelete:(id:number)=>void;startHour?:number}) {
  const start=new Date(event.start_at);const end=new Date(event.end_at);const top=((start.getHours()+start.getMinutes()/60)-startHour)*64;const height=Math.max(40,(+end-+start)/60000/60*64-4)
  return <article className={`week-event ${eventTone(event.category)}`} style={{top:`${Math.max(0,top)}px`,height:`${height}px`}} title={`${event.title} · ${start.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}`} onClick={()=>onOpen(event)} tabIndex={0} role="button" onKeyDown={key=>{if(key.key==='Enter'||key.key===' ')onOpen(event)}}>
    <b>{eventIcon(event.category)} {event.title}</b><span>{start.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})} – {end.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}</span>
    <button onClick={click=>{click.stopPropagation();onDelete(event.id)}} aria-label={`Удалить ${event.title}`}><Trash2/></button>
  </article>
}

export function CalendarGrid({events,weekStart,onOpen,onDelete,onCreate}:{events:EventItem[];weekStart:Date;onOpen:(event:EventItem)=>void;onDelete:(id:number)=>void;onCreate:(date:Date,hour:number)=>void}) {
  const [compact,setCompact]=useState(()=>window.matchMedia('(max-width: 767px)').matches)
  useEffect(()=>{const media=window.matchMedia('(max-width: 767px)');const change=()=>setCompact(media.matches);media.addEventListener('change',change);return()=>media.removeEventListener('change',change)},[])
  const startHour=6;const endHour=23;const hours=Array.from({length:endHour-startHour+1},(_,index)=>startHour+index);const weekDays=Array.from({length:7},(_,index)=>{const day=new Date(weekStart);day.setDate(day.getDate()+index);return day});const now=new Date();const today=dayKey(now);const currentTop=((now.getHours()+now.getMinutes()/60)-startHour)*64
  const currentInWeek=now>=weekStart&&now<new Date(+weekStart+7*86400000);const compactStart=currentInWeek?now:weekStart;const days=compact?Array.from({length:3},(_,index)=>{const day=new Date(compactStart);day.setDate(day.getDate()+index);return day}):weekDays;const columns=`54px repeat(${days.length}, minmax(0, 1fr))`
  return <div className="calendar-grid-wrap calendar-view-animate"><div className="week-grid-head" style={compact?{gridTemplateColumns:columns}:undefined}><span/>{days.map(day=><div key={dayKey(day)} className={dayKey(day)===today?'today':''}><b>{day.toLocaleDateString('ru-RU',{weekday:'short'}).toUpperCase()}</b><em>{day.getDate()}</em></div>)}</div><div className="week-grid-body" style={compact?{gridTemplateColumns:columns}:undefined}>
    <div className="time-axis">{hours.map(hour=><span key={hour} style={{top:`${(hour-startHour)*64}px`}}>{String(hour).padStart(2,'0')}:00</span>)}</div>
    {days.map(day=><div className={`day-column ${dayKey(day)===today?'today':''}`} key={dayKey(day)}>{hours.map(hour=><button aria-label={`Создать событие ${dayKey(day)} ${hour}:00`} className="calendar-hour-slot" key={hour} style={{top:`${(hour-startHour)*64}px`}} onClick={()=>onCreate(day,hour)}/>)}{events.filter(event=>dayKey(event.start_at)===dayKey(day)).map(event=><CalendarEvent key={event.occurrence_id||event.id} event={event} onOpen={onOpen} onDelete={onDelete} startHour={startHour}/>)}{dayKey(day)===today&&currentTop>=0&&currentTop<=(endHour-startHour)*64&&<div className="current-time-line" style={{top:`${currentTop}px`}}><i/></div>}</div>)}
  </div></div>
}

function DayCalendar({date,events,energy,onOpen,onDelete,onCreate}:{date:Date;events:EventItem[];energy:EnergyForecast|null;onOpen:(event:EventItem)=>void;onDelete:(id:number)=>void;onCreate:(date:Date,hour:number)=>void}) {
  const startHour=6;const hours=Array.from({length:18},(_,index)=>startHour+index);const now=new Date();const today=dayKey(now)===dayKey(date);const currentTop=((now.getHours()+now.getMinutes()/60)-startHour)*64
  return <div className="day-calendar calendar-view-animate"><div className="day-grid-head"><span/><div><b>{date.toLocaleDateString('ru-RU',{weekday:'long'}).toUpperCase()}</b><em>{date.getDate()}</em></div></div><div className="day-grid-body"><div className="time-axis">{hours.map(hour=><span key={hour} style={{top:`${(hour-startHour)*64}px`}}>{String(hour).padStart(2,'0')}:00</span>)}</div><div className="day-timeline">{hours.map(hour=>{const point=energy?.points.find(item=>item.hour===hour);return <button key={hour} className={`day-hour-slot ${point?.kind||''}`} style={{top:`${(hour-startHour)*64}px`}} onClick={()=>onCreate(date,hour)}><span>{point?.level&&point.level>=78?`Пик энергии · ${point.level}%`:point?.kind==='recovery'?'Восстановление':''}</span></button>})}{events.map(event=><CalendarEvent key={event.occurrence_id||event.id} event={event} onOpen={onOpen} onDelete={onDelete} startHour={startHour}/>)}{today&&currentTop>=0&&currentTop<=18*64&&<div className="current-time-line" style={{top:`${currentTop}px`}}><i/></div>}</div></div></div>
}

function MonthCalendar({anchor,events,onDay,onOpen}:{anchor:Date;events:EventItem[];onDay:(day:Date)=>void;onOpen:(event:EventItem)=>void}) {
  const first=new Date(anchor.getFullYear(),anchor.getMonth(),1);const start=startOfWeek(first);const days=Array.from({length:42},(_,index)=>{const day=new Date(start);day.setDate(day.getDate()+index);return day});const today=dayKey(new Date())
  return <div className="month-calendar calendar-view-animate"><div className="month-weekdays">{['ПН','ВТ','СР','ЧТ','ПТ','СБ','ВС'].map((day,index)=><b key={day} className={index>4?'weekend':''}>{day}</b>)}</div><div className="month-grid">{days.map((day,index)=>{const items=events.filter(event=>dayKey(event.start_at)===dayKey(day));return <div key={dayKey(day)} className={`month-cell ${day.getMonth()!==anchor.getMonth()?'outside':''} ${dayKey(day)===today?'today':''} ${index%7>4?'weekend':''}`}><button className="month-day-number" onClick={()=>onDay(day)} aria-label={`Открыть ${day.toLocaleDateString('ru-RU')}`}>{day.getDate()}</button><div className="month-events">{items.slice(0,3).map(event=><button key={event.occurrence_id||event.id} className={eventTone(event.category)} onClick={()=>onOpen(event)}><i/>{new Date(event.start_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})} {event.title}</button>)}{items.length>3&&<button className="month-more" onClick={()=>onDay(day)}>+ ещё {items.length-3}</button>}</div></div>})}</div></div>
}

function EventDetailsModal({event,onClose,onEdit,onDelete}:{event:EventItem;onClose:()=>void;onEdit:(event:EventItem)=>void;onDelete:(id:number)=>void}) {
  const start=new Date(event.start_at);const end=new Date(event.end_at)
  return <Modal title="Детали события" onClose={onClose}><div className="event-details"><span className={`event-detail-mark ${eventTone(event.category)}`}>{eventIcon(event.category)}</span><div><BadgeLike tone={eventTone(event.category)}>{categoryLabel(event.category)}</BadgeLike><h3>{event.title}</h3>{event.description&&<p>{event.description}</p>}{event.recurrence_rule&&<small>Изменение и удаление применяются ко всей серии.</small>}</div><dl><div><dt><Clock3/> Время</dt><dd>{start.toLocaleDateString('ru-RU',{weekday:'long',day:'numeric',month:'long'})}<br/>{start.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}–{end.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}</dd></div>{event.location&&<div><dt><MapPin/> Место</dt><dd>{event.location}</dd></div>}</dl><div className="event-detail-actions"><button className="secondary" onClick={onClose}>Закрыть</button><button className="secondary" onClick={()=>onEdit(event)}><Pencil/> Редактировать серию</button><button className="danger-button" onClick={()=>onDelete(event.id)}><Trash2/> Удалить серию</button></div></div></Modal>
}
const BadgeLike=({children,tone}:{children:React.ReactNode;tone:string})=><span className={`badge badge-${tone}`}>{children}</span>

export default function PremiumCalendarPage({view,onView,plannerOpen,onPlannerOpen,onPlannerClose,onChanged}:{view:CalendarView;onView:(view:CalendarView)=>void;plannerOpen:boolean;onPlannerOpen:()=>void;onPlannerClose:()=>void;onChanged:()=>void}) {
  const [events,setEvents]=useState<EventItem[]|null>(null);const [error,setError]=useState('');const [modal,setModal]=useState(false);const [details,setDetails]=useState<EventItem|null>(null);const [eventToEdit,setEventToEdit]=useState<EventItem|undefined>();const [createStart,setCreateStart]=useState<Date|undefined>();const [energy,setEnergy]=useState<EnergyForecast|null>(null);const mainRef=useRef<HTMLElement>(null)
  const [anchor,setAnchor]=useState(()=>{const saved=localStorage.getItem('axel_calendar_date');const parsed=saved?new Date(`${saved}T12:00`):new Date();return Number.isNaN(+parsed)?new Date():parsed})
  const range=useMemo(()=>viewRange(view,anchor),[view,anchor]);const weekStart=useMemo(()=>startOfWeek(anchor),[anchor])
  const persistAnchor=(next:Date)=>{setAnchor(next);localStorage.setItem('axel_calendar_date',dayKey(next))}
  const load=()=>api<EventItem[]>(`/events?start=${encodeURIComponent(localDateTime(range.start))}&end=${encodeURIComponent(localDateTime(range.end))}`).then(items=>{setEvents(items);setError('')}).catch(err=>setError(err instanceof Error?err.message:'Не удалось загрузить календарь'))
  useEffect(()=>{setEvents(null);void load()},[view,anchor])
  useEffect(()=>{void api<EnergyForecast>(`/energy?date=${dayKey(anchor)}`).then(setEnergy).catch(()=>setEnergy(null))},[anchor])
  useEffect(()=>{const open=()=>{const start=new Date(anchor);start.setHours(Math.min(22,new Date().getHours()+1),0,0,0);setEventToEdit(undefined);setCreateStart(start);setModal(true)};window.addEventListener('axel:add-event',open);return()=>window.removeEventListener('axel:add-event',open)},[anchor])
  useEffect(()=>{if(!events)return;const now=new Date();const target=view==='month'?0:dayKey(anchor)===dayKey(now)?Math.max(0,(now.getHours()-7)*64):96;requestAnimationFrame(()=>{if(mainRef.current)mainRef.current.scrollTop=target})},[events,view,anchor])
  const navigate=(offset:number)=>{const next=new Date(anchor);if(view==='day')next.setDate(next.getDate()+offset);else if(view==='week')next.setDate(next.getDate()+offset*7);else next.setMonth(next.getMonth()+offset);persistAnchor(next)}
  const remove=async(id:number)=>{if(!confirm('Удалить событие?'))return;await api(`/events/${id}`,{method:'DELETE'});setDetails(null);void load();onChanged()}
  const createAt=(date:Date,hour:number)=>{const start=new Date(date);start.setHours(hour,0,0,0);setEventToEdit(undefined);setCreateStart(start);setModal(true)}
  const edit=async(event:EventItem)=>{setDetails(null);setCreateStart(undefined);try{setEventToEdit(await api<EventItem>(`/events/${event.series_id||event.id}`));setModal(true)}catch(err){setError(err instanceof Error?err.message:'Не удалось загрузить серию')}}
  const title=view==='day'?anchor.toLocaleDateString('ru-RU',{weekday:'long',day:'numeric',month:'long',year:'numeric'}):view==='month'?anchor.toLocaleDateString('ru-RU',{month:'long',year:'numeric'}):`${weekStart.toLocaleDateString('ru-RU',{day:'numeric',month:'short'})} — ${new Date(+weekStart+6*86400000).toLocaleDateString('ru-RU',{day:'numeric',month:'short',year:'numeric'})}`
  return <div className="calendar-workspace">
    <CalendarSidebar events={events||[]} selectedDate={anchor} onSelect={day=>{persistAnchor(day);onView('day')}}/>
    <main className="calendar-main" ref={mainRef}><div className="calendar-toolbar"><div><button onClick={()=>navigate(-1)} aria-label="Предыдущий период"><ChevronLeft/></button><button className="today-button" onClick={()=>persistAnchor(new Date())}>Сегодня</button><button onClick={()=>navigate(1)} aria-label="Следующий период"><ChevronRight/></button><h1>{title}</h1></div><p>{view==='day'?'День':view==='week'?'Неделя':'Месяц'} · {events?.length||0} событий <b>· AI-анализ активен</b></p><button className="calendar-ai-trigger" onClick={onPlannerOpen}>AI-план</button><button className="calendar-add-inline" onClick={()=>{setEventToEdit(undefined);setCreateStart(undefined);setModal(true)}}><Plus/> Событие</button></div>
      {!events&&!error?<Loading/>:error?<div className="error-state compact"><AlertTriangle/><h3>Не удалось загрузить календарь</h3><p>{error}</p><button onClick={()=>void load()}>Повторить</button></div>:view==='day'?<DayCalendar date={anchor} events={events||[]} energy={energy} onOpen={setDetails} onDelete={id=>void remove(id)} onCreate={createAt}/>:view==='week'?<CalendarGrid events={events||[]} weekStart={weekStart} onOpen={setDetails} onDelete={id=>void remove(id)} onCreate={createAt}/>:<MonthCalendar anchor={anchor} events={events||[]} onDay={day=>{persistAnchor(day);onView('day')}} onOpen={setDetails}/>} 
    </main>
    <AIPlannerPanel events={events||[]} selectedDate={dayKey(anchor)} open={plannerOpen} onClose={onPlannerClose} onCalendarChanged={()=>{void load();onChanged()}}/>
    {modal&&<QuickEventModal initialStart={createStart} eventToEdit={eventToEdit} onClose={()=>setModal(false)} onSaved={()=>{setModal(false);setEventToEdit(undefined);void load();onChanged()}}/>}{details&&<EventDetailsModal event={details} onClose={()=>setDetails(null)} onEdit={event=>void edit(event)} onDelete={id=>void remove(id)}/>}
  </div>
}
