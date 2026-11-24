import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.main import app
from backend import storage as db


def decision(question):
    kind,id=question['kind'],question['tx_id']
    if kind=='category':
        categories=['餐饮','餐饮','交通','购物','生活服务','教育','娱乐','医疗','居住缴费']
        category=categories[int(id[4:])%9] if id.startswith('DEMO') and id[4:].isdigit() else '购物'
        return dict(action='category',category=category)
    if kind=='transfer' and id=='DEMO-FRIEND':return dict(action='keep',category='其他')
    if kind=='refund' and id=='DEMO-REFUND-MISSING':return dict(action='exclude')
    if kind=='duplicate' and id in ['DEMO-SAME-1','DEMO-SAME-2']:return dict(action='keep')
    if kind=='anomaly':return dict(action='confirm')
    raise ValueError(f'未定义的构造演示操作：{id} / {kind}')


def validate():
    results=[]
    with tempfile.TemporaryDirectory(prefix='bill-synthetic-demo-') as directory:
        with patch.dict(os.environ,{'BILL_DATA_DIR':directory,'LLM_API_KEY':''}), \
                patch('backend.main.load_dotenv',lambda *a,**kw:None), \
                patch('backend.llm.call_json',side_effect=AssertionError('离线演示不调用模型')), \
                patch('httpx.HTTPTransport.handle_request',side_effect=AssertionError('离线演示不联网')):
            with TestClient(app) as client:
                job=client.post('/api/demo').json()
                assert job['imported']==65 and job['synthetic']
                client.post('/api/jobs/'+job['id']+'/run').raise_for_status()
                for _ in range(100):
                    pending=client.get('/api/reviews').json()
                    if not pending:break
                    question=pending[0];answer=decision(question)
                    response=client.post('/api/reviews/'+question['id']+'/answer',json=answer)
                    response.raise_for_status()
                    results.append(dict(question=question,answer=answer,event_id=response.json()['event']['id']))
                else:raise ValueError('核对循环次数超限')
                ledger=client.get('/api/ledger').json()
                expected=dict(count=65,confirmed=60,pending=0,excluded=5,expense=669100,refund=4300,net=664800)
                assert all(ledger['summary'][k]==v for k,v in expected.items()),ledger['summary']
                assert client.get('/api/jobs/'+job['id']).json()['status']=='complete'
                exported=client.get('/api/export?format=xlsx');exported.raise_for_status()
                book=pd.ExcelFile(io.BytesIO(exported.content))
                sheets={name:len(pd.read_excel(book,sheet_name=name)) for name in book.sheet_names}
                assert sheets['核对后账本']==60 and sheets['待核对记录']==0 and sheets['全部记录']==65 and sheets['排除记录']==5
                (ROOT/'docs/demo_核对后账本.xlsx').write_bytes(exported.content)
                last=results[-1]
                client.post('/api/events/'+last['event_id']+'/undo').raise_for_status()
                assert client.get('/api/jobs/'+job['id']).json()['status']=='review'
                client.post('/api/reviews/'+last['question']['id']+'/answer',json=last['answer']).raise_for_status()
                assert client.get('/api/jobs/'+job['id']).json()['status']=='complete'
                assert client.get('/api/ledger').json()['summary']['net']==expected['net']
                with db.connect() as con:assert con.execute('SELECT COUNT(*) FROM usage').fetchone()[0]==0
                result=dict(synthetic=True,verified_on='2026-11-25',operator='脚本按预先声明的构造场景执行核对，不是真实用户研究',
                    summary=ledger['summary'],trace=client.get('/api/jobs/'+job['id']).json()['trace'],
                    decisions=results,export_sheets=sheets,undo_and_reconfirm=True,external_calls=0,
                    export_stage='首次核对完成后导出；随后在临时库额外验证撤销和再确认')
    (ROOT/'results/demo_replay.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(summary=result['summary'],export_sheets=sheets,undo_and_reconfirm=True),ensure_ascii=False))
    return result


if __name__=='__main__':validate()
