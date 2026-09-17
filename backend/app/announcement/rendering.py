"""Lossless text/image sequence, using small UTF-8 chunks for DingTalk."""
import re
from urllib.parse import quote

from app.core.config import get_settings


def escape(text):
    return re.sub(r'([\\`*_{}\[\]<>#!|])', r'\\\1', str(text))


def text_parts(text, limit=2400):
    """Keep every character, including long paragraphs and Chinese text."""
    parts, buf, size = [], [], 0
    for char in text:
        width = len(char.encode('utf-8'))
        if size + width > limit:
            parts.append({'kind': 'text', 'text': ''.join(buf)})
            buf, size = [], 0
        buf.append(char)
        size += width
    if buf:
        parts.append({'kind': 'text', 'text': ''.join(buf)})
    return parts


def render_parts(content):
    parts, pending = [], []

    def flush():
        if pending:
            parts.extend(text_parts(''.join(pending).strip('\n')))
            pending.clear()

    def walk(node):
        kind, attrs = node.get('type'), node.get('attrs', {})
        if kind == 'knowledgeImage':
            flush()
            parts.append({'kind': 'image', 'asset_id': attrs['assetId'], 'alt': attrs.get('alt', '')})
            if attrs.get('caption'):
                pending.append(escape(attrs['caption']) + '\n')
            return
        if kind == 'text':
            pending.append(escape(node['text']))
            for mark in node.get('marks', []):
                if mark['type'] == 'link':
                    pending.append(' (' + mark['attrs']['href'] + ')')
            return
        if kind in {'hardBreak', 'horizontalRule'}:
            pending.append('\n')
        if kind == 'table':
            pending.append('\n【表格：逐行排列，单元格以 ｜ 分隔】\n')
        if kind in {'listItem', 'taskItem'}:
            pending.append(('☑ ' if attrs.get('checked') else '☐ ') if kind == 'taskItem' else '• ')
        for child in node.get('content', []):
            walk(child)
        if kind in {'tableCell', 'tableHeader'}:
            pending.append(' ｜ ')
        if kind in {'paragraph', 'heading', 'listItem', 'taskItem', 'tableRow', 'blockquote', 'codeBlock'}:
            pending.append('\n')

    walk(content)
    flush()
    return parts


def link(document_id):
    base = get_settings().ANNOUNCEMENT_PUBLIC_BASE_URL.rstrip('/')
    return f'{base}/announcements/{quote(str(document_id))}'


def publication_parts(publication, revision, meta):
    title = f'【{"公告更新" if publication.kind == "update" else "通知公告"}】{revision.title}'
    info = f'{escape(title)}\n类别：{escape(meta.category_name)}\n'
    if meta.effective_at:
        info += f'生效：{meta.effective_at:%Y-%m-%d %H:%M}\n'
    if meta.expires_at:
        info += f'截止：{meta.expires_at:%Y-%m-%d %H:%M}\n'
    if meta.change_note:
        info += f'更新说明：{escape(meta.change_note)}\n'
    parts = text_parts(info) + render_parts(revision.content_json)
    parts.append({'kind': 'text', 'text': f'[查看原公告]({link(publication.document_id)})'})
    return [{'title': title[:100], **part} for part in parts]
