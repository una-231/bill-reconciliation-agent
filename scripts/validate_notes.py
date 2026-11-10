import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from fastapi.testclient import TestClient
from backend import llm, notes, storage as db
from backend.schema import NoteInput
from backend.main import app


TEXT = '构造随记：昨天午饭花了二十八块，支付宝付的。今天微信买早餐，忘了写金额。'
FOLLOWUP = '早餐花了十二块五，第一笔午饭其实是三十块，仍然是支付宝付的。'


def verify_commit(draft):
    # 使用真实模型草稿验证入账，但不改变已有演示账本。
    with tempfile.TemporaryDirectory(prefix='bill-note-check-') as directory:
        with patch.dict(os.environ, {'BILL_DATA_DIR': directory}), patch('backend.main.load_dotenv', lambda *a, **kw: None):
            with TestClient(app) as client:
                db.save('notes', draft)
                body = dict(revision=draft['revision'], items=draft['items'])
                first = client.post('/api/notes/' + draft['id'] + '/commit', json=body)
                first.raise_for_status()
                job = first.json()
                repeated = client.post('/api/notes/' + draft['id'] + '/commit', json=body)
                repeated.raise_for_status()
                assert repeated.json()['id'] == job['id']
                run = client.post('/api/jobs/' + job['id'] + '/run')
                run.raise_for_status()
                ledger = client.get('/api/ledger').json()
                assert len(ledger['rows']) == 2 and sum(r['amount'] for r in ledger['rows']) == 4250
                return dict(imported=2, repeated_commit_same_job=True, sum_amount_cents=4250,
                    workflow_status=run.json()['status'], ledger=ledger, isolated_database=True)


def validate(live=False, draft_id=None):
    load_dotenv(ROOT / '.env', override=True)
    db.init()
    result_path = ROOT / 'results/note_validation.json'
    before = llm.status()
    if live:
        first = notes.preview(NoteInput(text=TEXT, reference_date='2026-11-10', allow_remote=True, synthetic=True))
        assert first['mode'] == 'api' and any(r['amount_yuan'] == '28.00' and r['date'] == '2026-11-09' for r in first['items'])
        assert first['questions']
        draft = notes.preview(NoteInput(text=FOLLOWUP, draft_id=first['id'], revision=first['revision'], allow_remote=True, synthetic=True))
        result = dict(data_source='明确构造的随记，不含真实账单', first_preview=first)
    else:
        draft = db.get('notes', draft_id)
        if not draft or not draft.get('synthetic') or draft['messages'][0]['text'] != TEXT:
            raise ValueError('只复用本脚本指定的构造草稿')
        result = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
    assert draft['mode'] == 'api' and len(draft['items']) == 2 and not draft['questions']
    assert sorted(r['amount_yuan'] for r in draft['items']) == ['12.50', '30.00']
    assert {r['platform'] for r in draft['items']} == {'微信', '支付宝'}
    assert {r['date'] for r in draft['items']} == {'2026-11-09', '2026-11-10'}
    result.update(success=True, final_preview=draft, commit_verification=verify_commit(draft))
    # 费用记录只包含用量和价格，不包含请求头或密钥。
    with db.connect() as con:
        usage = [dict(cost_cny=r['cost'], **json.loads(r['data'])) for r in con.execute('SELECT cost,data FROM usage ORDER BY rowid DESC LIMIT 2')]
    result.update(model=llm.status()['model'], usage=usage, estimated_cost_cny=round(sum(r['cost_cny'] for r in usage), 8),
        total_project_estimated_cost_cny=llm.status()['spent_cny'], calls_in_script=llm.status()['calls'] - before['calls'],
        free_quota='用户声明有1M免费额度；此处为抵扣前估算，实际计费以平台为准')
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(success=True, entries=2, sum_amount_cents=4250, calls_in_script=result['calls_in_script'],
        estimated_cost_cny=result['estimated_cost_cny'], isolated_commit=True), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='用构造随记验证模型理解、补问、更正与确认入账')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--live', action='store_true', help='实际调用模型两次，计入本项目预算')
    group.add_argument('--draft-id', help='复用网页已实际生成的指定构造草稿，不新增API调用')
    args = parser.parse_args()
    validate(args.live, args.draft_id)
