import copy

import pytest
from fastapi.testclient import TestClient

from backend import storage as db
from backend.intake import parse_screenshot_list
from backend.main import app


TEXT = '2026年11月\n青禾面馆 -18.00\n11月19日12:10\n春山商店 88.8-\n11月18日12:00\n云杉药房 -6.00'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('BILL_DATA_DIR', str(tmp_path))
    monkeypatch.setattr('backend.main.load_dotenv', lambda *a, **kw: None)
    def parse(content, filename, platform, account, reference_date=None):
        rows, errors = parse_screenshot_list(TEXT, content, filename, platform, account, reference_date)
        return rows, errors, TEXT, 0.8
    monkeypatch.setattr('backend.main.parse_image', parse)
    with TestClient(app) as c: yield c


def upload(c, **data):
    response = c.post('/api/import/files', data=dict(platform='微信', account='我的微信', defer_images='true', **data),
        files=[('files', ('constructed.jpg', b'constructed-image-bytes', 'image/jpeg'))])
    response.raise_for_status()
    return response.json()


def save(c, job, entries):
    return c.patch(f'/api/jobs/{job["id"]}/screenshots', json=dict(
        revision=job['screenshot_revision'], items=entries))


def checked(draft, **patch):
    fields = dict(draft['fields'], **patch)
    return dict(id=draft['id'], fields=fields, reviewed=True)


def commit(c, job, ids=None):
    return c.post(f'/api/jobs/{job["id"]}/screenshots/commit', json=dict(
        revision=job['screenshot_revision'], ids=ids or [job['screenshot_drafts'][0]['id']]))


def test_screenshot_preview_keeps_all_rows_out_of_ledger_and_original_local(client):
    job = upload(client)
    assert job['imported'] == 0 and job['status'] == 'image_review'
    drafts = job['screenshot_drafts']
    assert len(drafts) == 3 and len(job['errors']) == 2
    assert drafts[1]['fields']['amount_yuan'] is None and drafts[2]['fields']['date'] is None
    assert drafts[1]['fields']['date'] == '2026-11-18'
    assert drafts[1]['fields']['merchant'] == '春山商店'
    assert not client.get('/api/ledger').json()['rows']
    assert client.get(f'/api/jobs/{job["id"]}').json()['screenshot_drafts'] == drafts
    image = client.get(f'/api/jobs/{job["id"]}/images/{job["images"][0]["token"]}')
    assert image.content == b'constructed-image-bytes' and image.headers['cache-control'] == 'no-store'
    assert client.get(f'/api/jobs/{job["id"]}/images/' + 'a' * 64 + '.jpg').status_code == 404


def test_draft_edits_persist_conflict_and_do_not_change_ledger(client):
    job = upload(client)
    entry = checked(job['screenshot_drafts'][0], amount_yuan='19.50')
    saved = save(client, job, [entry])
    assert saved.status_code == 200
    updated = saved.json()
    assert updated['screenshot_drafts'][0]['fields']['amount_yuan'] == '19.50'
    assert updated['screenshot_drafts'][0]['original_fields']['amount_yuan'] == '18.00'
    assert save(client, job, [entry]).status_code == 409
    assert not client.get('/api/ledger').json()['rows']


def test_commit_requires_explicit_field_confirmation_and_is_idempotent(client):
    job = upload(client)
    assert commit(client, job).status_code == 400
    updated = save(client, job, [checked(job['screenshot_drafts'][0], amount_yuan='19.50')]).json()
    child = commit(client, updated).json()
    assert child['imported'] == 1
    assert commit(client, updated).json()['id'] == child['id']
    assert client.post(f'/api/jobs/{child["id"]}/run').status_code == 200
    row = client.get('/api/ledger').json()['rows'][0]
    assert row['amount'] == 1950
    assert row['raw']['screenshot_confirmation']['original_fields']['amount_yuan'] == '18.00'
    assert row['raw']['screenshot_confirmation']['confirmed_fields']['amount_yuan'] == '19.50'
    assert row['sources'][0]['ocr'] is True
    assert row['ocr_fields_confirmed'] and row['ocr_review_required']
    assert not any(q['kind'] == 'ocr' for q in client.get('/api/reviews').json())


@pytest.mark.parametrize('patch', [dict(date=None), dict(time=None), dict(amount_yuan=None),
    dict(time='29:00'), dict(merchant=' '), dict(kind='退款', direction='支出')])
def test_missing_or_inconsistent_fields_cannot_be_confirmed(client, patch):
    job = upload(client)
    response = save(client, job, [checked(job['screenshot_drafts'][0], **patch)])
    assert response.status_code == 400
    assert client.get(f'/api/jobs/{job["id"]}').json()['screenshot_revision'] == 1
    assert not client.get('/api/ledger').json()['rows']


def test_held_rows_can_be_completed_in_a_later_batch(client):
    job = upload(client)
    first, broken, cropped = job['screenshot_drafts']
    saved = save(client, job, [checked(first), dict(id=cropped['id'], fields=cropped['fields'], held=True)]).json()
    commit(client, saved).raise_for_status()
    saved = client.get(f'/api/jobs/{job["id"]}').json()
    assert saved['screenshot_drafts'][2]['status'] == 'held'
    fixed = checked(cropped, date='2026-11-18', time='13:15')
    saved = save(client, saved, [fixed]).json()
    assert commit(client, saved, [cropped['id']]).json()['imported'] == 1
    assert len(client.get('/api/ledger').json()['rows']) == 2


def test_reimport_does_not_duplicate_confirmed_screenshot_record(client):
    job = upload(client)
    saved = save(client, job, [checked(job['screenshot_drafts'][0])]).json()
    commit(client, saved).raise_for_status()
    second = upload(client)
    saved = save(client, second, [checked(second['screenshot_drafts'][0])]).json()
    child = commit(client, saved).json()
    assert child['imported'] == 0 and child['reimported'] == 1
    assert len(client.get('/api/ledger').json()['rows']) == 1


def test_screenshot_edits_are_atomic_and_cannot_inject_or_modify_imported_rows(client):
    job = upload(client)
    unknown = copy.deepcopy(checked(job['screenshot_drafts'][0]))
    unknown['id'] = unknown['fields']['id'] = 'unknown'
    response = save(client, job, [checked(job['screenshot_drafts'][0], amount_yuan='25'), unknown])
    assert response.status_code == 400
    assert client.get(f'/api/jobs/{job["id"]}').json()['screenshot_drafts'][0]['fields']['amount_yuan'] == '18.00'
    updated = save(client, job, [checked(job['screenshot_drafts'][0])]).json()
    commit(client, updated).raise_for_status()
    updated = client.get(f'/api/jobs/{job["id"]}').json()
    assert save(client, updated, [checked(job['screenshot_drafts'][0], amount_yuan='25')]).status_code == 400


def test_same_image_twice_in_one_upload_has_single_draft_set(client):
    data = dict(platform='微信', account='我的微信', defer_images='true')
    files = [('files', ('constructed.jpg', b'constructed-image-bytes', 'image/jpeg'))] * 2
    job = client.post('/api/import/files', data=data, files=files).json()
    assert len(job['screenshot_drafts']) == 3


def test_model_config_reload_preserves_explicit_database_directory(tmp_path,monkeypatch):
    from backend import main
    isolated=tmp_path/'isolated'
    monkeypatch.setenv('BILL_DATA_DIR',str(isolated))
    monkeypatch.setattr(main,'ROOT',tmp_path)
    (tmp_path/'.env').write_text('BILL_DATA_DIR=another-ledger\nLLM_MODEL=test-model\n',encoding='utf-8')
    monkeypatch.setenv('LLM_MODEL','previous')
    with TestClient(app) as c:
        assert c.get('/api/config').json()['llm']['model']=='test-model'
        assert db.data_dir()==isolated
        assert not (tmp_path/'another-ledger').exists()
