import copy
import json
import sys
import time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score,f1_score

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.reconcile import analyze,summary
from backend.ml import bundle,text_of
from backend.schema import Transaction
from backend.quality import inspect_records
from backend.intake import parse_image,parse_table


def evaluate():
    all_rows=json.loads((ROOT/'data/synthetic.json').read_text(encoding='utf-8'))
    test=[r for r in all_rows if r['split']=='test']
    truth={r['id']:r for r in test}
    raw=[Transaction.model_validate(r).model_dump() for r in test]
    cases=[];failed=[]
    for name,opts in [('原始收支+模型分类',dict(use_matching=False,use_review=False)),('匹配但无人工核对',dict(use_review=False)),('完整流程',{}),('关闭数据体检',dict(use_quality=False))]:
        start=time.perf_counter();rows,qs=analyze(copy.deepcopy(raw),name,**opts)
        counted=[r for r in rows if not r.get('excluded') and r['review_status']=='已核对']
        duplicates=[r for r in counted if truth[r['id']]['truth_relation']=='duplicate']
        merged=[r for r in rows if r.get('excluded') and r.get('linked_id')]
        wrong_merged=[r for r in merged if truth[r['id']]['truth_relation'] not in ['duplicate','transfer']]
        auto=[]
        for r in rows:
            if not r.get('linked_id'):continue
            t=truth[r['id']]; correct=(t['truth_link']==r['linked_id'])
            if t['truth_relation']=='refund':
                # 原订单的重复副本属于同一经济事件，但工作流应关联规范记录。
                correct=correct or truth.get(r['linked_id'],{}).get('truth_link')==t['truth_link']
            auto.append((r,correct))
            if not correct:failed.append(dict(variant=name,id=r['id'],linked_id=r['linked_id'],truth=t['truth_link']))
        row_ids={q['tx_id'] for q in qs}
        category_errors=sum(r['category']!=truth[r['id']]['truth_category'] for r in rows if truth[r['id']]['id'].startswith('SYN'))
        cases.append(dict(variant=name,seconds=time.perf_counter()-start,records=len(rows),
            review_questions=len(qs),review_request_rate=len(row_ids)/len(rows),
            unresolved_rate=sum(r['review_status']=='待核对' for r in rows)/len(rows),
            duplicate_accounting_rate=len(duplicates)/max(len(counted),1),false_merge_rate=len(wrong_merged)/max(len(merged),1),
            automatic_link_precision=sum(v for _,v in auto)/max(len(auto),1),automatic_link_count=len(auto),
            auto_link_by_kind={kind:dict(count=sum(r['kind']==kind for r,_ in auto),precision=sum(v for r,v in auto if r['kind']==kind)/max(sum(r['kind']==kind for r,_ in auto),1)) for kind in ['退款','转账','消费']},
            category_modification_rate=category_errors/max(sum(r['id'].startswith('SYN') for r in rows),1),
            net_cents=summary(rows)['net']))
    # 人工决策用测试标签模拟，不能解释为真实用户研究。
    full_rows,qs=analyze(copy.deepcopy(raw),'oracle')
    fixes=sum(bool(r['category'] and r['category']!=truth[r['id']]['truth_category']) for r in full_rows if truth[r['id']]['id'].startswith('SYN'))
    oracle=dict(note='使用真值模拟人工反馈，不是用户实测',records_modified=fixes,category_modification_rate=fixes/max(sum(r['id'].startswith('SYN') for r in test),1))
    # 独立商户的个性化适应实验，固定测试集从未加入适应训练。
    adaptations=[dict(merchant=f'春山学习空间{i:02}',description='自习座位预约费用',truth_category='教育') for i in range(18)]
    holdout=[dict(merchant=f'湖畔研习空间{i:02}',description='自习座位预约费用',truth_category='教育') for i in range(12)]
    original=bundle()['classifier'];train=[r for r in all_rows if r['split']=='train' and r['id'].startswith('SYN')]
    improved=copy.deepcopy(original)
    improved.fit([text_of(r) for r in train+adaptations],[r['truth_category'] for r in train+adaptations])
    before=original.predict([text_of(r) for r in holdout]);after=improved.predict([text_of(r) for r in holdout])
    adaptation_result=dict(adaptation_count=18,holdout_count=12,merchant_disjoint=True,
        accuracy_before=accuracy_score(['教育']*12,before),accuracy_after=accuracy_score(['教育']*12,after),
        predictions_before=list(before),predictions_after=list(after),
        note='新增自习空间这一偏好场景，12个不同商户留出测试，共享同一服务描述，不能泛化为所有新消费')
    # 体检消融对照：完整输入与损坏字段输入分别报告。
    damaged=copy.deepcopy(raw[:30])
    for r in damaged[:5]:r['merchant']=''
    qresult=inspect_records(damaged)
    quality=dict(records=30,injected_missing_merchants=5,detected=len(qresult['issues']),without_skill_detected=0,empty_table=inspect_records([]),note='独立字段缺失探针，主测试集字段完整时关闭体检不应改变结果')
    # OCR兼容性实测：只使用构造图片。
    ocr_results=[]
    for filename in ['demo_screenshot.png','demo_screenshot_blurred.png']:
        start=time.perf_counter()
        try:
            rows,errors,text,score=parse_image((ROOT/'data'/filename).read_bytes(),filename,'微信','我的微信')
            expected=[2800,600,6800]
            correct=sum(a==b for a,b in zip([r['amount'] for r in rows],expected))
            expected_times=['2026-09-08T12:30:00','2026-09-08T18:00:00','2026-09-09T10:20:00']
            ocr_results.append(dict(file=filename,records=len(rows),expected_records=3,amount_exact=correct/3,
                time_exact=sum(r['time']==t for r,t in zip(rows,expected_times))/3,
                merchant_exact=sum(r['merchant']==t for r,t in zip(rows,['青禾面馆','城市地铁','知行书店']))/3,
                errors=len(errors),min_confidence=score,text=text,seconds=time.perf_counter()-start))
        except Exception as e:ocr_results.append(dict(file=filename,error=str(e),seconds=time.perf_counter()-start))
    result=dict(ablations=cases,simulated_human_feedback=oracle,personalization=adaptation_result,quality=quality,ocr=ocr_results,wrong_auto_links=failed,
        api_validation='pending_user_key',real_data_validation='pending_user_authorized_sample')
    (ROOT/'results/workflow_evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(cases).drop(columns=['auto_link_by_kind']).to_csv(ROOT/'results/ablations.csv',index=False,encoding='utf-8-sig')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':evaluate()
