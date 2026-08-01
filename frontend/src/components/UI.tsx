import { CircleUserRound, X } from 'lucide-react'

export function PageHeader({eyebrow,title,description,action}:{eyebrow:string;title:string;description?:string;action?:React.ReactNode}) {
  return <div className="page-header"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1>{description&&<p>{description}</p>}</div>{action&&<div className="page-action">{action}</div>}</div>
}

export function Modal({title,children,onClose}:{title:string;children:React.ReactNode;onClose:()=>void}) {
  return <div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><div className="modal" role="dialog" aria-modal="true" aria-label={title}><div className="modal-head"><h2>{title}</h2><button className="icon-btn" onClick={onClose} aria-label="Закрыть"><X size={20}/></button></div>{children}</div></div>
}

export function BottomSheet({title,children,onClose}:{title:string;children:React.ReactNode;onClose:()=>void}) {
  return <div className="bottom-sheet"><Modal title={title} onClose={onClose}>{children}</Modal></div>
}

export function Empty({icon:Icon=CircleUserRound,title,text}:{icon?:typeof CircleUserRound;title:string;text:string}) {
  return <div className="empty"><span><Icon/></span><h3>{title}</h3><p>{text}</p></div>
}

export function Loading() { return <div className="section-loader premium-skeleton" aria-busy="true" aria-label="Обновляем данные"><div className="skeleton-title"/><div className="skeleton-grid"><i/><i/><i/><i/></div><div className="skeleton-panel"/><span>Обновляем данные…</span></div> }
