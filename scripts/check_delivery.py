import json
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def verify():
    required=['README.md','LICENSE','requirements-lock.txt','frontend/package-lock.json','run.py','start.ps1',
        'data/synthetic.json','data/demo.json','data/demo_微信.csv','data/demo_支付宝.csv','data/demo_screenshot.png',
        'docs/DEMO.md','docs/EVALUATION.md','docs/COMPONENTS.md','docs/demo_核对后账本.xlsx',
        'skills/bill-data-quality/SKILL.md','third_party/csv-data-summarizer/SKILL.md',
        'results/metrics.json','results/workflow_evaluation.json','results/test_verification.json',
        'results/demo_replay.json','results/real_sample_compatibility_summary.json']
    missing=[p for p in required if not (ROOT/p).is_file()]
    if missing:raise ValueError('缺少交付文件：'+', '.join(missing))
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf-8').strip('\0').split('\0')
    forbidden=[p for p in tracked if p.startswith(('data/private/','提交材料/','工作文件/','.venv/','node_modules/'))
        or p=='.env' or (p.startswith('runtime/') and p!='runtime/.gitkeep')
        or p.lower().endswith(('.docx','.pdf','.sqlite','.joblib'))]
    if forbidden:raise ValueError('索引包含本地私有或报告文件：'+', '.join(forbidden))
    for path in ['.env','data/private/example.png','runtime/private.sqlite','提交材料/report.pdf']:
        if subprocess.run(['git','check-ignore','--quiet',path],cwd=ROOT).returncode:
            raise ValueError('缺少忽略规则：'+path)
    broken=[];secret_files=[]
    for relative in tracked:
        p=ROOT/relative
        if p.suffix.lower() not in ['.md','.py','.ts','.tsx','.json','.txt','.yml','.example']:continue
        text=p.read_text(encoding='utf-8-sig')
        if re.search(r'\bsk-[A-Za-z0-9_-]{24,}',text):secret_files.append(relative)
        if p.suffix=='.md' and not relative.startswith('third_party/'):
            for target in re.findall(r'\]\(([^\s)]+)\)',text):
                if '://' in target or target.startswith(('#','mailto:')):continue
                target=target.split('#')[0]
                if target and not (p.parent/target).exists():broken.append(dict(file=relative,target=target))
    if secret_files:raise ValueError('疑似密钥文件：'+', '.join(secret_files))
    if broken:raise ValueError('文档链接不存在：'+json.dumps(broken,ensure_ascii=False))
    data=json.loads((ROOT/'data/synthetic.json').read_text(encoding='utf-8'))
    demo=json.loads((ROOT/'results/demo_replay.json').read_text(encoding='utf-8'))
    tests=json.loads((ROOT/'results/test_verification.json').read_text(encoding='utf-8'))
    assert len(data)==3000 and demo['summary']['count']==65
    assert demo['summary']['pending']==0 and demo['summary']['net']==664800
    assert tests['failed']==0
    result=dict(verified_on='2026-11-25',required_files_checked=len(required),tracked_files_checked=len(tracked),
        missing_files=missing,broken_local_links=broken,private_or_report_files_tracked=forbidden,
        secret_signature_matches=secret_files,private_paths_ignored=True,
        local_links_scope='项目编写文档；上游原文保持原样，其缺少独立LICENSE的情况已在组件清单披露',
        synthetic_rows=3000,demo_rows=65,demo_net_cents=664800,regression_tests=tests['passed'])
    (ROOT/'results/delivery_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return result


if __name__=='__main__':verify()
