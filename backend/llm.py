import json
import os
import httpx
from .storage import connect, uid, dumps, now


def pricing():
    try:
        inp=float(os.getenv('LLM_INPUT_CNY_PER_M','.15'))
        out=float(os.getenv('LLM_OUTPUT_CNY_PER_M','1.5'))
        if not (0<=inp<float('inf') and 0<=out<float('inf')):
            raise ValueError
    except (TypeError,ValueError) as exc:
        raise ValueError('请先按当前平台确认并填写输入、输出单价（元/百万tokens），再调用API') from exc
    return inp,out


def status():
    with connect() as c:
        cost=c.execute('SELECT COALESCE(SUM(cost),0) FROM usage').fetchone()[0]
        count=c.execute('SELECT COUNT(*) FROM usage').fetchone()[0]
    try:
        pricing();pricing_configured=True
    except ValueError:
        pricing_configured=False
    return dict(configured=bool(os.getenv('LLM_API_KEY')),model=os.getenv('LLM_MODEL','qwen-flash'),pricing_configured=pricing_configured,
        spent_cny=round(cost,6),budget_cny=float(os.getenv('LLM_BUDGET_CNY','5')),calls=count)


def call_json(messages, max_tokens=1600):
    if type(max_tokens) is not int or not 1 <= max_tokens <= 3200:
        raise ValueError("输出长度须在1至3200tokens内")
    key=os.getenv('LLM_API_KEY')
    if not key:raise ValueError('尚未配置本地 LLM_API_KEY')
    inp,out=pricing()
    # 用UTF-8字节数加协议余量保守预留，默认限制在32K计费档以内。
    input_upper=len(json.dumps(messages,ensure_ascii=False).encode('utf-8'))+1024
    if input_upper>int(os.getenv('LLM_MAX_INPUT_TOKENS','30000')):
        raise ValueError('本次输入超过当前计费档的长度限制，请缩短或分批处理')
    reserve=(input_upper*inp+max_tokens*out)/1e6
    request_id=uid()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        spent=c.execute('SELECT COALESCE(SUM(cost),0) FROM usage').fetchone()[0]
        if spent+reserve>float(os.getenv('LLM_BUDGET_CNY','5')):
            raise ValueError('已达到本项目API预算上限')
        c.execute('INSERT INTO usage VALUES(?,?,?)',(request_id,reserve,dumps(dict(status='reserved',time=now()))))
    model=os.getenv('LLM_MODEL','qwen-flash')
    try:
        payload=dict(model=model,messages=messages,max_tokens=max_tokens,temperature=.1,response_format={'type':'json_object'})
        thinking=os.getenv('LLM_ENABLE_THINKING')
        if thinking is not None:
            if thinking.lower() not in ['true','false']:raise ValueError('LLM_ENABLE_THINKING须为true或false')
            payload['enable_thinking']=thinking.lower()=='true'
        with httpx.Client(timeout=float(os.getenv('LLM_TIMEOUT_SECONDS','30'))) as client:
            response=client.post(os.getenv('LLM_BASE_URL','https://dashscope.aliyuncs.com/compatible-mode/v1').rstrip('/')+'/chat/completions',
                headers={'Authorization':'Bearer '+key},json=payload)
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
