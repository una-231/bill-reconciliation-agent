"""截图字段草稿与本地原图管理。"""
import hashlib
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from . import storage as db
from .intake import cents
from .schema import NoteEntry, Transaction


def image_attachment(content, filename):
    digest = hashlib.sha256(content).hexdigest()
    token = digest + Path(filename).suffix.lower()
    folder = db.data_dir() / 'uploads'
    folder.mkdir(exist_ok=True)
    (folder / token).write_bytes(content)
    return dict(token=token, file=filename, sha256=digest)


def make_drafts(rows, errors, attachment, platform, account, extracted='', reference_date=None):
    drafts = []
    for row in rows:
        fields = dict(id=row['id'], date=row['time'][:10], time=row['time'][11:16],
            merchant=row['merchant'], amount_yuan=f'{row["amount"] / 100:.2f}',
            direction=row['direction'], kind=row['kind'], platform=platform,
            account=account, description=row.get('description', ''))
        drafts.append(dict(id=row['id'], file=attachment['file'], image_token=attachment['token'],
            row=row['sources'][0].get('row'), fields=fields, original_fields=dict(fields),
            raw=row.get('raw', {}), sources=row['sources'], status='pending', reviewed=False, error=''))
    for error in errors:
        raw = error.get('raw', {})
        text = raw.get('ocr_block', raw.get('text', ''))
        number = error.get('row', 0)
        identity = hashlib.sha256(f'{attachment["sha256"]}:unparsed:{number}'.encode()).hexdigest()[:24]
        first = text.splitlines()[0] if text else ''
        amount = re.search(r'([+\-−－–])\s*(\d+\.\d{2})\s*$', first)
        # 只预填明确识别的字段，不修复错位小数点或补猜截断日期。
        merchant = first[:amount.start()].strip() if amount else re.sub(r'\s+[\d.]+[-+]\s*$', '', first).strip()
        clock = re.search(r'(?<!\d)(\d{1,2}:\d{2})(?!\d)', '\n'.join(text.splitlines()[1:]))
        direction = ('收入' if amount[1] == '+' else '支出') if amount else None
        context = date.fromisoformat(str(reference_date)) if reference_date else None
        year = re.search(r'(20\d{2})年', extracted)
        month_day = re.search(r'(\d{1,2})(?:月|-)(\d{1,2})(?:日|(?=\s|\d{1,2}:))', '\n'.join(text.splitlines()[1:]))
        relative = re.search(r'(今天|昨天|前天)', '\n'.join(text.splitlines()[1:]))
        day = None
        try:
            if relative and context: day = (context - timedelta(days={'今天': 0, '昨天': 1, '前天': 2}[relative[1]])).isoformat()
            elif month_day and (year or context): day = date(int(year[1]) if year else context.year, int(month_day[1]), int(month_day[2])).isoformat()
        except ValueError:
            pass
        kind = '退款' if direction == '收入' and '退款' in merchant else (
            '转账' if '转账' in merchant else ('收入' if direction == '收入' else '消费'))
        fields = dict(id=identity, date=day, time=clock[1].zfill(5) if clock else None,
            merchant=merchant, amount_yuan=amount[2] if amount else None, direction=direction,
            kind=kind, platform=platform, account=account, description=merchant)
        drafts.append(dict(id=identity, file=attachment['file'], image_token=attachment['token'],
            row=number, fields=fields, original_fields=dict(fields), raw=raw,
            sources=[dict(file=attachment['file'], row=number, sha256=attachment['sha256'], ocr=True)],
            status='pending', reviewed=False, error=error['error']))
    return sorted(drafts, key=lambda d: d['row'] or 0)


def checked_transaction(draft):
    item = NoteEntry.model_validate(draft['fields'])
    if not all([item.date, item.time, item.merchant.strip(), item.account.strip(), item.platform, item.direction]) or item.amount_yuan is None:
        raise ValueError('请补全日期、时间、商户、金额、收支方向和账户后再确认')
    if (item.kind == '退款' and item.direction != '收入') or (item.kind == '消费' and item.direction != '支出') or (item.kind == '收入' and item.direction != '收入'):
        raise ValueError('交易类型与收支方向不一致')
    timestamp = datetime.fromisoformat(f'{item.date.isoformat()}T{item.time}:00')
    row = Transaction(id=draft['id'], platform=item.platform, account=item.account.strip(),
        time=timestamp.isoformat(), amount=cents(item.amount_yuan), merchant=item.merchant.strip(),
        direction=item.direction, kind=item.kind, description=item.description or item.merchant.strip(),
        sources=draft['sources'], raw=dict(**draft['raw'], screenshot_confirmation=dict(
            original_fields=draft['original_fields'], confirmed_fields=item.model_dump(mode='json'),
            confirmed_at=db.now()))).model_dump()
    row.update(ocr_review_required=True, ocr_fields_confirmed=True)
    return row
