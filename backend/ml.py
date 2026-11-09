import json
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path
import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_cache = None


def text_of(r):
    return (r.get('merchant','')+' '+r.get('description','')).strip()


def bundle():
    global _cache
    path = ROOT/'models/active.joblib'
    if not path.exists():
        raise ValueError('分类模型未训练，请先运行 python scripts/train.py')
    stamp = path.stat().st_mtime_ns
    if _cache is None or _cache[0] != stamp:
        _cache = (stamp, joblib.load(path))
    return _cache[1]


def classify(rows):
    if not rows:
        return []
    b = bundle()
    probs = b['classifier'].predict_proba([text_of(r) for r in rows])
    classes = b['classifier'].classes_
    return [(str(classes[int(p.argmax())]),float(p.max())) for p in probs]


def pair_features(a,b):
    dt = abs((datetime.fromisoformat(a['time'])-datetime.fromisoformat(b['time'])).total_seconds())/3600
    aa,bb = a['amount'],b['amount']
    return [int(aa==bb), abs(aa-bb)/max(aa,bb,1), min(dt,2160)/2160,
        SequenceMatcher(None,a.get('merchant',''),b.get('merchant','')).ratio(),
        int(a['direction']!=b['direction']), int(a['account']==b['account']),
        int(a['platform']==b['platform']),
        int(bool(a.get('order_id')) and a.get('order_id')==b.get('order_id')),
        int(bool(a.get('reference')) and a['reference']==b.get('order_id')),
        int(a.get('kind')=='退款'), int(a.get('kind')=='转账' and b.get('kind')=='转账'),
        int(bool(a.get('reference')) and a['reference']==b.get('reference'))]


def candidates(a,rows):
    result = []
    seen_orders=set()
    ta = datetime.fromisoformat(a['time'])
    for b in rows:
        if a['id']==b['id'] or b.get('excluded') or b.get('kind')=='退款':
            continue
        delta = (ta-datetime.fromisoformat(b['time'])).total_seconds()
        if a.get('kind')=='退款':
            key=(b['platform'],b['account'],b.get('order_id'))
            if b.get('order_id') and key in seen_orders:
                continue
            if b.get('order_id'):
                seen_orders.add(key)
            ok = b['direction']=='支出' and b.get('kind')!='转账' and 0<=delta<=90*86400 and a['amount']<=b['amount']
        elif a.get('kind')=='转账':
            ok = b.get('kind')=='转账' and a['direction']!=b['direction'] and a['amount']==b['amount'] and abs(delta)<=86400
        else:
            ok = a['account']==b['account'] and a['direction']==b['direction'] and a['amount']==b['amount'] and abs(delta)<=600
        if ok:
            result.append(b)
    return result


def rank_matches(a,rows):
    cs = candidates(a,rows)
    if not cs:
        return []
    b = bundle()
    model = b['matcher']
    probs = model.predict_proba([pair_features(a,x) for x in cs])
    kind = 'refund' if a['kind']=='退款' else ('transfer' if a['kind']=='转账' else 'duplicate')
    idx = list(model.classes_).index(kind)
    return sorted([dict(id=x['id'],score=float(p[idx]),relation=kind) for x,p in zip(cs,probs)],key=lambda x:x['score'],reverse=True)[:3]


def anomaly_alerts(rows):
    from sklearn.ensemble import IsolationForest
    history = []
    alerts = {}
    for r in sorted(rows,key=lambda x:x['time']):
        if r['direction']!='支出' or r.get('excluded') or r['kind']!='消费':
            continue
        # 每个月只用此前月份拟合，避免把当前交易放入自己的历史。
        month=r['time'][:7]
        prior=[x for x in history if x['time'][:7]<month]
        if len(prior)>=30:
            amounts=np.array([x['amount'] for x in prior],dtype=float)
            median=float(np.median(amounts))
            if r['amount']>max(median*4,float(np.percentile(amounts,95))):
                alerts[r['id']]=dict(reason=f'金额为历史中位数的 {r["amount"]/max(median,1):.1f} 倍',type='amount')
        history.append(r)
    for month in sorted(set(r['time'][:7] for r in history)):
        prior=[x for x in history if x['time'][:7]<month]
        current=[x for x in history if x['time'][:7]==month]
        if len(prior)<30:
            continue
        model=IsolationForest(n_estimators=80,contamination=.04,random_state=42)
        def features(rs):
            return np.array([[np.log1p(x['amount']), datetime.fromisoformat(x['time']).hour/24] for x in rs])
        model.fit(features(prior))
        for r,pred in zip(current,model.predict(features(current))):
            if pred==-1:
                alerts.setdefault(r['id'],dict(reason='金额与时段组合偏离历史分布',type='isolation_forest'))
    return alerts
