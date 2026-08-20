"""Pure policy functions for the claude-mem to Mem0 boundary."""

import os
import re


ALLOWED_TYPES = frozenset(("decision", "bugfix", "discovery"))

TENTATIVE_RE = re.compile(
    r"(?:\b(?:todo|wip|tentative|unconfirmed|unverified|maybe|proposal|draft|"
    r"plan(?:ned)?|next steps?|work in progress)\b|"
    r"临时进度|未确认|未验证|待验证|暂定|草案|原始日志|下一步|计划中)",
    re.IGNORECASE,
)
SENSITIVE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:m0|sk|xox[baprs])-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
    re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+", re.IGNORECASE),
    re.compile(r"https://(?:oapi\.)?dingtalk\.com/robot/send\?access_token=[^\s]+", re.IGNORECASE),
    re.compile(r"https://discord(?:app)?\.com/api/webhooks/[^\s]+", re.IGNORECASE),
    re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s]+", re.IGNORECASE),
    re.compile(r"https?://[^\s/:]+:[^\s/@]+@[^\s]+", re.IGNORECASE),
    re.compile(
        r"\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|"
        r"secret|authorization)\b\s*[:=]\s*['\"]?[^\s,'\"]{8,}",
        re.IGNORECASE,
    ),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+\-/]+=*", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
)
RAW_LOG_PATTERNS = (
    re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE),
    re.compile(r"(?:^|\n)\s*at\s+\S+\s+\([^\n)]+:\d+:\d+\)", re.MULTILINE),
    re.compile(
        r"(?:^|\n)\d{4}-\d{2}-\d{2}[T ][0-9:.+-Z]+[^\n]*(?:ERROR|FATAL|WARN)",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(r"(?:^|\n)(?:ERROR|FATAL|DEBUG)\s+(?:stack|trace|exception)\b", re.IGNORECASE),
)
DECISION_QUALITY_RE = re.compile(
    r"(?:architecture|architectural|design decision|schema|contract|protocol|"
    r"policy|convention|invariant|stable preference|\bprefer(?:ence|red)?\b|"
    r"架构|选型|协议|契约|规范|约定|不变量|稳定偏好|长期偏好|安全边界)",
    re.IGNORECASE,
)
BUGFIX_QUALITY_RE = re.compile(
    r"(?:verified|validated|regression|test(?:ed|s)? pass|root cause|fixed|"
    r"reproduced|已验证|验证通过|测试通过|回归通过|根因|已修复|复现)",
    re.IGNORECASE,
)
DISCOVERY_QUALITY_RE = re.compile(
    r"(?:important|critical|confirmed|verified|root cause|invariant|constraint|"
    r"gotcha|risk|compatib|discovery|finding|关键|重要|已确认|已验证|根因|不变量|约束|限制|"
    r"风险|兼容|发现)",
    re.IGNORECASE,
)


def normalize_project(raw_project, aliases):
    project = (raw_project or "unknown").strip()
    if project in aliases:
        return str(aliases[project])
    real_project = os.path.realpath(os.path.expanduser(project))
    if real_project in aliases:
        return str(aliases[real_project])
    base = os.path.basename(project.rstrip(os.sep))
    if base in aliases:
        return str(aliases[base])
    for candidate, stable_name in aliases.items():
        if candidate.endswith("*") and base.startswith(candidate[:-1]):
            return str(stable_name)
    return re.sub(r"[^A-Za-z0-9._-]+", "-", base or "unknown").strip("-").lower() or "unknown"


def combined_content(row):
    parts = []
    for key in ("title", "narrative", "text", "facts"):
        value = row[key]
        if value and str(value).strip() and str(value).strip() not in parts:
            parts.append(str(value).strip())
    return "\n\n".join(parts)


def classify(row):
    obs_type = str(row["type"] or "").lower().strip()
    if obs_type not in ALLOWED_TYPES:
        return False, "type_not_allowed"
    content = combined_content(row)
    if not content:
        return False, "empty_content"
    if any(pattern.search(content) for pattern in SENSITIVE_PATTERNS):
        return False, "sensitive_content"
    if any(pattern.search(content) for pattern in RAW_LOG_PATTERNS):
        return False, "raw_log_content"
    if TENTATIVE_RE.search(content):
        return False, "tentative_or_temporary"
    if obs_type == "decision" and not DECISION_QUALITY_RE.search(content):
        return False, "decision_not_architectural_or_stable"
    if obs_type == "bugfix" and not BUGFIX_QUALITY_RE.search(content):
        return False, "bugfix_not_verified"
    if obs_type == "discovery" and not DISCOVERY_QUALITY_RE.search(content):
        return False, "discovery_not_important_or_confirmed"
    return True, "eligible"


def memory_text(row):
    title = str(row["title"] or "").strip()
    body = str(row["narrative"] or row["text"] or row["facts"] or "").strip()
    if title and body and title != body:
        value = "%s\n\n%s" % (title, body)
    else:
        value = title or body
    return value[:8000]


def source_key(config, obs_id):
    return "claude-mem:%s:%s" % (config["source_device"], obs_id)
