import {
  ArrowRight,
  Check,
  CheckCircle,
  ClipboardText,
  Clock,
  Copy,
  Factory,
  FileMagnifyingGlass,
  Heart,
  LinkSimple,
  Scissors,
  ShieldCheck,
  Sparkle,
  WarningCircle,
  X,
} from '@phosphor-icons/react'
import { useState } from 'react'
import { policyIcons } from './PolicyFinder'
import { roleLabels, serviceTimelines, stageLabels } from '../data'

const roleIcons = {
  product: Factory,
  salon: Scissors,
  care: Heart,
}

function LocalizedList({ items, lang, icon: Icon = Check }) {
  return (
    <ul>
      {items.map((item, index) => (
        <li key={`${item[lang]}-${index}`}><Icon size={16} weight="bold" /> <span>{item[lang]}</span></li>
      ))}
    </ul>
  )
}

export default function PolicyDetail({ lang, c, policy, products, onClaim }) {
  const [copyState, setCopyState] = useState('idle')
  const Icon = policyIcons[policy.id] || Sparkle
  const applicableProducts = products.filter((item) => policy.products.includes(item.id))
  const timeline = serviceTimelines[policy.stage]

  const copyPolicyLink = async () => {
    const url = `${window.location.origin}${window.location.pathname}${window.location.search}#policy-${policy.id}`
    let success = false
    try {
      await navigator.clipboard.writeText(url)
      success = true
    } catch {
      let input
      try {
        input = document.createElement('textarea')
        input.value = url
        document.body.appendChild(input)
        input.select()
        success = document.execCommand('copy')
      } catch {
        success = false
      } finally {
        input?.remove()
      }
    }
    setCopyState(success ? 'copied' : 'failed')
    window.setTimeout(() => setCopyState('idle'), 2200)
  }

  return (
    <article id="policy-detail" className="policy-detail" aria-labelledby="policy-title">
      <header className="policy-detail__header">
        <div className="policy-detail__identity">
          <span className="policy-detail__icon"><Icon size={29} weight="duotone" /></span>
          <div>
            <div className="policy-detail__meta">
              <span>{policy.code}</span>
              <i>{stageLabels[policy.stage][lang]}</i>
            </div>
            <h2 id="policy-title">{policy.title[lang]}</h2>
            <p>{policy.short[lang]}</p>
          </div>
        </div>
        <button className="copy-link" type="button" onClick={copyPolicyLink}>
          {copyState === 'copied' ? <CheckCircle size={17} weight="fill" /> : <LinkSimple size={17} />}
          {copyState === 'copied' ? c.linkCopied : copyState === 'failed' ? c.copyFailed : c.copyLink}
        </button>
      </header>

      <section className="policy-facts" aria-label={c.policyTiming}>
        <div>
          <span><Clock size={17} weight="duotone" /> {c.reviewWindow}</span>
          <strong>{policy.window[lang]}</strong>
        </div>
        <div>
          <span><ClipboardText size={17} weight="duotone" /> {c.notifyBy}</span>
          <strong>{policy.notify[lang]}</strong>
        </div>
        <div>
          <span><ShieldCheck size={17} weight="duotone" /> {c.responseTime}</span>
          <strong>{c.businessHours}</strong>
        </div>
      </section>
      <div className="policy-clock-note">
        <span>{c.evidenceClock}</span>
        <span>{c.discoveryRule}</span>
      </div>

      <section className="applies-row">
        <span>{c.appliesTo}</span>
        <div>{applicableProducts.map((item) => <i key={item.id}>{item.label[lang]}</i>)}</div>
      </section>

      <section className="detail-section">
        <div className="detail-section__heading">
          <span>01</span>
          <div><small>{c.decisionBasis}</small><h3>{c.causes}</h3></div>
        </div>
        <div className="cause-grid">
          {policy.causes.map((cause) => {
            const CauseIcon = roleIcons[cause.role]
            return (
              <div className={`cause-card cause-card--${cause.role}`} key={cause.role}>
                <span><CauseIcon size={20} weight="duotone" /></span>
                <small>{roleLabels[cause.role][lang]}</small>
                <p>{cause.text[lang]}</p>
              </div>
            )
          })}
        </div>
      </section>

      <section className="detail-section detail-section--split">
        <div className="detail-section__heading">
          <span>02</span>
          <div><small>{c.decisionBasis}</small><h3>{c.verify}</h3></div>
        </div>
        <ol className="test-list">
          {policy.tests.map((test, index) => (
            <li key={test[lang]}>
              <span>{String(index + 1).padStart(2, '0')}</span>
              <p>{test[lang]}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="detail-section">
        <div className="detail-section__heading">
          <span>03</span>
          <div><small>{c.decisionBasis}</small><h3>{c.coverage}</h3></div>
        </div>
        <div className="coverage-grid">
          <div className="coverage-card coverage-card--included">
            <div><CheckCircle size={20} weight="fill" /><h4>{c.included}</h4></div>
            <LocalizedList items={policy.coverage.included} lang={lang} />
          </div>
          <div className="coverage-card coverage-card--conditional">
            <div><WarningCircle size={20} weight="fill" /><h4>{c.conditional}</h4></div>
            <LocalizedList items={policy.coverage.conditional} lang={lang} icon={ArrowRight} />
          </div>
          <div className="coverage-card coverage-card--excluded">
            <div><X size={20} weight="bold" /><h4>{c.excluded}</h4></div>
            <LocalizedList items={policy.coverage.excluded} lang={lang} icon={X} />
          </div>
        </div>
      </section>

      <section className="detail-section detail-section--paired">
        <div className="paired-panel">
          <div className="detail-section__heading">
            <span>04</span>
            <div><small>{c.decisionBasis}</small><h3>{c.outcomes}</h3></div>
          </div>
          <LocalizedList items={policy.outcomes} lang={lang} icon={ShieldCheck} />
        </div>
        <div className="paired-panel paired-panel--evidence">
          <div className="detail-section__heading">
            <span>05</span>
            <div><small>{c.claimChecklist}</small><h3>{c.evidence}</h3></div>
          </div>
          <LocalizedList items={policy.evidence} lang={lang} icon={FileMagnifyingGlass} />
        </div>
      </section>

      <section className="detail-section detail-section--timeline">
        <div className="detail-section__heading">
          <span>06</span>
          <div><small>{stageLabels[policy.stage][lang]}</small><h3>{c.serviceTimeline}</h3></div>
        </div>
        <div className="service-timeline">
          {[
            [c.timelineAssessment, timeline.assessment[lang]],
            [c.timelineDecision, timeline.decision[lang]],
            [c.timelineExecution, timeline.execution[lang]],
          ].map(([label, value], index) => (
            <div key={label}>
              <span>{String(index + 1).padStart(2, '0')}</span>
              <small>{label}</small>
              <p>{value}</p>
            </div>
          ))}
        </div>
        <p className="remedy-ownership"><ShieldCheck size={16} weight="duotone" /> {c.remedyOwnership}</p>
      </section>

      <section className="salon-alignment">
        <div className="salon-alignment__intro">
          <small>{c.salonStandard}</small>
          <h3>{c.salonIntro}</h3>
        </div>
        <div>
          <h4><Scissors size={19} weight="duotone" /> {c.salonActions}</h4>
          <LocalizedList items={policy.salonActions} lang={lang} />
        </div>
        <div>
          <h4><Heart size={19} weight="duotone" /> {c.clientCare}</h4>
          <LocalizedList items={policy.clientCare} lang={lang} />
        </div>
      </section>

      <div className="policy-detail__cta">
        <div>
          <span><ShieldCheck size={20} weight="duotone" /> {policy.code}</span>
          <p>{policy.notify[lang]}</p>
        </div>
        <button type="button" onClick={onClaim}>{c.startClaim} <ArrowRight size={18} weight="bold" /></button>
      </div>
    </article>
  )
}
