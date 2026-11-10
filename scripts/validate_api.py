import argparse
import json
import sys
import time
import os
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv


def validate():
    load_dotenv(ROOT/'.env',override=True)
    from backend import storage as db,llm
    db.init()
    before=llm.status()
    with db.connect() as c:
        previous_ids={r[0] for r in c.execute('SELECT id FROM usage').fetchall()}
    cases=[]
    tests=[dict(name='结构化净支出计算',messages=[
        {'role':'system','content':'你是构造账单测试助手。仅返回合法JSON，字段为 ok 布尔值、net_cents 整数，不要输出其他内容。金额单位为分。'},
        {'role':'user','content':'以下账单为明确构造数据：支出10000分，已匹配退款2000分。请计算净支出。'}],expected_net=8000)]
    for case in tests:
        started=time.perf_counter()
        try:
            result=llm.call_json(case['messages'])
            passed=result.get('net_cents')==case['expected_net'] and result.get('ok') is True
            cases.append(dict(name=case['name'],success=passed,response=result,seconds=round(time.perf_counter()-started,3)))
        except Exception as exc:
            cases.append(dict(name=case['name'],success=False,error=str(exc),seconds=round(time.perf_counter()-started,3)))
    # 后端聊天只发送问题和脱敏汇总，不向模型发送真实账单明细。
    with httpx.Client(base_url='http://127.0.0.1:8000',trust_env=False,timeout=45) as client:
        for name,prompt in [('核对问题问答','请概括当前构造账本，并告诉我哪些问题需要人工确认。不要编造未给出的明细。'),('退款口径问答','当前账本中，已匹配退款应如何影响月度净支出？请依据工具数据回答。')]:
            started=time.perf_counter()
            try:
                response=client.post('/api/chat',json=dict(message=prompt,allow_remote=True))
                response.raise_for_status();r=response.json()
                cases.append(dict(name=name,success=r.get('mode')=='api' and bool(r.get('reply')),mode=r.get('mode'),reply=r.get('reply'),tools=r.get('tools'),seconds=round(time.perf_counter()-started,3)))
            except Exception as exc:cases.append(dict(name=name,success=False,error=str(exc),seconds=round(time.perf_counter()-started,3)))
    after=llm.status()
    with db.connect() as c:
        usage=[dict(cost_cny=r['cost'],**json.loads(r['data'])) for r in c.execute('SELECT id,cost,data FROM usage').fetchall() if r['id'] not in previous_ids]
    result=dict(success=all(c['success'] for c in cases),model=after['model'],cases=cases,usage=usage,
        calls_in_run=after['calls']-before['calls'],estimated_cost_cny=round(after['spent_cny']-before['spent_cny'],8),
        total_project_estimated_cost_cny=after['spent_cny'],
        pricing=dict(input_cny_per_million=float(os.environ['LLM_INPUT_CNY_PER_M']),output_cny_per_million=float(os.environ['LLM_OUTPUT_CNY_PER_M']),source='本地配置，本次用户提供平台计费截图，输入<=32K档'),
        enable_thinking=os.getenv('LLM_ENABLE_THINKING'),
        free_quota='用户声明有1M免费额度，实际抵扣由平台账单确认，以下费用为抵扣前保守估算',
        data_source='明确构造账单与匿名汇总，不含原始真实账单')
    (ROOT/'results/api_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='真实API验证，仅使用构造数据，会消耗少量tokens')
    parser.add_argument('--live',action='store_true',help='执行实际接口调用')
    args=parser.parse_args()
    if not args.live:parser.error('请明确使用 --live 执行真实调用；密钥仅从本机.env读取')
    raise SystemExit(0 if validate()['success'] else 1)
