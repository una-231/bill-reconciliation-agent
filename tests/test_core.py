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
