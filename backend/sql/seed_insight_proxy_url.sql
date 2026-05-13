-- 方舟洞见 - 信源代理地址初始化
-- 为需要访问 Google / Pinterest 的信源配置代理

UPDATE ark_insight_sources
SET proxy_url = 'http://127.0.0.1:1080'
WHERE source_type IN ('google_alerts_rss', 'google_trends_rss', 'pinterest_scrape');

-- 其余信源（Amazon / 竞品 RSS / 竞品 HTML / AIHot）不需要代理，维持 NULL
