import hashlib
import math
import re
import unicodedata
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher

from .intake import cents, screenshot_blocks


NUMERIC_FEATURES = [
    'platform_wechat', 'platform_alipay', 'amount_cents', 'signed_amount_cents',
    'log1p_amount_yuan', 'is_expense', 'is_income', 'is_refund', 'is_transfer',
    'has_refund_annotation', 'refund_annotation_cents', 'year', 'month', 'day',
    'hour', 'minute', 'weekday', 'hour_sin', 'hour_cos', 'relative_day_offset',
    'missing_amount', 'missing_year', 'missing_day', 'missing_clock',
    'merchant_truncated', 'merchant_length',
]


def clean_merchant(text):
    text = unicodedata.normalize('NFKC', text).strip().lower()
    text = re.sub(r'^(?:闪购|美团|淘宝|收银通|业发|收)\s+', '', text)
    text = re.sub(r'[-－—·\s]*退款$', '', text)
    text = re.sub(r'\.{2,}|…+', '', text)
    return ''.join(c for c in text if unicodedata.category(c)[0] in ['L', 'N'])


def extract_features(extracted, digest, filename, platform, account, reference_date=None):
    if platform not in ['微信', '支付宝']:
        raise ValueError('仅支持微信和支付宝')
    grouped = screenshot_blocks(extracted)
    if grouped is None:
        raise ValueError('没有识别到交易列表')
    header, blocks = grouped
    context = date.fromisoformat(str(reference_date)) if reference_date else None
    year_match = re.search(r'(20\d{2})年', header)
    header_month = re.search(r'(\d{1,2})月', header)
    header_year = int(year_match[1]) if year_match else None
    result = []
    for index, (row_number, block) in enumerate(blocks, 1):
        amount = re.search(r'([+\-−－–])\s*(\d+\.\d{2})\s*$', block[0])
        invalid_amount = re.search(r'\s+\d+\.\d+[-+]\s*$', block[0])
        merchant_raw = block[0][:amount.start() if amount else (
            invalid_amount.start() if invalid_amount else len(block[0]))].strip()
        merchant = clean_merchant(merchant_raw)
        detail = '\n'.join(block[1:])
        clock = re.search(r'(\d{1,2}):(\d{2})', detail)
        month_day = re.search(r'(\d{1,2})(?:月|-)(\d{1,2})(?:日|(?=\s|\d{1,2}:))', detail)
        relative = re.search(r'(今天|昨天|前天)', detail)
        refund_annotation = re.search(r'已退款\s*[(（]\s*[¥￥]?\s*(\d+\.\d{2})', detail)
        value = cents(amount[2]) if amount else None
        direction = ('收入' if amount[1] == '+' else '支出') if amount else None
        is_refund = '退款' in merchant_raw and direction == '收入'
        is_transfer = '转账' in merchant_raw
        year = header_year or (context.year if context else None)
        month = int(month_day[1]) if month_day else (int(header_month[1]) if header_month else None)
        day = int(month_day[2]) if month_day else None
        relative_offset = {'今天': 0, '昨天': -1, '前天': -2}[relative[1]] if relative else None
        resolved = None
        if relative and context:
            resolved = context + timedelta(days=relative_offset)
            year, month, day = resolved.year, resolved.month, resolved.day
        elif year and month and day:
            resolved = date(year, month, day)
        hour, minute = (int(clock[1]), int(clock[2])) if clock else (None, None)
        if hour is not None and (hour > 23 or minute > 59):
            hour, minute = None, None
        timestamp = datetime.combine(resolved, datetime.min.time()).replace(hour=hour, minute=minute).isoformat() \
            if resolved and hour is not None else None
        signed_value = value * (-1 if direction == '支出' else 1) if value is not None else None
        phase = 2 * math.pi * (hour + minute / 60) / 24 if hour is not None else None
        issues = []
        if value is None:
            issues.append('金额识别异常')
        if year is None:
            issues.append('年份缺失')
        if relative and not context:
            issues.append('相对日期待确认')
        if not month_day and not relative or hour is None:
            issues.append('时间截断或缺失')
        truncated = bool(re.search(r'\.{2,}|…', merchant_raw))
        if truncated:
            issues.append('商户名称截断')
        fields = dict(platform_wechat=int(platform == '微信'), platform_alipay=int(platform == '支付宝'),
            amount_cents=value, signed_amount_cents=signed_value,
            log1p_amount_yuan=math.log1p(value / 100) if value is not None else None,
            is_expense=int(direction == '支出') if direction else None,
            is_income=int(direction == '收入') if direction else None,
            is_refund=int(is_refund), is_transfer=int(is_transfer),
            has_refund_annotation=int(bool(refund_annotation)),
            refund_annotation_cents=cents(refund_annotation[1]) if refund_annotation else None,
            year=year, month=month, day=day, hour=hour, minute=minute,
            weekday=resolved.weekday() if resolved else None,
            hour_sin=math.sin(phase) if phase is not None else None,
            hour_cos=math.cos(phase) if phase is not None else None,
            relative_day_offset=relative_offset, missing_amount=int(value is None),
            missing_year=int(year is None), missing_day=int(day is None), missing_clock=int(hour is None),
            merchant_truncated=int(truncated), merchant_length=len(merchant))
        result.append(dict(id=hashlib.sha256(f'{digest}:feature:{row_number}'.encode()).hexdigest()[:24],
            file=filename, source_sha256=digest, source_row=row_number, block_index=index,
            platform=platform, account=account, merchant_raw=merchant_raw, merchant_clean=merchant,
            text_for_classifier=f'{merchant} {merchant}'.strip(), raw_block='\n'.join(block),
            direction=direction, kind='退款' if is_refund else ('转账' if is_transfer else (
                '消费' if direction == '支出' else ('收入' if direction == '收入' else '待确认'))),
            timestamp=timestamp, relative_date=relative[1] if relative else '',
            date_basis='截图年份' if header_year else ('用户提供日期' if context else '未确认'),
            issues=issues, requires_review=True, features=fields))
    return result


def matching_features(records):
    pairs = []
    for i, left in enumerate(records):
        for right in records[i + 1:]:
            a, b = left['features'], right['features']
            if left['platform'] != right['platform'] or left['account'] != right['account']:
                continue
            if a['amount_cents'] is None or b['amount_cents'] is None:
                continue
            similarity = SequenceMatcher(None, left['merchant_clean'], right['merchant_clean']).ratio()
            if not left['merchant_clean'] or not right['merchant_clean'] or similarity < .6:
                continue
            refund_pair = bool(a['is_refund']) != bool(b['is_refund']) and left['direction'] != right['direction']
            equal_amount = a['amount_cents'] == b['amount_cents']
            if not refund_pair and not equal_amount:
                continue
            difference = abs((datetime.fromisoformat(left['timestamp']) - datetime.fromisoformat(right['timestamp'])).total_seconds()) \
                if left['timestamp'] and right['timestamp'] else None
            visible_date_equal = (a['month'], a['day']) == (b['month'], b['day']) \
                if a['day'] is not None and b['day'] is not None else None
            clock_equal = (a['hour'], a['minute']) == (b['hour'], b['minute']) \
                if a['hour'] is not None and b['hour'] is not None else None
            if refund_pair:
                refund, original = (left, right) if a['is_refund'] else (right, left)
                if refund['features']['amount_cents'] > original['features']['amount_cents']:
                    continue
                if refund['timestamp'] and original['timestamp'] and refund['timestamp'] < original['timestamp']:
                    continue
                annotation_equal = original['features']['refund_annotation_cents'] == refund['features']['amount_cents']
                reason = '退款候选，备注金额一致' if annotation_equal else '退款候选，缺少订单号'
            elif visible_date_equal and clock_equal:
                reason = '跨截图重叠候选，缺少订单号待确认'
            elif visible_date_equal is False:
                reason = '同额同商户但日期不同，保留为不同交易'
            else:
                reason = '同额同商户但时间不全，不自动合并'
            pairs.append(dict(left_id=left['id'], right_id=right['id'], relation_hint='退款候选' if refund_pair else '重复核对',
                same_amount=int(equal_amount), amount_difference_cents=abs(a['amount_cents'] - b['amount_cents']),
                amount_relative_difference=abs(a['amount_cents'] - b['amount_cents']) / max(a['amount_cents'], b['amount_cents'], 1),
                absolute_time_difference_seconds=difference, time_difference_missing=int(difference is None),
                merchant_similarity=similarity, opposite_direction=int(left['direction'] != right['direction']),
                same_account=1, same_platform=1, same_visible_month_day=visible_date_equal,
                same_clock=clock_equal, evidence=reason, auto_merge=False))
    return pairs
