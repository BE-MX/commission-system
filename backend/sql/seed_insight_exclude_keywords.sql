-- 方舟洞见 - 信源排除关键词初始化 (8 条 Google Alerts RSS)
-- 执行前确认 ark_insight_sources 表中已有对应记录
-- 运行方式: 在 MySQL 客户端执行 SOURCE backend/sql/seed_insight_exclude_keywords.sql;

UPDATE ark_insight_sources
SET keywords = '["professional","salon","brand","market","launch","trend"]',
    exclude_keywords = '["halloween","costume","diy","aliexpress","shein","kids"]'
WHERE name LIKE '%hair extensions%' AND source_type = 'google_alerts_rss';

UPDATE ark_insight_sources
SET keywords = '["hair","extensions"]',
    exclude_keywords = '["fabric","textile","weaving","loom","cotton","linen"]'
WHERE name LIKE '%weft%' AND name NOT LIKE '%genius%' AND source_type = 'google_alerts_rss';

UPDATE ark_insight_sources
SET keywords = '[]',
    exclude_keywords = '["wish","dropship","cheap"]'
WHERE name LIKE '%genius weft%' AND source_type = 'google_alerts_rss';

UPDATE ark_insight_sources
SET keywords = '["hair","extensions","salon"]',
    exclude_keywords = '["duct","packaging","shipping","diy home"]'
WHERE name LIKE '%tape in%' AND source_type = 'google_alerts_rss';

UPDATE ark_insight_sources
SET keywords = '[]',
    exclude_keywords = '[]'
WHERE name LIKE '%BELLAMI Hair%' AND source_type = 'google_alerts_rss';

UPDATE ark_insight_sources
SET keywords = '[]',
    exclude_keywords = '["movie","film","book","novel"]'
WHERE name LIKE '%Great Lengths%' AND source_type = 'google_alerts_rss';

UPDATE ark_insight_sources
SET keywords = '[]',
    exclude_keywords = '[]'
WHERE name LIKE '%Hairlaya%' AND source_type = 'google_alerts_rss';

UPDATE ark_insight_sources
SET keywords = '["report","growth","forecast","billion","CAGR","trend","size"]',
    exclude_keywords = '["seo","blog","guest post","sponsored"]'
WHERE name LIKE '%hair extension market%' AND source_type = 'google_alerts_rss';
