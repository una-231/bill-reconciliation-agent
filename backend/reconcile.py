import hashlib
from collections import defaultdict
from datetime import datetime
from .ml import classify, bundle, rank_matches, anomaly_alerts
from .schema import CATEGORIES


def analyze(records, job_id, use_matching=True, use_review=True, use_quality=True):
    rows=[dict(r) for r in records]
    lookup={r['id']:r for r in rows}
    reviews=[]
    def ask(r,kind,reason,options=None):
        key=hashlib.sha256(f'{job_id}:{r["id"]}:{kind}'.encode()).hexdigest()[:24]
        reviews.append(dict(id=key,job_id=job_id,tx_id=r['id'],kind=kind,reason=reason,
            options=options or [],status='open',merchant=r['merchant'],amount=r['amount'],time=r['time']))
    def is_fixed(r):return r.get('user_confirmed',False)
    classify_rows=[r for r in rows if r['direction']=='支出' and r['kind']=='消费' and not is_fixed(r)]
    b=bundle()
    for r,(category,confidence) in zip(classify_rows,classify(classify_rows)):
        r.update(category=category,confidence=confidence)
    seen={}
    for r in sorted(rows,key=lambda x:x['time']):
        if is_fixed(r):continue
        r.update(review_status='已核对')
        status=r.get('status','')
        if any(w in status for w in ['失败','已关闭','交易关闭','撤销','待付款']):
            r.update(excluded=True,exclusion_reason='未实际收支')
            continue
        if status and not any(w in status for w in ['成功','已收款','已支付','已完成','退款','完成']):
            ask(r,'status','交易状态尚不能确认实际收支，请核对后确认或排除')
        if use_quality and not r.get('merchant'):
            ask(r,'field','缺少交易对方，请核对原始记录')
        if r.get('ocr_review_required'):
            ask(r,'ocr','请对照原截图确认日期、金额和商户，OCR识别不能替代账务核对')
        key=(r['platform'],r['account'],r.get('order_id'))
        if use_matching and r.get('order_id') and key in seen:
            target=seen[key]
            if (r['amount'],r['direction'],r['kind'])==(target['amount'],target['direction'],target['kind']):
                r.update(excluded=True,linked_id=target['id'],exclusion_reason='同账户同订单重复记录')
                continue
            ask(r,'duplicate','同订单号出现不同金额或方向，不能自动合并',[dict(id=target['id'],score=1)])
        else:
            seen[key]=r
        if r['direction']=='支出' and r['kind']=='消费' and r.get('confidence',0)<b['category_threshold']:
            ask(r,'category',f'消费分类置信度 {r.get("confidence",0):.0%}，请确认类别',CATEGORIES)
        if r['kind']=='转账' and not use_matching:
            # 消融时采用原始收支口径。
            continue
        if r['kind'] in ['退款','转账']:
            if not use_matching:
                if r['kind']=='退款':r['category']='其他'
                continue
            rank=rank_matches(r,rows)
            if r['kind']=='退款':
                exact=[x for x in rows if r.get('reference') and x.get('order_id')==r['reference'] and x['account']==r['account'] and x['kind']=='消费' and not x.get('excluded') and x['time']<=r['time']]
                target=exact[0] if len(exact)==1 else None
                if target is None and rank and rank[0]['score']>=b['match_thresholds']['refund'] and (len(rank)<2 or rank[0]['score']-rank[1]['score']>.15):
                    target=lookup[rank[0]['id']]
                if target:
                    refunded=sum(x['amount'] for x in rows if x['id']!=r['id'] and x['kind']=='退款' and x.get('linked_id')==target['id'] and not x.get('excluded'))
                    if r['amount']+refunded<=target['amount']:
                        r.update(linked_id=target['id'],category=target.get('category') or '其他')
                    else:
                        ask(r,'refund','累计退款超过原订单金额，请核对原订单或排除此条',[dict(id=target['id'],score=1)])
                else:
                    ask(r,'refund','未找到足够确定的原订单，请选择原消费或补充账单',rank)
            else:
                # 本人账户由导入时的账户别名声明；朋友名称不会自动进入此集合。
                own={x['account'] for x in rows}
                exact=[x for x in rows if x['id']!=r['id'] and x['kind']=='转账' and x['account']!=r['account'] and x['direction']!=r['direction'] and x['amount']==r['amount'] and r.get('reference') and x.get('reference')==r['reference'] and r['merchant'] in own and x['merchant'] in own and abs((datetime.fromisoformat(x['time'])-datetime.fromisoformat(r['time'])).total_seconds())<=86400]
                if len(exact)==1:
                    r.update(excluded=True,linked_id=exact[0]['id'],exclusion_reason='本人账户内部转账')
                elif r.get('linked_id') and lookup.get(r['linked_id'],{}).get('exclusion_reason')=='本人账户内部转账':
                    r.update(excluded=True,exclusion_reason='本人账户内部转账')
                else:
                    ask(r,'transfer','请确认是本人账户划转，还是向他人付款',rank)
        elif use_matching and r['direction']=='支出' and not r.get('excluded'):
            rank=rank_matches(r,rows)
            possible=[x for x in rank if x['score']>=.25 and x['id'] in lookup and lookup[x['id']]['time']<=r['time']]
            if possible and not r.get('order_id'):
                ask(r,'duplicate','存在同额近时记录，请核对是否重复；同额不等于同订单',possible)
    for r in rows:
        if r['kind']=='退款' and r.get('linked_id') in lookup:
            r['category']=lookup[r['linked_id']].get('category') or '其他'
    alerts=anomaly_alerts(rows)
    for r in rows:
        if r['id'] in alerts and not is_fixed(r) and not r.get('excluded'):
            ask(r,'anomaly',alerts[r['id']]['reason']+'；这只是异常提示，请确认是否为真实交易')
    open_ids={v['tx_id'] for v in reviews}
    for r in rows:
        if r['id'] in open_ids:r['review_status']='待核对'
    if not use_review:
        for r in rows:r['review_status']='已核对'
        reviews=[]
    return rows,reviews


def summary(rows):
    confirmed=[r for r in rows if r['review_status']=='已核对' and not r.get('excluded')]
    spend=sum(r['amount'] for r in confirmed if r['direction']=='支出')
    refund=sum(r['amount'] for r in confirmed if r['kind']=='退款' and r.get('linked_id'))
    income=sum(r['amount'] for r in confirmed if r['direction']=='收入' and r['kind']!='退款')
    cats=defaultdict(int);months=defaultdict(lambda:dict(expense=0,refund=0,net=0))
    for r in confirmed:
        month=months[r['time'][:7]]
        if r['direction']=='支出':
            cats[r.get('category') or '其他']+=r['amount'];month['expense']+=r['amount'];month['net']+=r['amount']
        elif r['kind']=='退款' and r.get('linked_id'):
            cats[r.get('category') or '其他']-=r['amount'];month['refund']+=r['amount'];month['net']-=r['amount']
    ms=[dict(month=k,**v) for k,v in sorted(months.items())]
    changes=[]
    for previous,current in zip(ms,ms[1:]):
        if current['expense']>previous['expense']*1.5 and current['expense']-previous['expense']>=10000:
            changes.append(dict(month=current['month'],message=f'{current["month"]} 支出较上个有数据月份增长 {(current["expense"]/max(previous["expense"],1)-1):.0%}，请结合账单覆盖范围核对'))
    return dict(count=len(rows),confirmed=len(confirmed),pending=sum(r['review_status']=='待核对' for r in rows),
        excluded=sum(bool(r.get('excluded')) for r in rows),expense=spend,refund=refund,net=spend-refund,income=income,
        categories=[dict(name=k,value=v) for k,v in sorted(cats.items(),key=lambda kv:-kv[1])],months=ms,changes=changes,
        history_note='至少30条此前月份消费才启用历史异常检测；月份变化受导入覆盖范围影响')
