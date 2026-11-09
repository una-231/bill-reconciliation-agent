import csv
import hashlib
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from .schema import Transaction

ALIASES = {
    'time': ['交易时间', '交易创建时间', '付款时间', '时间', 'time'],
    'direction': ['收/支', '收支', '收支方向', 'direction'],
    'amount': ['金额(元)', '金额（元）', '金额', 'amount'],
    'merchant': ['交易对方', '商户', '商户名称', 'merchant'],
    'description': ['商品', '商品说明', '商品名称', '交易说明', '备注', 'description'],
    'order_id': ['交易单号', '交易号', '订单号', 'order_id'],
    'reference': ['原订单号', '关联订单号', 'reference'],
    'status': ['当前状态', '交易状态', '状态', 'status'],
    'kind': ['交易类型', '类型', 'kind'],
    'account': ['账户', 'account'],
}


class MappingRequired(ValueError):
    def __init__(self, columns, preview):
        self.columns, self.preview = columns, preview
        super().__init__('无法识别时间、金额或收支列，请指定字段映射')


def cents(value):
    s = re.sub(r'[¥￥元,\s]', '', str(value))
    try:
        v = Decimal(s)
        if not v.is_finite() or v < 0 or v * 100 != (v * 100).to_integral_value():
            raise ValueError('金额须为非负数，最多两位小数')
        return int(v * 100)
    except InvalidOperation as e:
        raise ValueError('金额无法识别') from e


def read_frame(content, suffix):
    if suffix == '.xlsx':
        frame = pd.read_excel(io.BytesIO(content), header=None, dtype=str).fillna('')
        for i, row in frame.iterrows():
            if any(str(v).strip() in ALIASES['time'] for v in row):
                frame.columns = [str(v).strip() for v in row]
                return frame.iloc[i + 1:].reset_index(drop=True), int(i) + 2
        return pd.read_excel(io.BytesIO(content), dtype=str).fillna(''), 2
    text = None
    for enc in ['utf-8-sig', 'gb18030']:
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    if text is None:
        raise ValueError('文件编码不支持，请另存为 UTF-8 CSV')
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if any(k in line for k in ALIASES['time']) and any(k in line for k in ALIASES['amount']):
            start = i
            break
    sample = '\n'.join(lines[start:])
    try:
        sep = csv.Sniffer().sniff(sample[:4000], delimiters=',\t;').delimiter
    except csv.Error:
        sep = ','
    return pd.read_csv(io.StringIO(sample), dtype=str, sep=sep, keep_default_na=False), start + 2


def parse_table(content, filename, platform, account, mapping=None):
    df, first_row = read_frame(content, Path(filename).suffix.lower())
    df.columns = [str(c).strip() for c in df.columns]
    mapping = mapping or {field: next((a for a in aliases if a in df.columns), '') for field, aliases in ALIASES.items()}
    if any(not mapping.get(k) or mapping[k] not in df.columns for k in ['time', 'amount', 'direction']):
        raise MappingRequired(list(df.columns), df.head(4).to_dict('records'))
    rows, errors = [], []
    digest = hashlib.sha256(content).hexdigest()
    for i, row in df.iterrows():
        raw = {str(k): str(v) for k, v in row.to_dict().items()}
        if not any(v.strip() for v in raw.values()) or str(row.get(mapping['time'], '')).startswith('---'):
            continue
        try:
            fields = {k: str(row.get(v, '')).strip().strip('`') for k, v in mapping.items()}
            time = pd.to_datetime(fields['time'], errors='raise')
            if pd.isna(time):
                raise ValueError('日期为空')
            direction = fields['direction']
            if direction in ['不计收支', '/', '不计入收支', '其他']:
                direction = '不计收支'
            if direction not in ['收入', '支出', '不计收支']:
                raise ValueError('收支方向无法识别')
            kind = fields.get('kind', '')
            if '退款' in kind or ('退款' in fields.get('description', '') and direction == '收入'):
                kind = '退款'
            elif any(w in kind for w in ['转账', '提现', '充值']):
                kind = '转账'
            else:
                kind = '收入' if direction == '收入' else '消费'
            tx = Transaction(id=hashlib.sha256(f'{digest}:{i}'.encode()).hexdigest()[:24], platform=platform,
                account=fields.get('account') or account, time=time.isoformat(), direction=direction,
                amount=cents(fields['amount']), merchant=fields.get('merchant', ''),
                description=fields.get('description', ''), order_id=fields.get('order_id', ''),
                reference=fields.get('reference', ''), status=fields.get('status') or '成功', kind=kind,
                sources=[dict(file=Path(filename).name, row=int(i) + first_row, sha256=digest)], raw=raw)
            rows.append(tx.model_dump())
        except Exception as e:
            errors.append(dict(row=int(i) + first_row, error=str(e), raw=raw))
    return rows, errors


def parse_text(text, platform, account):
    if any(s in text for s in [',', '\t']) and any(s in text for s in ['金额', 'amount']):
        return parse_table(text.encode('utf-8'), '粘贴文字.csv', platform, account)
    records, errors = [], []
    for i, line in enumerate(text.splitlines()):
        if not line.strip() or '构造账单' in line:
            continue
        date = re.search(r'(20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}日?)(?:\s*(\d{1,2}:\d{2}(?::\d{2})?))?', line)
        amount = re.search(r'(?:[¥￥]\s*(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s*元)', line)
        if not date or not amount:
            errors.append(dict(row=i + 1, error='请补充完整日期、金额（带元或¥）、商户和收支方向', raw={'text':line}))
            continue
        if not any(w in line for w in ['支出', '收入', '退款']):
            errors.append(dict(row=i + 1, error='缺少明确收支方向', raw={'text':line}))
            continue
        date_text = date.group(1).replace('年', '-').replace('月', '-').replace('日', '').replace('/', '-')
        timestamp = datetime.fromisoformat(date_text + 'T' + (date.group(2) or '00:00:00'))
        merchant = re.sub(r'^[\s,，|：:]+|[\s,，|：:]+$', '', line[date.end():amount.start()])
        merchant = re.sub(r'支出|收入|退款|消费|付款', '', merchant).strip(' ,，|：:')
        if not merchant:
            errors.append(dict(row=i + 1, error='缺少商户，请补充后重试', raw={'text':line}))
            continue
        direction = '收入' if '收入' in line or '退款' in line else '支出'
        kind = '退款' if '退款' in line else ('转账' if '转账' in line else ('消费' if direction == '支出' else '收入'))
        tx = Transaction(id=hashlib.sha256(f'{platform}|{account}|{line}|{i}'.encode()).hexdigest()[:24],
            platform=platform, account=account, time=timestamp.isoformat(), direction=direction,
            amount=cents(amount.group(1) or amount.group(2)), merchant=merchant, description=line,
            kind=kind, sources=[dict(file='文字输入', row=i+1)], raw={'text':line})
        records.append(tx.model_dump())
    return records, errors


_ocr = None


def parse_image(content, filename, platform, account):
    global _ocr
    from PIL import Image
    import numpy as np
    from rapidocr import RapidOCR
    im = Image.open(io.BytesIO(content)).convert('RGB')
    if im.width * im.height > 20_000_000:
        raise ValueError('图片过大，请裁剪后上传')
    if _ocr is None:
        _ocr = RapidOCR()
    result = _ocr(np.asarray(im))
    texts = list(result.txts) if result.txts is not None else []
    scores = list(result.scores) if result.scores is not None else []
    # 同一水平行按坐标合并，避免OCR将时间、商户、金额拆成独立文本块。
    lines=[]
    if result.boxes is not None:
        entries=[]
        for box,txt in zip(result.boxes,texts):
            box=np.asarray(box)
            entries.append((float(box[:,1].mean()),float(box[:,0].min()),float(box[:,1].max()-box[:,1].min()),txt))
        for y,x,h,txt in sorted(entries):
            if lines and abs(lines[-1]['y']-y)<=max(h,lines[-1]['h'])*.65:
                lines[-1]['parts'].append((x,txt))
            else:lines.append(dict(y=y,h=h,parts=[(x,txt)]))
        extracted='\n'.join(' '.join(t for _,t in sorted(line['parts'])) for line in lines)
    else:extracted='\n'.join(texts)
    rows, errors = parse_text(extracted, platform, account)
    if not rows:
        # 详情页仅在唯一日期、唯一金额和明确交易对方均存在时拼接。
        date=re.findall(r'20\d{2}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?',extracted)
        amount=re.findall(r'[¥￥]\s*\d+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?\s*元',extracted)
        merchant=re.search(r'(?:收款方|交易对方|商户名称)\s*[:：]?\s*([^\n]+)',extracted)
        direction='支出' if any(w in extracted for w in ['支出','付款成功','支付成功']) else ('收入' if '收入' in extracted else '')
        if len(date)==len(amount)==1 and merchant and direction:
            rows,errors=parse_text(f'{date[0]} {merchant.group(1)} {direction} {amount[0]}',platform,account)
    for r in rows:
        r['sources'] = [dict(file=filename, ocr=True, min_confidence=float(min(scores)) if scores else 0)]
        r['raw'] = {'ocr_text': extracted}
    return rows, errors, extracted, float(min(scores)) if scores else 0
