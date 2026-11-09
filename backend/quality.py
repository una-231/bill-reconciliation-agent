from collections import Counter
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[1] / 'skills/bill-data-quality/SKILL.md').read_text(encoding='utf-8')


def inspect_records(records):
    missing = Counter()
    issues = []
    for r in records:
        for key in ['time', 'account', 'merchant', 'direction']:
            if not r.get(key):
                missing[key] += 1
                issues.append(dict(tx_id=r['id'], field=key, reason=f'缺少 {key}'))
    dates = [r['time'] for r in records if r.get('time')]
    return dict(rows=len(records), missing=dict(missing), issues=issues,
        date_range=[min(dates), max(dates)] if dates else [],
        outgoing_cents=sum(r['amount'] for r in records if r['direction'] == '支出'),
        incoming_cents=sum(r['amount'] for r in records if r['direction'] == '收入'),
        skill='bill-data-quality/1.0.0',
        note='原始收支合计包含尚未核对的转账与退款，不等于消费净支出')
