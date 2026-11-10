import json

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend import llm, storage as db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('BILL_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.setattr('backend.main.load_dotenv', lambda *a, **kw: None)
    with TestClient(app) as value: yield value


def entry(**kw):
    row = dict(date='2026-11-09', merchant='午饭', amount_yuan='28', direction='支出', kind='消费', evidence='昨天午饭二十八')
    row.update(kw)
    return row


def payload(**kw):
    body = dict(text='昨天午饭二十八，今天早餐还没写金额', reference_date='2026-11-10', allow_remote=True, synthetic=True)
    body.update(kw)
    return body


def model(monkeypatch, result):
    monkeypatch.setenv('LLM_API_KEY', 'test-placeholder')
    monkeypatch.setattr(llm, 'call_json', lambda *a, **kw: result)


def test_notes_consent_required_even_for_synthetic(client, monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'test-placeholder')
    def forbidden(*a, **kw): raise AssertionError('不应调用远端')
    monkeypatch.setattr(llm, 'call_json', forbidden)
    note = client.post('/api/notes/preview', json=payload(allow_remote=False)).json()
    assert note['mode'] == 'local' and note['items'][0]['amount_yuan'] is None
    assert not client.get('/api/ledger').json()['rows']


def test_notes_followup_preview_persistence_and_idempotent_commit(client, monkeypatch):
    model(monkeypatch, dict(items=[entry(platform='支付宝'), entry(date='2026-11-10', merchant='早餐', amount_yuan=None)], questions=['早餐花了多少？']))
    first = client.post('/api/notes/preview', json=payload()).json()
    assert first['mode'] == 'api' and first['items'][0]['account'] == '我的支付宝'
    assert first['items'][0]['amount_yuan'] == '28.00'
    assert not client.get('/api/ledger').json()['rows']
    assert client.get('/api/notes/' + first['id']).json() == first
    assert client.post('/api/notes/' + first['id'] + '/commit', json=dict(revision=1, items=first['items'])).status_code == 400
    corrected = first['items']
    corrected[0]['merchant'] = '午餐面馆'
    def follow(messages, **kw):
        context = json.loads(messages[1]['content'])
        assert context['reference_date'] == '2026-11-10'
        assert context['previous_items'][0]['merchant'] == '午餐面馆'
        assert all('account' not in r for r in context['previous_items'])
        assert len(context['input']) == 2
        return dict(items=[dict(corrected[0], amount_yuan='30'), dict(corrected[1], amount_yuan='12.50')], questions=[])
    monkeypatch.setattr(llm, 'call_json', follow)
    second = client.post('/api/notes/preview', json=payload(draft_id=first['id'], revision=1, items=corrected, text='早餐十二块五，午饭改为三十')).json()
    assert second['revision'] == 2 and not second['questions']
    assert [i['id'] for i in second['items']] == [i['id'] for i in first['items']]
    assert client.post('/api/notes/' + first['id'] + '/commit', json=dict(revision=1, items=first['items'])).status_code == 409
    body = dict(revision=2, items=second['items'])
    response = client.post('/api/notes/' + first['id'] + '/commit', json=body)
    assert response.status_code == 200
    job = response.json()
    assert job['imported'] == 2
    assert client.post('/api/notes/' + first['id'] + '/commit', json=body).json()['id'] == job['id']
    rows = client.get('/api/ledger').json()['rows']
    assert len(rows) == 2 and sum(r['amount'] for r in rows) == 4250
    assert all(r['raw']['time_precision'] == 'day' and r['time'].endswith('00:00:00') for r in rows)
    assert all(r['raw']['note_messages'][0]['text'] == payload()['text'] for r in rows)
    assert client.post('/api/jobs/' + job['id'] + '/run').status_code == 200
    assert client.get('/api/notes/' + first['id']).json()['status'] == 'committed'


def test_notes_timeout_keeps_text_and_no_ledger_write(client, monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'test-placeholder')
    def timeout(*a, **kw): raise TimeoutError()
    monkeypatch.setattr(llm, 'call_json', timeout)
    note = client.post('/api/notes/preview', json=payload()).json()
    assert note['mode'] == 'local' and '未自动入账' in note['warning']
    assert note['messages'][0]['text'] == payload()['text']
    assert not client.get('/api/ledger').json()['rows']


@pytest.mark.parametrize('amount', ['-1', '1.001', 'NaN', True, 'Infinity'])
def test_notes_invalid_model_amount_never_commits(client, monkeypatch, amount):
    model(monkeypatch, dict(items=[entry(amount_yuan=amount)]))
    note = client.post('/api/notes/preview', json=payload()).json()
    assert note['mode'] == 'local'
    assert not client.get('/api/ledger').json()['rows']


def test_notes_local_manual_completion_and_refund_validation(client):
    note = client.post('/api/notes/preview', json=payload(allow_remote=False)).json()
    row = dict(note['items'][0], date='2026-11-10', merchant='退款', amount_yuan='8.10', direction='支出', kind='退款')
    url = '/api/notes/' + note['id'] + '/commit'
    assert client.post(url, json=dict(revision=1, items=[row])).status_code == 400
    row['direction'] = '收入'
    assert client.post(url, json=dict(revision=1, items=[row], acknowledge_questions=True)).status_code == 200
    assert client.get('/api/ledger').json()['rows'][0]['amount'] == 810


def test_notes_stale_followup_and_unknown_ids_rejected(client, monkeypatch):
    model(monkeypatch, dict(items=[entry()]))
    first = client.post('/api/notes/preview', json=payload()).json()
    second = client.post('/api/notes/preview', json=payload(draft_id=first['id'], revision=1, text='确认午饭28')).json()
    assert second['revision'] == 2
    assert client.post('/api/notes/preview', json=payload(draft_id=first['id'], revision=1)).status_code == 409
    bad = dict(second['items'][0], id='invented-id')
    assert client.post('/api/notes/' + first['id'] + '/commit', json=dict(revision=2, items=[bad])).status_code == 400
    assert client.post('/api/notes/' + first['id'] + '/commit', json=dict(revision=2, items=second['items'] * 2)).status_code == 400


def test_notes_output_budget_reservation_uses_requested_limit(client, monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'test-placeholder')
    monkeypatch.setenv('LLM_INPUT_CNY_PER_M', '0')
    monkeypatch.setenv('LLM_OUTPUT_CNY_PER_M', '1')
    monkeypatch.setenv('LLM_BUDGET_CNY', '0.002')
    with pytest.raises(ValueError, match='预算'):
        llm.call_json([dict(role='user', content='构造样例')], max_tokens=3200)
    assert llm.status()['calls'] == 0


def test_notes_questions_without_partial_row_still_block_save(client, monkeypatch):
    model(monkeypatch, dict(items=[entry()], questions=['早餐金额是多少？']))
    draft = client.post('/api/notes/preview', json=payload()).json()
    url = '/api/notes/' + draft['id'] + '/commit'
    body = dict(revision=1, items=draft['items'])
    assert client.post(url, json=body).status_code == 400
    assert not client.get('/api/ledger').json()['rows']
    body['acknowledge_questions'] = True
    assert client.post(url, json=body).status_code == 200
    assert db.get('notes', draft['id'])['acknowledge_questions'] is True
