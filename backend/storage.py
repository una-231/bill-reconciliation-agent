import json
import os
import sqlite3
import uuid
import threading
from functools import wraps
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_local=threading.local()


def data_dir():
    p = Path(os.getenv('BILL_DATA_DIR', str(ROOT / 'runtime')))
    p.mkdir(parents=True, exist_ok=True)
    return p


def uid():
    return uuid.uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(x):
    return json.dumps(x, ensure_ascii=False, allow_nan=False)


@contextmanager
def connect():
    active=getattr(_local,'connection',None)
    if active is not None:
        yield active
        return
    con = sqlite3.connect(data_dir() / 'ledger.sqlite', timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


@contextmanager
def atomic():
    if getattr(_local,'connection',None) is not None:
        yield
        return
    with connect() as c:
        _local.connection=c
        try:
            c.execute('BEGIN IMMEDIATE')
            yield
        finally:
            _local.connection=None


def transactional(fn):
    @wraps(fn)
    def wrapped(*args,**kwargs):
        with atomic():return fn(*args,**kwargs)
    return wrapped


def init():
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS transactions(id TEXT PRIMARY KEY, job_id TEXT, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY, job_id TEXT, tx_id TEXT, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, job_id TEXT, tx_id TEXT, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY, tx_id TEXT, text TEXT, category TEXT);
        CREATE TABLE IF NOT EXISTS usage(id TEXT PRIMARY KEY, cost REAL, data TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, data TEXT);
        ''')


def save(table, item, job_id=None, tx_id=None):
    if table not in {'jobs', 'notes', 'transactions', 'reviews', 'events'}:
        raise ValueError('未知数据表')
    columns = ['id', 'data']
    values = [item['id'], dumps(item)]
    if table not in {'jobs', 'notes'}:
        columns += ['job_id']
        values += [job_id or item.get('job_id')]
    if table in {'reviews', 'events'}:
        columns += ['tx_id']
        values += [tx_id or item.get('tx_id')]
    with connect() as c:
        c.execute(f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)


def get(table, id):
    if table not in {'jobs', 'notes', 'transactions', 'reviews', 'events'}:
        raise ValueError('未知数据表')
    with connect() as c:
        row = c.execute(f'SELECT data FROM {table} WHERE id=?', (id,)).fetchone()
    return json.loads(row['data']) if row else None


def all_items(table, job_id=None):
    if table not in {'jobs', 'notes', 'transactions', 'reviews', 'events'}:
        raise ValueError('未知数据表')
    with connect() as c:
        rows = c.execute(f'SELECT data FROM {table}' + (' WHERE job_id=?' if job_id else ''), (job_id,) if job_id else ()).fetchall()
    return [json.loads(r['data']) for r in rows]


def event(job_id, tx_id, before, after, reason):
    e = dict(id=uid(), job_id=job_id, tx_id=tx_id, before=before, after=after, reason=reason, time=now(), undone=False)
    save('events', e)
    return e
