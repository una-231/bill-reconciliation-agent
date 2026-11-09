import json
import os
import httpx
from .storage import connect, uid, dumps, now


def status():
    with connect() as c:
        cost=c.execute('SELECT COALESCE(SUM(cost),0) FROM usage').fetchone()[0]
        count=c.execute('SELECT COUNT(*) FROM usage').fetchone()[0]
    return dict(configured=bool(os.getenv('LLM_API_KEY')),model=os.getenv('LLM_MODEL','qwen-flash'),
        spent_cny=round(cost,6),budget_cny=float(os.getenv('LLM_BUDGET_CNY','5')),calls=count)


def call_json(messages):
    key=os.getenv('LLM_API_KEY')
    if not key:raise ValueError('尚未配置本地 LLM_API_KEY')
    inp=float(os.getenv('LLM_INPUT_CNY_PER_M','.15'));out=float(os.getenv('LLM_OUTPUT_CNY_PER_M','1.5'))
    # 中文字符按最多两 tokens 预留，避免最后一次调用越过本地预算。
    reserve=(len(json.dumps(messages,ensure_ascii=False))*2*inp+1600*out)/1e6
    request_id=uid()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        spent=c.execute('SELECT COALESCE(SUM(cost),0) FROM usage').fetchone()[0]
        if spent+reserve>float(os.getenv('LLM_BUDGET_CNY','5')):
            raise ValueError('已达到本项目API预算上限')
        c.execute('INSERT INTO usage VALUES(?,?,?)',(request_id,reserve,dumps(dict(status='reserved',time=now()))))
    model=os.getenv('LLM_MODEL','qwen-flash')
    try:
        with httpx.Client(timeout=float(os.getenv('LLM_TIMEOUT_SECONDS','30'))) as client:
            response=client.post(os.getenv('LLM_BASE_URL','https://dashscope.aliyuncs.com/compatible-mode/v1').rstrip('/')+'/chat/completions',
                headers={'Authorization':'Bearer '+key},json=dict(model=model,messages=messages,max_tokens=1600,temperature=.1,response_format={'type':'json_object'}))
        if response.status_code>=400:
            raise ValueError(f'模型服务返回 HTTP {response.status_code}，请检查本地配置和额度')
        result=response.json();usage=result.get('usage',{})
        actual=(usage.get('prompt_tokens',0)*inp+usage.get('completion_tokens',0)*out)/1e6 if usage else reserve
        with connect() as c:
            c.execute('UPDATE usage SET cost=?,data=? WHERE id=?',(actual,dumps(dict(model=result.get('model',model),usage=usage,status='completed',time=now())),request_id))
        return json.loads(result['choices'][0]['message']['content'])
    except Exception:
        # 请求可能已在服务端执行，失败时保留预留金额，不假定免费。
        with connect() as c:
            c.execute('UPDATE usage SET data=? WHERE id=?',(dumps(dict(model=model,status='failed_reserved',time=now())),request_id))
        raise
