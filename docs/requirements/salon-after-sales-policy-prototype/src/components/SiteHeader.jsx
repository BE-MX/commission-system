import { Globe, List, X } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'

export default function SiteHeader({ lang, setLang, c, onClaim }) {
  const [open, setOpen] = useState(false)
  const menuButton = useRef(null)
  const nav = useRef(null)

  const go = () => setOpen(false)

  useEffect(() => {
    if (!open) return undefined
    const handlePointer = (event) => {
      if (!nav.current?.contains(event.target) && !menuButton.current?.contains(event.target)) setOpen(false)
    }
    const handleKey = (event) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      menuButton.current?.focus()
    }
    document.addEventListener('pointerdown', handlePointer)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('pointerdown', handlePointer)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  return (
    <header className="site-header">
      <div className="site-header__inner">
        <a className="brand" href="#top" aria-label={c.homeLabel} onClick={go}>
          <span className="brand__mark" aria-hidden="true">LS</span>
          <span className="brand__name">
            <strong>LeShine</strong>
            <small>{c.brandQualifier}</small>
          </span>
        </a>

        <button
          ref={menuButton}
          className="mobile-menu-button"
          type="button"
          aria-label={open ? c.menuClose : c.menuOpen}
          aria-expanded={open}
          aria-controls="primary-navigation"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <X size={20} /> : <List size={22} />}
        </button>

        <nav ref={nav} id="primary-navigation" className={`site-nav ${open ? 'is-open' : ''}`} aria-label={c.navLibrary}>
          <a href="#library" onClick={go}>{c.navLibrary}</a>
          <a href="#standards" onClick={go}>{c.navCare}</a>
          <a href="#process" onClick={go}>{c.navProcess}</a>
          <button
            className="language-switch"
            type="button"
            onClick={() => {
              setLang(lang === 'en' ? 'zh' : 'en')
              go()
            }}
          >
            <Globe size={17} weight="bold" />
            {lang === 'en' ? '中文' : 'EN'}
          </button>
          <button className="header-claim" type="button" onClick={() => { onClaim(); go() }}>
            {c.contact}
          </button>
        </nav>
      </div>
    </header>
  )
}
