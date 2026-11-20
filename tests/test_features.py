import math

from backend.features import clean_merchant, extract_features, matching_features


def features(text, platform='支付宝', reference_date=None, digest='constructed'):
    return extract_features(text, digest, 'constructed.jpg', platform, '我的' + platform, reference_date)


def test_text_cleanup_preserves_branch_and_does_not_complete_truncation():
    assert clean_merchant('闪购 青禾面馆（东门店）...') == '青禾面馆东门店'
    assert clean_merchant('青禾面馆-退款') == '青禾面馆'
    assert clean_merchant('南山超市1店') != clean_merchant('南山超市2店')


def test_unknown_year_retains_visible_month_day_and_midnight():
    rows = features('11月\n南山超市 -0.00\n11-17 00:00\n青禾面馆 -8.00\n昨天11:06')
    a, b = [r['features'] for r in rows]
    assert a['amount_cents'] == 0 and a['missing_amount'] == 0
    assert a['month'] == 11 and a['day'] == 17 and a['hour'] == 0
    assert a['year'] is a['weekday'] is None
    assert a['hour_sin'] == 0 and a['hour_cos'] == 1
    assert b['relative_day_offset'] == -1 and b['day'] is None
    assert all(r['timestamp'] is None for r in rows)


def test_bad_money_stays_missing_and_crop_does_not_inherit_previous_date():
    rows = features('2025年8月\n南山超市 -8.00\n8月16日00:00\n青禾面馆 88.8-\n8月15日12:00\n云杉药房 -6.00', '微信')
    bad, cropped = rows[1:]
    assert bad['features']['amount_cents'] is bad['features']['is_expense'] is None
    assert bad['features']['missing_amount'] == 1
    assert bad['merchant_clean'] == '青禾面馆'
    assert cropped['features']['day'] is cropped['features']['hour'] is None
    assert cropped['timestamp'] is None


def test_refund_annotation_is_feature_not_an_extra_transaction():
    rows = features('2025年8月\n青禾面馆 -18.00\n8月16日12:00 已退款(￥3.00)\n青禾面馆-退款 +3.00\n8月16日13:00', '微信')
    assert len(rows) == 2
    assert rows[0]['features']['refund_annotation_cents'] == 300
    assert rows[0]['features']['signed_amount_cents'] == -1800
    assert rows[1]['features']['signed_amount_cents'] == 300
    pairs = matching_features(rows)
    assert len(pairs) == 1 and '备注金额一致' in pairs[0]['evidence']
    assert pairs[0]['absolute_time_difference_seconds'] == 3600
    assert not pairs[0]['auto_merge']


def test_partial_date_overlap_keeps_time_difference_missing():
    text = '11月\n青禾面馆 -18.00\n11-16 12:10\n青禾面馆 -18.00\n11-15 12:10'
    first, second = features(text), features(text, digest='another')
    pairs = matching_features(first + second)
    assert any('重叠候选' in p['evidence'] for p in pairs)
    assert any('日期不同' in p['evidence'] for p in pairs)
    assert all(p['absolute_time_difference_seconds'] is None and p['time_difference_missing'] == 1 for p in pairs)
    assert not any(p['auto_merge'] for p in pairs)


def test_confirmed_context_resolves_relative_date_without_using_current_clock():
    rows = features('11月\n南山超市 -8.00\n昨天11:06\n青禾面馆 -6.00\n11-17 11:21', reference_date='2025-11-19')
    assert rows[0]['timestamp'] == '2025-11-18T11:06:00'
    assert rows[0]['features']['weekday'] == 1
    assert math.isfinite(rows[0]['features']['log1p_amount_yuan'])
    assert 'category' not in rows[0]['features']
