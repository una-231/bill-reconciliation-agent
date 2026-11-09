import hashlib
import json
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
repo='coffeefuelbump/csv-data-summarizer-claude-skill'


def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'bill-agent-course-project'})
    return urllib.request.urlopen(req,timeout=30).read()


if __name__=='__main__':
    commit=json.loads(fetch(f'https://api.github.com/repos/{repo}/commits/main'))['sha']
    target=ROOT/'third_party/csv-data-summarizer';target.mkdir(parents=True,exist_ok=True)
    files={}
    for name in ['SKILL.md','analyze.py','README.md','requirements.txt']:
        data=fetch(f'https://raw.githubusercontent.com/{repo}/{commit}/{name}')
        (target/name).write_bytes(data)
        files[name]=hashlib.sha256(data).hexdigest()
    manifest=dict(repository=f'https://github.com/{repo}',commit=commit,declared_version='2.1.0',
        license='MIT as declared in upstream README; upstream has no separate LICENSE file',sha256=files,
        execution='原始脚本仅审阅，不在Agent中直接执行',adaptation='skills/bill-data-quality + backend/quality.py，重写领域检查与结构化输出')
    (target/'PROVENANCE.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
