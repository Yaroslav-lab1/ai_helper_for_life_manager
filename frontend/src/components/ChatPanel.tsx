import { useEffect, useRef, useState } from 'react'
import { ArrowUp, Bot, ChevronDown, History, Plus, RotateCcw, ShieldCheck, Sparkles, Square, Trash2, X } from 'lucide-react'
import { api, streamAIChat } from '../lib/api'
import type { AIActionProposal, AIConsent, AIConversation, AIStatus, ChatMessage } from '../types'
import { PrivacyPolicy } from './PrivacyPolicy'

const quickPrompts=[
  'Оптимизируй мой сегодняшний день','Составь план на завтра','Найди время для тренировки',
  'Какие задачи лучше перенести?','Оцени мою нагрузку','Как быстрее достичь текущей цели?',
]

export function ChatPanel({onClose}:{onClose:()=>void}) {
  const [messages,setMessages]=useState<ChatMessage[]>([])
  const [conversations,setConversations]=useState<AIConversation[]>([])
  const [conversationId,setConversationId]=useState<number|undefined>()
  const [status,setStatus]=useState<AIStatus|null>(null)
  const [consent,setConsent]=useState<AIConsent|null>(null)
  const [consentChecked,setConsentChecked]=useState(false)
  const [privacy,setPrivacy]=useState(false)
  const [text,setText]=useState('');const [sending,setSending]=useState(false);const [error,setError]=useState('')
  const endRef=useRef<HTMLDivElement>(null);const controllerRef=useRef<AbortController|null>(null)

  const refreshConversations=async()=>{const items=await api<AIConversation[]>('/ai/conversations');setConversations(items);return items}
  const openConversation=async(id:number)=>{setConversationId(id);setMessages(await api<ChatMessage[]>(`/ai/conversations/${id}/messages`));setError('')}
  useEffect(()=>{
    void api<AIStatus>('/ai/status').then(setStatus).catch(e=>setStatus({available:false,provider:'unknown',model:'не определена',message:e.message}))
    void api<AIConsent>('/settings/ai-consent').then(setConsent)
    void refreshConversations().then(async items=>{if(items[0])await openConversation(items[0].id)})
  },[])
  useEffect(()=>{endRef.current?.scrollIntoView({behavior:'smooth'})},[messages])
  useEffect(()=>()=>controllerRef.current?.abort(),[])

  const newConversation=()=>{controllerRef.current?.abort();setConversationId(undefined);setMessages([]);setError('');setText('')}
  const clearConversation=async()=>{
    if(conversationId){await api(`/ai/conversations/${conversationId}`,{method:'DELETE'});await refreshConversations()}
    newConversation()
  }
  const stop=()=>{controllerRef.current?.abort();controllerRef.current=null;setSending(false)}

  const send=async(value=text)=>{
    const message=value.trim();if(!message||sending||!consent||(consent.required&&!consent.active))return
    setText('');setSending(true);setError('')
    const assistantIndex=messages.length+1
    setMessages(prev=>[...prev,{role:'user',content:message},{role:'assistant',content:''}])
    const controller=new AbortController();controllerRef.current=controller
    try{
      await streamAIChat({message,conversation_id:conversationId},event=>{
        if(event.event==='meta'&&event.conversation_id){setConversationId(event.conversation_id);void refreshConversations()}
        if(event.event==='chunk'&&event.text)setMessages(prev=>prev.map((item,index)=>index===assistantIndex?{...item,content:item.content+event.text}:item))
        if(event.event==='done'){
          if(event.conversation_id)setConversationId(event.conversation_id)
          setMessages(prev=>prev.map((item,index)=>index===assistantIndex?{...item,id:event.message_id,proposals:event.proposals}:item))
        }
      },controller.signal)
      await refreshConversations()
      void api<AIStatus>('/ai/status').then(setStatus)
    }catch(err){
      if((err as Error).name!=='AbortError'){
        const messageText=err instanceof Error?err.message:'Не удалось ответить'
        setError(messageText)
        setMessages(prev=>prev.map((item,index)=>index===assistantIndex&&item.content===''?{...item,content:messageText}:item))
      }
    }finally{if(controllerRef.current===controller)controllerRef.current=null;setSending(false)}
  }

  const retry=()=>{const last=[...messages].reverse().find(item=>item.role==='user');if(last)void send(last.content)}
  const updateProposal=async(proposal:AIActionProposal,action:'confirm'|'cancel')=>{
    try{
      const updated=action==='confirm'
        ?await api<AIActionProposal>(`/ai/action-proposals/${proposal.id}/confirm`,{method:'POST'})
        :await api<AIActionProposal>(`/ai/action-proposals/${proposal.id}`,{method:'PATCH',body:JSON.stringify({status:'cancelled'})})
      setMessages(prev=>prev.map(item=>({...item,proposals:item.proposals?.map(p=>p.id===updated.id?updated:p)})))
    }catch(err){setError(err instanceof Error?err.message:'Не удалось обработать предложение')}
  }
  const editProposal=(proposal:AIActionProposal)=>{
    const change=window.prompt('Что изменить в предложении?',proposal.description)
    if(change?.trim()){void updateProposal(proposal,'cancel');void send(`Измени предложение «${proposal.title}»: ${change.trim()}`)}
  }
  const acceptConsent=async()=>{
    if(!consentChecked||!consent)return
    setConsent(await api<AIConsent>('/settings/ai-consent',{method:'POST',body:JSON.stringify({accepted:true,policy_version:consent.policy_version})}))
    setConsentChecked(false)
  }

  return <><button className="chat-scrim" onClick={onClose} aria-label="Закрыть чат"/><aside className="chat-panel">
    <header><div className="ai-avatar"><Sparkles/></div><div><b>Axel AI</b><span className={status?.available?'online':'offline'}><i/> {status?.available?`${status.model} · ${status.provider==='gigachat'?'облако Сбера':'локально'}`:'нейросеть недоступна'}</span></div><button className="icon-btn" onClick={onClose}><X/></button></header>
    <div className="chat-toolbar">
      <label><History/><select value={conversationId||''} onChange={e=>e.target.value?void openConversation(+e.target.value):newConversation()}><option value="">Новый диалог</option>{conversations.map(item=><option key={item.id} value={item.id}>{item.title}</option>)}</select><ChevronDown/></label>
      <button onClick={newConversation} title="Новый диалог"><Plus/></button><button onClick={()=>void clearConversation()} disabled={!conversationId} title="Очистить диалог"><Trash2/></button>
    </div>
    {!status?.available&&status&&<div className="chat-error-state"><Bot/><span>{status.message}</span><button onClick={()=>api<AIStatus>('/ai/status').then(setStatus)}><RotateCcw/> Проверить</button></div>}
    {status?.available&&<div className="chat-context"><Bot size={15}/> Контекст ограничен вашими задачами, встречами, целями и нагрузкой</div>}
    {consent?.required&&!consent.active?<div className="chat-consent-gate"><ShieldCheck/><h3>Нужно ваше согласие</h3><p>Для ответа GigaChat получит ваш вопрос и минимизированный контекст: события, задачи, цели, привычки и показатели нагрузки.</p><button className="privacy-link" onClick={()=>setPrivacy(true)}>Прочитать политику</button><label><input type="checkbox" checked={consentChecked} onChange={e=>setConsentChecked(e.target.checked)}/><span>Я явно соглашаюсь на передачу описанного контекста в GigaChat.</span></label><button className="primary" disabled={!consentChecked} onClick={()=>void acceptConsent()}>Согласиться и продолжить</button></div>:<>
    <div className="messages">
      {messages.length===0&&<div className="chat-welcome"><span><Sparkles/></span><h3>С чего начнём?</h3><p>Можно разобрать день, выбрать приоритет или найти способ снизить нагрузку.</p></div>}
      {messages.map((item,index)=><div key={item.id||index} className={`message ${item.role}`}><span>{item.content||<i className="typing"><b/><b/><b/></i>}</span>{item.proposals?.map(proposal=><article className="action-proposal" key={proposal.id}><b>{proposal.title}</b><p>{proposal.description}</p>{proposal.status==='pending'?<div><button className="primary" onClick={()=>void updateProposal(proposal,'confirm')}>Подтвердить</button><button onClick={()=>editProposal(proposal)}>Изменить</button><button onClick={()=>void updateProposal(proposal,'cancel')}>Отменить</button></div>:<small>{proposal.status==='confirmed'?'Подтверждено':'Отменено'}</small>}</article>)}</div>)}
      <div ref={endRef}/>
    </div>
      {messages.length===0&&<div className="chat-prompts">{quickPrompts.map(item=><button key={item} onClick={()=>void send(item)} disabled={!status?.available||!consent}>{item}</button>)}</div>}
    {error&&<div className="chat-inline-error"><span>{error}</span><button onClick={retry}><RotateCcw/> Повторить</button></div>}
    <form className="chat-input" onSubmit={e=>{e.preventDefault();void send()}}><textarea rows={1} value={text} maxLength={4000} onChange={e=>setText(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();void send()}}} placeholder="Спросите о планах, целях или балансе…"/>{sending?<button type="button" className="stop" onClick={stop} title="Остановить"><Square/></button>:<button disabled={!text.trim()||!status?.available||!consent}><ArrowUp/></button>}</form></>}
  </aside>{privacy&&<PrivacyPolicy onClose={()=>setPrivacy(false)}/>}</>
}
