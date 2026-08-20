import {
  ArrowsClockwise,
  Bandaids,
  Barcode,
  Drop,
  FunnelSimple,
  HairDryer,
  Package,
  Palette,
  Scales,
  Scissors,
  Sparkle,
  Waves,
  X,
} from '@phosphor-icons/react'

export const policyIcons = {
  breakage: Scissors,
  'colour-change': Drop,
  'shade-variance': Palette,
  texture: Waves,
  shedding: Sparkle,
  'split-ends': HairDryer,
  'dry-tangle': ArrowsClockwise,
  'oily-feel': Drop,
  adhesive: Bandaids,
  weight: Scales,
  'glue-evenness': Barcode,
  packaging: Package,
}

export default function PolicyFinder({
  lang,
  c,
  search,
  setSearch,
  product,
  setProduct,
  category,
  setCategory,
  products,
  categories,
  filtered,
  selectedId,
  onSelect,
  onReset,
}) {
  const hasFilters = Boolean(search || product !== 'all' || category !== 'all')

  return (
    <div className="policy-finder">
      <div className="finder-controls">
        <div className="search-field">
          <label htmlFor="policy-search">{c.searchLabel}</label>
          <div>
            <Sparkle size={19} weight="duotone" aria-hidden="true" />
            <input
              id="policy-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={c.searchPlaceholder}
            />
            {search && (
              <button type="button" onClick={() => setSearch('')} aria-label={c.clearSearch}>
                <X size={16} weight="bold" />
              </button>
            )}
          </div>
        </div>
        <div className="filter-field">
          <label htmlFor="product-filter">{c.products}</label>
          <div>
            <FunnelSimple size={17} aria-hidden="true" />
            <select id="product-filter" value={product} onChange={(event) => setProduct(event.target.value)}>
              <option value="all">{c.allProducts}</option>
              {products.map((item) => <option key={item.id} value={item.id}>{item.label[lang]}</option>)}
            </select>
          </div>
        </div>
      </div>

      <div className="category-row" aria-label={c.concerns}>
        <span>{c.concerns}</span>
        <button
          className={category === 'all' ? 'is-active' : ''}
          type="button"
          onClick={() => setCategory('all')}
          aria-pressed={category === 'all'}
        >
          {c.allConcerns}
        </button>
        {categories.map((item) => (
          <button
            className={category === item.id ? 'is-active' : ''}
            key={item.id}
            type="button"
            onClick={() => setCategory(item.id)}
            aria-pressed={category === item.id}
          >
            {item.label[lang]}
          </button>
        ))}
      </div>

      <div className="results-heading">
        <strong>{c.resultCount(filtered.length)}</strong>
        {hasFilters && <button type="button" onClick={onReset}>{c.clearFilters}</button>}
      </div>

      {filtered.length > 0 ? (
        <div className="policy-results">
          {filtered.map((policy) => {
            const Icon = policyIcons[policy.id] || Sparkle
            const selected = policy.id === selectedId
            return (
              <button
                className={`policy-result ${selected ? 'is-selected' : ''}`}
                type="button"
                key={policy.id}
                onClick={() => onSelect(policy.id)}
                aria-pressed={selected}
              >
                <span className="policy-result__icon"><Icon size={21} weight="duotone" /></span>
                <span className="policy-result__copy">
                  <small>{policy.code}</small>
                  <strong>{policy.title[lang]}</strong>
                  <em>{policy.short[lang]}</em>
                </span>
                <span className="policy-result__window">{policy.window[lang]}</span>
              </button>
            )
          })}
        </div>
      ) : (
        <div className="empty-state">
          <FunnelSimple size={30} weight="duotone" />
          <p>{c.noResults}</p>
          <button type="button" onClick={onReset}>{c.clearFilters}</button>
        </div>
      )}
    </div>
  )
}
