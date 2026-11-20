from backend.intake import parse_screenshot_list
from backend.reconcile import analyze, summary


def parse(text, platform='微信', reference_date=None, content=b'constructed-screenshot'):
    return parse_screenshot_list(text, content, 'constructed.jpg', platform, '我的' + platform, reference_date)


def test_wechat_list_uses_header_year_and_separate_date_lines():
    rows, errors = parse('账单\n2025年8月 支出￥999.00 收入￥99.00\n青禾面馆 -18.00\n8月16日12:10\n青禾面馆-退款 +3.00\n8月16日13:10\n青禾面馆 -5.00\n8月15日12:00 已退款(￥2.00)')
    assert not errors and len(rows) == 3
    assert [r['amount'] for r in rows] == [1800, 300, 500]
    assert rows[0]['time'] == '2025-08-16T12:10:00'
    assert rows[1]['kind'] == '退款' and rows[2]['kind'] == '消费'
    assert all(r['ocr_review_required'] for r in rows)


def test_alipay_year_and_yesterday_require_explicit_context():
    text = '11月\n支出￥200.00 收入￥0.00\n闪购 青禾面馆 -18.00\n餐饮美食\n昨天11:06\n春山商店 -8.00\n11-1711:21'
    rows, errors = parse(text, '支付宝')
    assert not rows and len(errors) == 2
    assert '相对日期' in errors[0]['error'] and '年份' in errors[1]['error']
    rows, errors = parse(text, '支付宝', '2025-11-19')
    assert not errors
    assert [r['time'] for r in rows] == ['2025-11-18T11:06:00', '2025-11-17T11:21:00']
    assert rows[0]['merchant'] == '青禾面馆'


def test_list_corrupt_money_and_cropped_time_are_withheld():
    text = '2025年8月\n青禾面馆 -18.00\n8月16日12:10\n春山商店 88.8-\n8月15日12:00\n云杉药房 -6.00'
    rows, errors = parse(text)
    assert len(rows) == 1 and len(errors) == 2
    assert '金额' in errors[0]['error'] and '截断' in errors[1]['error']
    assert '88.8-' in errors[0]['raw']['ocr_block']


def test_overlap_without_order_requires_review_and_same_amount_different_day_kept():
    text = '2025年8月\n青禾面馆 -18.00\n8月16日12:10\n青禾面馆 -18.00\n8月15日12:10'
    first, _ = parse(text)
    second, _ = parse(text, content=b'another-constructed-screenshot')
    rows, reviews = analyze(first + second, 'list-test')
    assert not any(r['excluded'] for r in rows)
    duplicates = [q for q in reviews if q['kind'] == 'duplicate']
    assert duplicates
    lookup = {r['id']: r for r in rows}
    for q in duplicates:
        assert all(lookup[o['id']]['time'] == lookup[q['tx_id']]['time'] for o in q['options'])
    assert summary(rows)['net'] == 0
    repeated, _ = parse(text)
    assert [r['id'] for r in first] == [r['id'] for r in repeated]


def test_screenshot_refund_without_order_stays_a_suggestion():
    rows, _ = parse('2025年8月\n青禾面馆 -18.00\n8月16日12:10\n青禾面馆-退款 +3.00\n8月16日13:10')
    analyzed, reviews = analyze(rows, 'refund-list-test')
    refund = next(r for r in analyzed if r['kind'] == '退款')
    assert not refund['linked_id']
    assert any(q['kind'] == 'refund' for q in reviews)
    assert summary(analyzed)['refund'] == 0
