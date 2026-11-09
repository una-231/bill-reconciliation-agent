import sqlite3
import threading
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from . import storage as db
from .quality import inspect_records
from .reconcile import analyze, summary

LOCK=threading.RLock()


class State(TypedDict, total=False):
    job_id:str
    stage:str


def update(job_id,stage,message):
    job=db.get('jobs',job_id)
    job['status']=stage
    if not job['trace'] or job['trace'][-1]['message']!=message:
        job['trace'].append(dict(stage=stage,message=message,time=db.now()))
    db.save('jobs',job)


def quality_node(state):
    job=db.get('jobs',state['job_id'])
    job['quality']=inspect_records(db.all_items('transactions',job['id']))
    db.save('jobs',job)
    update(job['id'],'checking','数据体检完成，开始分类、匹配和历史异常检查')
    return {'stage':'checking'}


def reconcile_node(state):
    job_id=state['job_id']
    current=db.all_items('transactions',job_id)
    current_ids={r['id'] for r in current}
    all_rows=db.all_items('transactions')
    rows,reviews=analyze(all_rows,job_id)
    # 已有账本只提供匹配上下文，新的问题仅归属当前导入批次。
    for r in rows:
        if r['id'] in current_ids:
            db.save('transactions',r,job_id)
    for q in reviews:
        if q['tx_id'] in current_ids:db.save('reviews',q)
    update(job_id,'review','已生成核对建议，等待你确认不确定记录')
    return {'stage':'review'}


def review_node(state):
    pending=[q for q in db.all_items('reviews',state['job_id']) if q['status']=='open']
    if pending:
        interrupt(dict(kind='bill_review',job_id=state['job_id'],count=len(pending),message='请在待核对队列逐项确认'))
    return {'stage':'complete'}


def final_node(state):
    update(state['job_id'],'complete','本批核对完成，可以导出账本和修改记录')
    return {'stage':'complete'}


def run(job_id,resume=False):
    with LOCK:
        with SqliteSaver.from_conn_string(str(db.data_dir()/'checkpoints.sqlite')) as saver:
            graph=StateGraph(State)
            graph.add_node('quality',quality_node);graph.add_node('reconcile',reconcile_node)
            graph.add_node('review',review_node);graph.add_node('finish',final_node)
            graph.add_edge(START,'quality');graph.add_edge('quality','reconcile');graph.add_edge('reconcile','review')
            graph.add_edge('review','finish');graph.add_edge('finish',END)
            compiled=graph.compile(checkpointer=saver)
            config={'configurable':{'thread_id':job_id},'recursion_limit':8}
            if resume and not compiled.get_state(config).next:
                # 撤销后重新核对：从已结束的检查点重新进入最终提交节点。
                compiled.update_state(config,{'stage':'complete'},as_node='review')
                return compiled.invoke(None,config)
            return compiled.invoke(Command(resume=True) if resume else {'job_id':job_id},config)
