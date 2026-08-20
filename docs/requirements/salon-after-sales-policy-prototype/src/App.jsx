import {
  ArrowDown,
  ArrowRight,
  CheckCircle,
  ClockCountdown,
  Files,
  ShieldCheck,
  Sparkle,
} from '@phosphor-icons/react'
import { useEffect, useMemo, useState } from 'react'
import ClaimDrawer from './components/ClaimDrawer'
import PolicyDetail from './components/PolicyDetail'
import PolicyFinder from './components/PolicyFinder'
import SiteHeader from './components/SiteHeader'
import { categories, copy, policies, products } from './data'

const initialLanguage = () => {
  const saved = window.localStorage.getItem('leshine-policy-language')
  return saved === 'zh' ? 'zh' : 'en'
}

const initialPolicy = () => {
  const hash = window.location.hash.replace('#policy-', '')
  return policies.some((policy) => policy.id === hash) ? hash : 'adhesive'
}

export default function App() {
  const [lang, setLang] = useState(initialLanguage)
  const [search, setSearch] = useState('')
  const [product, setProduct] = useState('all')
  const [category, setCategory] = useState('all')
  const [selectedId, setSelectedId] = useState(initialPolicy)
  const [claimOpen, setClaimOpen] = useState(false)
  const c = copy[lang]

  useEffect(() => {
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'
    window.localStorage.setItem('leshine-policy-language', lang)
    document.title = lang === 'zh' ? '莱莎专业售后保障查询' : 'LeShine Professional Assurance'
    const description = document.querySelector('meta[name="description"]')
    description?.setAttribute(
      'content',
      lang === 'zh'
        ? '面向莱莎沙龙合作伙伴的精细化接发产品售后保障查询。'
        : 'Issue-specific hair-extension assurance for LeShine salon partners.',
    )
  }, [lang])

  useEffect(() => {
    const syncPolicyHash = () => {
      const hashId = window.location.hash.replace('#policy-', '')
      if (!window.location.hash.startsWith('#policy-') || !policies.some(({ id }) => id === hashId)) return
      setSearch('')
      setProduct('all')
      setCategory('all')
      setSelectedId(hashId)
      window.setTimeout(() => {
        document.getElementById('library')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 0)
    }
    window.addEventListener('hashchange', syncPolicyHash)
    if (window.location.hash.startsWith('#policy-')) syncPolicyHash()
    return () => window.removeEventListener('hashchange', syncPolicyHash)
  }, [])

  const filtered = useMemo(() => {
    const term = search.trim().toLocaleLowerCase()
    return policies.filter((policy) => {
      const productMatch = product === 'all' || policy.products.includes(product)
      const categoryMatch = category === 'all' || policy.category === category
      const productTerms = products
        .filter((item) => policy.products.includes(item.id))
        .flatMap((item) => [item.label.en, item.label.zh])
      const localized = (items) => items.flatMap((item) => [item.en, item.zh])
      const haystack = [
        policy.code,
        policy.title.en,
        policy.title.zh,
        policy.short.en,
        policy.short.zh,
        ...productTerms,
        ...policy.causes.flatMap((cause) => [cause.text.en, cause.text.zh]),
        ...localized(policy.tests),
        ...localized(policy.coverage.included),
        ...localized(policy.coverage.conditional),
        ...localized(policy.coverage.excluded),
        ...localized(policy.outcomes),
        ...localized(policy.salonActions),
        ...localized(policy.clientCare),
      ].join(' ').toLocaleLowerCase()
      return productMatch && categoryMatch && (!term || haystack.includes(term))
    })
  }, [search, product, category])

  const selectedPolicy = policies.find((policy) => policy.id === selectedId) || policies[0]

  useEffect(() => {
    if (filtered.length === 0 || filtered.some((policy) => policy.id === selectedId)) return
    const nextId = filtered[0].id
    setSelectedId(nextId)
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#policy-${nextId}`)
  }, [filtered, selectedId])

  const selectPolicy = (id) => {
    setSelectedId(id)
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#policy-${id}`)
  }

  const resetFilters = () => {
    setSearch('')
    setProduct('all')
    setCategory('all')
  }

  const scrollToLibrary = () => {
    document.getElementById('library')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div id="top" className="app-shell">
      <SiteHeader lang={lang} setLang={setLang} c={c} onClaim={() => setClaimOpen(true)} />

      <div className="draft-notice" role="note">
        <strong>{c.draftLabel}</strong>
        <span>{c.draftNotice}</span>
      </div>

      <main>
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero__ambient" aria-hidden="true">
            <span className="hero__strand hero__strand--one" />
            <span className="hero__strand hero__strand--two" />
            <span className="hero__strand hero__strand--three" />
          </div>
          <div className="hero__content">
            <div className="hero__eyebrow"><Sparkle size={15} weight="fill" /> {c.heroEyebrow}</div>
            <h1 id="hero-title">
              <span>{c.heroTitleA}</span>
              <em>{c.heroTitleB}</em>
            </h1>
            <p>{c.heroBody}</p>
            <div className="hero__actions">
              <button className="primary-action" type="button" onClick={scrollToLibrary}>
                {c.explore} <ArrowDown size={18} weight="bold" />
              </button>
              <span className="policy-version"><ShieldCheck size={18} weight="duotone" /> {c.version}</span>
            </div>
          </div>
          <div className="hero__proof" aria-label={c.serviceCommitments}>
            <div><ClockCountdown size={22} weight="duotone" /><span>{c.response}</span></div>
            <div><Files size={22} weight="duotone" /><span>{c.assessment}</span></div>
            <div><CheckCircle size={22} weight="duotone" /><span>{c.decision}</span></div>
          </div>
        </section>

        <section id="library" className="library-section" aria-labelledby="library-title">
          <div className="section-heading">
            <div>
              <span>{c.navLibrary}</span>
              <h2 id="library-title">{c.searchLabel}</h2>
            </div>
            <p>{c.finePrint}</p>
          </div>

          <PolicyFinder
            lang={lang}
            c={c}
            search={search}
            setSearch={setSearch}
            product={product}
            setProduct={setProduct}
            category={category}
            setCategory={setCategory}
            products={products}
            categories={categories}
            filtered={filtered}
            selectedId={selectedId}
            onSelect={selectPolicy}
            onReset={resetFilters}
          />

          {filtered.length > 0 ? (
            <PolicyDetail
              lang={lang}
              c={c}
              policy={selectedPolicy}
              products={products}
              onClaim={() => setClaimOpen(true)}
            />
          ) : (
            <div className="policy-detail-empty">
              <Files size={34} weight="duotone" />
              <h3>{c.noResults}</h3>
              <button type="button" onClick={resetFilters}>{c.clearFilters}</button>
            </div>
          )}
        </section>

        <section id="standards" className="standards-section" aria-labelledby="standards-title">
          <div className="standards-heading">
            <span>{c.salonStandard}</span>
            <h2 id="standards-title">{c.salonIntro}</h2>
          </div>
          <div className="standards-grid">
            <article className="standard-card">
              <span className="standard-card__number">01</span>
              <h3>{c.preOrder}</h3>
              <p>{c.preOrderText}</p>
            </article>
            <article className="standard-card">
              <span className="standard-card__number">02</span>
              <h3>{c.maintenance}</h3>
              <p>{c.maintenanceText}</p>
            </article>
            <article className="standard-card standard-card--urgent">
              <span className="standard-card__number">!</span>
              <h3>{c.urgent}</h3>
              <p>{c.urgentText}</p>
            </article>
          </div>
        </section>

        <section id="process" className="process-section" aria-labelledby="process-title">
          <div className="process-copy">
            <span>{c.processEyebrow}</span>
            <h2 id="process-title">{c.processTitle}</h2>
            <p>{c.processBody}</p>
            <button type="button" onClick={() => setClaimOpen(true)}>
              {c.startClaim} <ArrowRight size={18} weight="bold" />
            </button>
          </div>
          <ol className="process-steps">
            {[
              [c.step1, c.step1Body],
              [c.step2, c.step2Body],
              [c.step3, c.step3Body],
              [c.step4, c.step4Body],
            ].map(([title, body], index) => (
              <li key={title}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <div><h3>{title}</h3><p>{body}</p></div>
              </li>
            ))}
          </ol>
        </section>
      </main>

      <footer>
        <a className="brand brand--footer" href="#top" aria-label={c.backToTop}>
          <span className="brand__mark" aria-hidden="true">LS</span>
          <span className="brand__name"><strong>LeShine</strong><small>{c.brandQualifier}</small></span>
        </a>
        <p>{c.version} · {c.finePrint}<br />{c.legalRights}</p>
      </footer>

      <ClaimDrawer
        open={claimOpen}
        onClose={() => setClaimOpen(false)}
        policy={selectedPolicy}
        lang={lang}
        c={c}
      />
    </div>
  )
}
