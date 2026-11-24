import io
import json
import os
from datetime import datetime,timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from backend.schema import Transaction
from backend.intake import cents,parse_table,parse_text,MappingRequired
from backend.quality import inspect_records
from backend.reconcile import analyze,summary
from backend.ml import anomaly_alerts
from backend import storage as db
from backend.main import app


def tx(id,**kw):
    base=dict(platform='微信',account='我的微信',time='2026-08-01T12:00:00',direction='支出',amount=5000,merchant='面馆',description='午餐面馆消费',order_id=id)
    base.update(kw)
    return Transaction(id=id,**base).model_dump()


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('BILL_DATA_DIR',str(tmp_path))
    monkeypatch.delenv('LLM_API_KEY',raising=False)
    monkeypatch.setenv('LLM_INPUT_CNY_PER_M','0.15')
    monkeypatch.setenv('LLM_OUTPUT_CNY_PER_M','1.5')
    monkeypatch.setattr('backend.main.load_dotenv',lambda *args,**kwargs:None)
    with TestClient(app) as c:yield c


@pytest.mark.parametrize('value,expected',[('￥1,234.50',123450),('0',0),('12.30元',1230)])
def test_money_exact(value,expected):assert cents(value)==expected


@pytest.mark.parametrize('value',['-1','nan','1.001','USD 10','Infinity'])
def test_money_reject(value):
    with pytest.raises(ValueError):cents(value)


def test_csv_headers_and_bad_rows():
    text='构造账单\n交易时间,交易对方,收/支,金额(元),商品说明\n2026-09-01,面馆,支出,12.30,午餐\n错误日期,商店,支出,20,商品\n'
    rows,errors=parse_table(text.encode('utf-8-sig'),'微信.csv','微信','我的微信')
    assert len(rows)==len(errors)==1 and rows[0]['amount']==1230 and rows[0]['sources'][0]['row']==3


def test_xlsx_preamble():
    f=io.BytesIO();pd.DataFrame([['构造账单','','',''],['交易时间','金额(元)','收/支','交易对方'],['2026-09-01','10.50','支出','公交']]).to_excel(f,index=False,header=False)
    rows,errors=parse_table(f.getvalue(),'账单.xlsx','支付宝','我的支付宝')
    assert not errors and rows[0]['amount']==1050


def test_mapping_required_and_apply():
    raw=b'date,money,type,vendor\n2026-09-01,8.10,expense,shop'
    with pytest.raises(MappingRequired):parse_table(raw,'x.csv','微信','我')
    raw='日期,数额,方向,对方\n2026-09-01,8.10,支出,商店'.encode()
    rows,errors=parse_table(raw,'x.csv','微信','我',{'time':'日期','amount':'数额','direction':'方向','merchant':'对方'})
    assert rows[0]['amount']==810 and not errors


def test_text_missing_fields_not_invented():
    rows,errors=parse_text('2026-09-08 青禾面馆 支出 28.00元\n昨天买了东西','微信','我')
    assert len(rows)==len(errors)==1 and rows[0]['merchant']=='青禾面馆'


def test_empty_quality_and_missing():
    assert inspect_records([])['rows']==0
    result=inspect_records([tx('a',merchant='')]);assert result['missing']=={'merchant':1}


def test_duplicate_same_order_excluded_preserve_source():
    a=tx('a');b=tx('b',order_id='a',sources=[{'file':'再次导出'}])
    rows,_=analyze([a,b],'j');assert rows[1]['excluded'] and rows[1]['linked_id']=='a'
    assert rows[1]['sources'][0]['file']=='再次导出'


def test_same_amount_different_orders_kept():
    rows,_=analyze([tx('a'),tx('b',time='2026-08-01T12:01:00')],'j')
    assert all(not r['excluded'] for r in rows)


def test_order_conflict_review():
    rows,qs=analyze([tx('a'),tx('b',order_id='a',amount=6000)],'j')
    assert not rows[1]['excluded'] and any(q['kind']=='duplicate' for q in qs)


def test_friend_transfer_not_automatically_internal():
    rows,qs=analyze([tx('friend',kind='转账',merchant='张同学')],'j')
    assert not rows[0]['excluded'] and any(q['kind']=='transfer' for q in qs)


def test_internal_transfer_both_sides():
    a=tx('a',kind='转账',merchant='我的支付宝',reference='own')
    b=tx('b',platform='支付宝',account='我的支付宝',kind='转账',merchant='我的微信',reference='own',direction='收入')
    rows,qs=analyze([a,b],'j');assert all(r['excluded'] for r in rows)


def test_partial_multi_refund_cross_month_and_overflow():
    a=tx('a',amount=10000,time='2026-07-31T12:00:00')
    rs=[tx('r1',kind='退款',direction='收入',reference='a',amount=4000),tx('r2',kind='退款',direction='收入',reference='a',amount=6000,time='2026-08-02T12:00:00'),tx('r3',kind='退款',direction='收入',reference='a',amount=100,time='2026-08-03T12:00:00')]
    rows,qs=analyze([a]+rs,'j');assert rows[1]['linked_id']==rows[2]['linked_id']=='a'
    assert not rows[3]['linked_id'] and any(q['tx_id']=='r3' and q['kind']=='refund' for q in qs)
    rows[0]['review_status']='已核对';s=summary(rows)
    assert s['net']==0 and next(m for m in s['months'] if m['month']=='2026-08')['net']==-10000


def test_closed_order_not_counted():
    rows,_=analyze([tx('a',status='交易关闭')],'j');assert rows[0]['excluded'] and summary(rows)['net']==0


def test_future_data_does_not_change_past_anomaly():
    history=[tx(str(i),time=(datetime(2026,7,1)+timedelta(days=i%27,hours=i%8)).isoformat(),amount=2000+i*10) for i in range(40)]
    current=tx('current',time='2026-08-10T12:00:00',amount=50000)
    baseline=anomaly_alerts(history+[current]);future=tx('future',time='2026-09-01T12:00:00',amount=9999999)
    assert baseline['current']==anomaly_alerts(history+[current,future])['current']


def test_task_persistence_review_resume_undo(client):
    j=client.post('/api/import/text',json={'text':'2026-09-08 张同学转账 支出 28.00元','platform':'微信','account':'我的微信'}).json()
    assert client.post('/api/jobs/'+j['id']+'/run').status_code==200
    q=client.get('/api/reviews').json()[0]
    assert q['kind']=='transfer'
    assert client.get('/api/jobs/'+j['id']).json()['status']=='review'
    result=client.post('/api/reviews/'+q['id']+'/answer',json={'action':'keep'}).json()
    assert client.get('/api/jobs/'+j['id']).json()['status']=='complete'
    assert client.post('/api/events/'+result['event']['id']+'/undo').status_code==200
    assert client.get('/api/reviews').json()[0]['status']=='open'
    assert client.post('/api/reviews/'+q['id']+'/answer',json={'action':'keep'}).status_code==200
    assert client.get('/api/jobs/'+j['id']).json()['status']=='complete'


def test_reimport_same_content_and_source(client):
    body={'text':'2026-09-08 面馆 支出 28.00元','platform':'微信','account':'我的微信'}
    assert client.post('/api/import/text',json=body).json()['imported']==1
    assert client.post('/api/import/text',json=body).json()['reimported']==1
    assert len(client.get('/api/ledger').json()['rows'])==1


def test_export_excel_and_formula_safety(client):
    j=client.post('/api/import/text',json={'text':'2026-09-08 =WEBSERVICE(1) 支出 28.00元','account':'我的微信'}).json()
    client.post('/api/jobs/'+j['id']+'/run')
    csv=client.get('/api/export?format=csv');assert csv.status_code==200 and "'=WEBSERVICE" in csv.content.decode('utf-8-sig')
    xlsx=client.get('/api/export?format=xlsx');assert xlsx.status_code==200
    assert set(pd.ExcelFile(io.BytesIO(xlsx.content)).sheet_names)=={'核对后账本','待核对记录','排除记录','全部记录','修改记录'}


def test_patch_propagates_refund_and_undo_guard(client):
    from backend.main import job_with_rows
    j=job_with_rows([tx('a'),tx('ref',kind='退款',direction='收入',reference='a',amount=1000)],[],'test')
    client.post('/api/jobs/'+j['id']+'/run')
    first=client.patch('/api/ledger/a',json={'category':'购物'}).json()
    rows=client.get('/api/ledger').json()['rows'];assert all(r['category']=='购物' for r in rows)
    second=client.patch('/api/ledger/a',json={'category':'教育'}).json()
    assert client.post('/api/events/'+first['id']+'/undo').status_code==409
    assert client.post('/api/events/'+second['id']+'/undo').status_code==200
    assert client.post('/api/events/'+first['id']+'/undo').status_code==200


def test_oversized_refund_answer_rejected(client):
    from backend.main import job_with_rows
    j=job_with_rows([tx('a',amount=1000),tx('ref',kind='退款',direction='收入',amount=2000)],[],'test')
    client.post('/api/jobs/'+j['id']+'/run');qs=client.get('/api/reviews').json();q=next(q for q in qs if q['kind']=='refund')
    assert client.post('/api/reviews/'+q['id']+'/answer',json={'action':'link','target_id':'a'}).status_code==400


def test_llm_timeout_falls_back_and_budget(client,monkeypatch):
    from backend import llm
    monkeypatch.setenv('LLM_API_KEY','local-test-placeholder')
    def failed(*args,**kwargs):raise TimeoutError('测试超时')
    monkeypatch.setattr('httpx.Client.post',failed)
    r=client.post('/api/chat',json={'message':'退款情况','allow_remote':True})
    assert r.status_code==200 and r.json()['mode']=='local'
    assert llm.status()['spent_cny']>0
    monkeypatch.setenv('LLM_BUDGET_CNY','0')
    with pytest.raises(ValueError,match='预算'):llm.call_json([{'role':'user','content':'测试'}])


def test_ocr_mandatory_review():
    r=tx('ocr');r['ocr_review_required']=True
    rows,qs=analyze([r],'j');assert any(q['kind']=='ocr' for q in qs)


def test_image_reference_date_validated_and_passed(client,monkeypatch):
    from datetime import date
    seen=[]
    def image(content,filename,platform,account,reference_date):
        seen.append(reference_date)
        return [tx('screenshot')],[], 'constructed OCR', .9
    monkeypatch.setattr('backend.main.parse_image',image)
    data=dict(platform='微信',account='我的微信',reference_date='2025-08-16')
    result=client.post('/api/import/files',data=data,files={'files':('constructed.jpg',b'constructed','image/jpeg')})
    assert result.status_code==200 and result.json()['imported']==1
    assert seen==[date(2025,8,16)]
    assert db.get('transactions','screenshot')['ocr_review_required']
    data['reference_date']='not-a-date'
    assert client.post('/api/import/files',data=data,files={'files':('constructed.jpg',b'constructed','image/jpeg')}).status_code==422


def test_truth_fields_not_imported():
    raw='交易时间,金额,收/支,交易对方,truth_category,split\n2026-09-01,12,支出,商店,教育,test'
    rows,_=parse_table(raw.encode(),'x.csv','微信','我')
    assert 'truth_category' not in rows[0] and 'split' not in rows[0]


def test_category_review_propagates_refund(client):
    from backend.main import job_with_rows
    a=tx('unknown',merchant='未知公司',description='扫码支付')
    r=tx('refund',kind='退款',direction='收入',reference='unknown',amount=1000,time='2026-08-02T12:00:00')
    j=job_with_rows([a,r],[],'test');client.post('/api/jobs/'+j['id']+'/run')
    q=next(q for q in client.get('/api/reviews').json() if q['kind']=='category')
    result=client.post('/api/reviews/'+q['id']+'/answer',json={'action':'category','category':'教育'})
    assert result.status_code==200
    assert all(x['category']=='教育' for x in client.get('/api/ledger').json()['rows'])
    assert client.patch('/api/ledger/unknown',json={'excluded':True}).status_code==400


def test_ocr_no_whitespace_timestamp():
    rows,errors=parse_text('2026-09-0812:30 青禾面馆 支出28.00元','微信','我')
    assert not errors and rows[0]['time']=='2026-09-08T12:30:00' and rows[0]['merchant']=='青禾面馆'


def test_model_update_retrains_real_pipeline(client,tmp_path,monkeypatch):
    import scripts.train as training
    import shutil,joblib
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    isolated=tmp_path/'training';(isolated/'data').mkdir(parents=True)
    shutil.copy2(root/'data/synthetic.json',isolated/'data/synthetic.json')
    monkeypatch.setattr(training,'ROOT',isolated)
    with db.connect() as con:
        for i in range(18):con.execute('INSERT INTO feedback VALUES(?,?,?,?)',(str(i),str(i),f'春山学习空间{i} 自习座位预约费用','教育'))
    result=client.post('/api/models/update')
    assert result.status_code==200 and result.json()['feedback_count']==18
    trained=joblib.load(isolated/'models/active.joblib')
    assert trained['feedback_count']==18
    assert trained['classifier'].predict(['湖畔研习空间 自习座位预约费用'])[0]=='教育'


def test_failed_event_rolls_back_ledger_and_feedback(client,monkeypatch):
    from backend.main import job_with_rows
    j=job_with_rows([tx('a')],[],'test');client.post('/api/jobs/'+j['id']+'/run')
    before=db.get('transactions','a')
    def failed(*args,**kwargs):raise ValueError('模拟审计写入失败')
    monkeypatch.setattr(db,'event',failed)
    assert client.patch('/api/ledger/a',json={'category':'教育'}).status_code==400
    assert db.get('transactions','a')==before
    with db.connect() as con:assert con.execute('SELECT COUNT(*) FROM feedback').fetchone()[0]==0


def test_unknown_provider_pricing_blocks_call_without_spending(client,monkeypatch):
    from backend import llm
    monkeypatch.setenv('LLM_API_KEY','test-placeholder')
    monkeypatch.setenv('LLM_INPUT_CNY_PER_M','')
    assert not llm.status()['pricing_configured']
    with pytest.raises(ValueError,match='单价'):
        llm.call_json([{'role':'user','content':'构造账单测试'}])
    assert llm.status()['calls']==0


def test_oversized_prompt_blocks_before_budget_reservation(client,monkeypatch):
    from backend import llm
    monkeypatch.setenv('LLM_API_KEY','test-placeholder')
    monkeypatch.setenv('LLM_MAX_INPUT_TOKENS','30000')
    with pytest.raises(ValueError,match='长度限制'):
        llm.call_json([{'role':'user','content':'账'*11000}])
    assert llm.status()['calls']==0


def test_qwen_non_thinking_payload_and_usage(client,monkeypatch):
    from backend import llm
    import httpx
    monkeypatch.setenv('LLM_API_KEY','test-placeholder')
    monkeypatch.setenv('LLM_ENABLE_THINKING','false')
    def completed(self,url,**kwargs):
        assert kwargs['json']['enable_thinking'] is False
        assert kwargs['json']['response_format']=={'type':'json_object'}
        return httpx.Response(200,json={'model':'test-model','usage':{'prompt_tokens':10,'completion_tokens':20},'choices':[{'message':{'content':'{"ok":true}'}}]})
    monkeypatch.setattr('httpx.Client.post',completed)
    assert llm.call_json([{'role':'user','content':'JSON test'}])=={'ok':True}
    assert llm.status()['calls']==1


def test_confirmed_order_still_deduplicates_and_merges_sources():
    a=tx('a',sources=[{'file':'first.csv'}])
    a.update(user_confirmed=True,review_status='已核对',category='教育',confidence=1)
    b=tx('b',order_id='a',sources=[{'file':'second.csv'}],time='2026-08-01T11:59:00')
    rows,qs=analyze([a,b],'second-import')
    assert rows[1]['excluded'] and rows[1]['linked_id']=='a'
    assert rows[0]['category']=='教育' and rows[0]['user_confirmed']
    assert rows[0]['sources']==[{'file':'first.csv'},{'file':'second.csv'}]
    assert a['sources']==[{'file':'first.csv'}]
    assert not any(q['tx_id']=='b' for q in qs)


def test_confirmed_order_conflict_is_not_silently_merged():
    a=tx('a');a.update(user_confirmed=True,review_status='已核对',category='餐饮')
    rows,qs=analyze([a,tx('b',order_id='a',amount=6000)],'order-conflict')
    assert not rows[1]['excluded']
    assert any(q['kind']=='duplicate' and q['tx_id']=='b' for q in qs)


def test_duplicate_import_persists_confirmed_source_without_reclassifying(client):
    from backend.main import job_with_rows
    original=tx('a',merchant='未知公司',description='扫码支付',sources=[{'file':'first.csv'}])
    first=job_with_rows([original],[],'first')
    client.post('/api/jobs/'+first['id']+'/run')
    q=next(q for q in client.get('/api/reviews').json() if q['kind']=='category')
    assert client.post('/api/reviews/'+q['id']+'/answer',json={'action':'category','category':'教育'}).status_code==200
    repeated=tx('b',order_id='a',sources=[{'file':'second.csv'}])
    second=job_with_rows([repeated],[],'second')
    assert client.post('/api/jobs/'+second['id']+'/run').status_code==200
    assert db.get('transactions','b')['excluded']
    saved=db.get('transactions','a')
    assert saved['category']=='教育' and saved['user_confirmed']
    assert saved['sources']==[{'file':'first.csv'},{'file':'second.csv'}]


def transfer_jobs(client):
    from backend.main import job_with_rows
    first=job_with_rows([tx('left',kind='转账',merchant='我的支付宝')],[],'left')
    client.post('/api/jobs/'+first['id']+'/run')
    second=job_with_rows([tx('right',platform='支付宝',account='我的支付宝',kind='转账',direction='收入',merchant='我的微信')],[],'right')
    client.post('/api/jobs/'+second['id']+'/run')
    return first,second


def test_cross_batch_transfer_completes_both_jobs_and_undo_reopens_both(client):
    first,second=transfer_jobs(client)
    q=next(q for q in client.get('/api/reviews').json() if q['tx_id']=='right')
    result=client.post('/api/reviews/'+q['id']+'/answer',json={'action':'link','target_id':'left'})
    assert result.status_code==200
    assert all(client.get('/api/jobs/'+j['id']).json()['status']=='complete' for j in [first,second])
    assert client.get('/api/reviews').json()==[]
    assert client.post('/api/events/'+result.json()['event']['id']+'/undo').status_code==200
    assert all(client.get('/api/jobs/'+j['id']).json()['status']=='review' for j in [first,second])
    assert len(client.get('/api/reviews').json())==2
    q=next(q for q in client.get('/api/reviews').json() if q['tx_id']=='left')
    assert client.post('/api/reviews/'+q['id']+'/answer',json={'action':'link','target_id':'right'}).status_code==200
    assert all(client.get('/api/jobs/'+j['id']).json()['status']=='complete' for j in [first,second])


def test_run_recovers_stale_review_job_with_no_open_questions(client):
    from backend.main import job_with_rows
    j=job_with_rows([tx('a',kind='转账',merchant='同学')],[],'stale')
    client.post('/api/jobs/'+j['id']+'/run')
    for q in db.all_items('reviews',j['id']):
        q['status']='closed';db.save('reviews',q)
    assert client.post('/api/jobs/'+j['id']+'/run').json()['status']=='complete'


def test_unseen_text_requests_review_instead_of_using_class_prior():
    from backend.ml import classify
    unknown=tx('oov',merchant='龘靐齉',description='')
    assert classify([unknown])==[('其他',0.0)]
    rows,qs=analyze([unknown],'oov')
    assert rows[0]['review_status']=='待核对'
    assert any(q['kind']=='category' and '词表' in q['reason'] for q in qs)


def test_cross_batch_audit_failure_rolls_back_before_job_sync(client,monkeypatch):
    first,second=transfer_jobs(client)
    q=next(q for q in client.get('/api/reviews').json() if q['tx_id']=='right')
    before=[db.get('transactions',id) for id in ['left','right']]
    def failed(*args,**kwargs):raise ValueError('模拟审计失败')
    monkeypatch.setattr(db,'event',failed)
    assert client.post('/api/reviews/'+q['id']+'/answer',json={'action':'link','target_id':'left'}).status_code==400
    assert [db.get('transactions',id) for id in ['left','right']]==before
    assert len(client.get('/api/reviews').json())==2
    assert all(client.get('/api/jobs/'+j['id']).json()['status']=='review' for j in [first,second])
