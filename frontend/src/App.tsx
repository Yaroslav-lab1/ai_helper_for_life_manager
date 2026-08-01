import { useEffect, useState } from 'react'
import { BarChart3, CalendarDays, ChevronRight, Diamond, Goal, LayoutDashboard, Sparkles, Target } from 'lucide-react'
import { api, session } from './lib/api'
import type { CalendarView, Tokens, User } from './types'
import { AnalyticsPage, GoalsPage, HabitsPage, SettingsPage, TasksPage } from './components/Pages'
import PremiumDashboardPage from './components/PremiumDashboard'
import PremiumCalendarPage from './components/PremiumCalendar'
import { AIAssistantPanel, AppHeader, Logo, MobileScrim, Sidebar } from './components/PremiumShell'
import { PrivacyPolicy } from './components/PrivacyPolicy'

export type Page = 'dashboard'|'calendar'|'tasks'|'goals'|'habits'|'analytics'|'settings'

const mobileNav:{id:Page;label:string;icon:typeof LayoutDashboard}[]=[
  {id:'dashboard',label:'Главная',icon:LayoutDashboard},
  {id:'calendar',label:'Календарь',icon:CalendarDays},
  {id:'tasks',label:'Решения',icon:Diamond},
  {id:'goals',label:'Цели',icon:Goal},
  {id:'analytics',label:'Баланс',icon:Target},
]

export default function App() {
  const [user,setUser]=useState<User|null>(null)
  const [checking,setChecking]=useState(true)
  const [page,setPage]=useState<Page>('dashboard')
  const [menu,setMenu]=useState(false)
  const [assistant,setAssistant]=useState(false)
  const [refreshKey,setRefreshKey]=useState(0)
  const [calendarView,setCalendarViewState]=useState<CalendarView>(()=>{
    const saved=localStorage.getItem('axel_calendar_view')
    return saved==='day'||saved==='month'?saved:'week'
  })

  useEffect(()=>{document.documentElement.dataset.theme='dark';document.documentElement.style.colorScheme='dark'},[])
  useEffect(()=>{const open=()=>setAssistant(true);window.addEventListener('axel:open-ai',open);return()=>window.removeEventListener('axel:open-ai',open)},[])
  useEffect(()=>{if(!session.access){setChecking(false);return}api<User>('/auth/me').then(setUser).catch(()=>session.clear()).finally(()=>setChecking(false))},[])

  const authenticated=(tokens:Tokens)=>{session.save(tokens);setUser(tokens.user)}
  const logout=()=>{void api('/auth/logout',{method:'POST'}).catch(()=>undefined).finally(()=>{session.clear();setUser(null);setMenu(false)})}
  const navigate=(next:Page)=>{setPage(next);setMenu(false);window.scrollTo({top:0,behavior:'smooth'})}
  const changed=()=>setRefreshKey(value=>value+1)
  const setCalendarView=(view:CalendarView)=>{setCalendarViewState(view);localStorage.setItem('axel_calendar_view',view)}

  if(checking)return <div className="app-loader"><Logo/><span>Собираем ваш день…</span></div>
  if(!user)return <AuthScreen onAuth={authenticated}/>

  const pages:Record<Exclude<Page,'calendar'>,React.ReactNode>={
    dashboard:<PremiumDashboardPage key={`d${refreshKey}`} navigate={navigate} onChanged={changed}/>,
    tasks:<TasksPage key={`t${refreshKey}`} onChanged={changed}/>,
    goals:<GoalsPage key={`g${refreshKey}`} onChanged={changed}/>,
    habits:<HabitsPage key={`h${refreshKey}`} onChanged={changed}/>,
    analytics:<AnalyticsPage key={`a${refreshKey}`}/>,
    settings:<SettingsPage user={user} onUser={setUser}/>,
  }
  return <div className={`app-shell ${page==='calendar'?'calendar-mode':''}`}>
    <AppHeader page={page} user={user} calendarView={calendarView} onCalendarView={setCalendarView} onMenu={()=>setMenu(true)} onAssistant={()=>setAssistant(true)} onHome={()=>navigate('dashboard')}/>
    <Sidebar page={page} user={user} open={menu} navigate={navigate} onClose={()=>setMenu(false)} onLogout={logout} onAssistant={()=>setAssistant(true)}/>
    {page==='calendar'?<PremiumCalendarPage key={`c${refreshKey}`} view={calendarView} onView={setCalendarView} plannerOpen={assistant} onPlannerOpen={()=>setAssistant(true)} onPlannerClose={()=>setAssistant(false)} onChanged={changed}/>:<>
      <main className="workspace-main">{pages[page as Exclude<Page,'calendar'>]}</main>
      <AIAssistantPanel open={assistant} onClose={()=>setAssistant(false)}/>
    </>}
    <MobileScrim visible={menu||assistant} onClick={()=>{setMenu(false);setAssistant(false)}}/>
    <nav className="mobile-nav premium-mobile-nav">{mobileNav.map(item=><button key={item.id} className={page===item.id?'active':''} onClick={()=>navigate(item.id)}><item.icon/><span>{item.label}</span></button>)}</nav>
  </div>
}

function AuthScreen({onAuth}:{onAuth:(tokens:Tokens)=>void}) {
  const pathMode=window.location.pathname.endsWith('/reset-password')?'reset':window.location.pathname.endsWith('/verify-email')?'verify':'login'
  const [mode,setMode]=useState<'login'|'register'|'forgot'|'reset'|'verify'>(pathMode)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [loading,setLoading]=useState(false)
  const [privacy,setPrivacy]=useState(false)
  const [form,setForm]=useState({name:'',email:'',password:'',newPassword:''})
  useEffect(()=>{if(mode!=='verify')return;const token=new URLSearchParams(location.search).get('token');if(!token){setError('Ссылка подтверждения неполная');return}setLoading(true);api<{message:string}>('/auth/verify-email',{method:'POST',body:JSON.stringify({token})}).then(data=>setNotice(data.message)).catch(err=>setError(err instanceof Error?err.message:'Не удалось подтвердить email')).finally(()=>setLoading(false))},[mode])
  const submit=async(event:React.FormEvent)=>{
    event.preventDefault();setError('');setNotice('');setLoading(true)
    try{
      if(mode==='forgot'){const result=await api<{message:string}>('/auth/forgot-password',{method:'POST',body:JSON.stringify({email:form.email})});setNotice(result.message);return}
      if(mode==='reset'){const token=new URLSearchParams(location.search).get('token');if(!token)throw new Error('Ссылка сброса неполная');const result=await api<{message:string}>('/auth/reset-password',{method:'POST',body:JSON.stringify({token,new_password:form.newPassword})});setNotice(result.message);return}
      const body=mode==='login'?{email:form.email,password:form.password}:{name:form.name,email:form.email,password:form.password,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone}
      onAuth(await api<Tokens>(`/auth/${mode}`,{method:'POST',body:JSON.stringify(body)}))
    }catch(err){setError(err instanceof Error?err.message:'Ошибка авторизации')}finally{setLoading(false)}
  }
  const demo=()=>{setForm({name:'Алексей',email:'demo@axel.one',password:import.meta.env.VITE_DEMO_PASSWORD||'',newPassword:''});setMode('login')}
  const demoEnabled=import.meta.env.VITE_ENABLE_DEMO_LOGIN==='true'
  return <div className="auth-layout premium-auth">
    <section className="auth-story"><Logo/><div className="story-copy"><span className="eyebrow">Персональная система управления</span><h1>Главное —<br/>в поле зрения.</h1><p>Планы, цели, привычки и баланс соединены в одно спокойное пространство с персональным AI-ассистентом.</p></div><div className="story-preview"><div className="preview-top"><span>Индекс вашего дня</span><b>82</b></div><div className="preview-line"><i/><span><b>09:00</b> Глубокая работа над главным</span></div><div className="preview-line"><i className="mint"/><span><b>13:00</b> Время на восстановление</span></div><div className="preview-ai"><Sparkles/><span>Сегодня хороший день, чтобы закончить важное без перегрузки.</span></div></div><small className="auth-footer">AXEL ONE · conscious productivity</small></section>
    <section className="auth-form-wrap"><form className="auth-form" onSubmit={submit}><Logo/><div><span className="eyebrow">Добро пожаловать</span><h2>{mode==='register'?'Создайте своё пространство':mode==='forgot'?'Восстановление доступа':mode==='reset'?'Новый пароль':mode==='verify'?'Подтверждение email':'Продолжим с главного'}</h2><p>{mode==='register'?'Axel поможет собрать вашу персональную систему.':mode==='forgot'?'Мы отправим одноразовую ссылку, если аккаунт существует.':mode==='reset'?'Задайте новый пароль длиной не менее 12 символов.':mode==='verify'?'Проверяем одноразовую ссылку.':'Войдите, чтобы увидеть актуальный план и рекомендации.'}</p></div>
      {(mode==='login'||mode==='register')&&<div className="auth-tabs"><button type="button" className={mode==='login'?'active':''} onClick={()=>setMode('login')}>Войти</button><button type="button" className={mode==='register'?'active':''} onClick={()=>setMode('register')}>Регистрация</button></div>}
      {mode==='register'&&<label>Как вас зовут<input required minLength={2} value={form.name} onChange={event=>setForm({...form,name:event.target.value})} placeholder="Имя и фамилия"/></label>}
      {(mode==='login'||mode==='register'||mode==='forgot')&&<label>Email<input required type="email" value={form.email} onChange={event=>setForm({...form,email:event.target.value})} placeholder="you@example.com"/></label>}
      {(mode==='login'||mode==='register')&&<label>Пароль<input required type="password" minLength={mode==='register'?12:1} value={form.password} onChange={event=>setForm({...form,password:event.target.value})} placeholder={mode==='register'?'Минимум 12 символов':'Ваш пароль'}/></label>}
      {mode==='reset'&&<label>Новый пароль<input required type="password" minLength={12} value={form.newPassword} onChange={event=>setForm({...form,newPassword:event.target.value})} placeholder="Минимум 12 символов"/></label>}
      {error&&<div className="form-error">{error}</div>}{notice&&<div className="form-success">{notice}</div>}
      {mode!=='verify'&&<button className="primary wide" disabled={loading}>{loading?'Подождите…':mode==='login'?'Войти в Axel One':mode==='register'?'Создать аккаунт':mode==='forgot'?'Отправить ссылку':'Сохранить пароль'}<ChevronRight/></button>}
      {mode==='login'&&<button className="demo-button" type="button" onClick={()=>setMode('forgot')}>Забыли пароль?</button>}
      {(mode==='forgot'||mode==='reset'||mode==='verify')&&<button className="demo-button" type="button" onClick={()=>setMode('login')}>Вернуться ко входу</button>}
      {demoEnabled&&mode==='login'&&<><button className="demo-button" type="button" onClick={demo}>Заполнить данные локального демо-аккаунта</button><small className="form-note">Доступно только в development</small></>}
      <button className="privacy-link" type="button" onClick={()=>setPrivacy(true)}>Политика конфиденциальности</button>
    </form></section>
    {privacy&&<PrivacyPolicy onClose={()=>setPrivacy(false)}/>}
  </div>
}
