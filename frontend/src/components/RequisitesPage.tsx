import { ArrowLeft, BadgeCheck, Mail, ReceiptText } from 'lucide-react'
import { useEffect } from 'react'
import { LEGAL_DETAILS } from '../legal'
import { Logo } from './PremiumShell'

export function RequisitesPage({onBack}:{onBack:()=>void}) {
  useEffect(()=>{
    const previousTitle=document.title
    document.title='Контакты и реквизиты — AXEL ONE'
    return()=>{document.title=previousTitle}
  },[])

  return <div className="requisites-page">
    <header className="requisites-header">
      <Logo onClick={onBack}/>
      <button type="button" className="requisites-back" onClick={onBack}><ArrowLeft/>Вернуться на сайт</button>
    </header>

    <main className="requisites-main">
      <section className="requisites-intro">
        <span className="requisites-eyebrow"><ReceiptText/>Информация о продавце</span>
        <h1>Контакты и реквизиты</h1>
        <p>Официальные сведения о продавце и контакты сервиса AXEL ONE.</p>
      </section>

      <section className="requisites-card" aria-labelledby="seller-details-title">
        <div className="requisites-card-heading">
          <span><BadgeCheck/></span>
          <div><small>Продавец</small><h2 id="seller-details-title">{LEGAL_DETAILS.operatorName}</h2></div>
        </div>
        <dl>
          <div><dt>Наименование проекта</dt><dd>AXEL ONE</dd></div>
          <div className="requisites-tax-id"><dt>ИНН продавца</dt><dd>{LEGAL_DETAILS.taxId}</dd></div>
          <div><dt>Статус</dt><dd>{LEGAL_DETAILS.status}</dd></div>
          <div><dt>Адрес сайта</dt><dd><a href={LEGAL_DETAILS.siteUrl}>axel-one.ru</a></dd></div>
        </dl>
      </section>

      <section className="requisites-contact" aria-labelledby="contact-title">
        <Mail/>
        <div><small>Связаться с нами</small><h2 id="contact-title">По вопросам оплаты и работы сервиса</h2><a href={`mailto:${LEGAL_DETAILS.email}`}>{LEGAL_DETAILS.email}</a></div>
      </section>
    </main>

    <footer className="requisites-footer">© {new Date().getFullYear()} AXEL ONE</footer>
  </div>
}
