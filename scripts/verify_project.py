import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

if __name__=='__main__':
    print('Project:',ROOT,flush=True)
    print('Interpreter:',sys.executable,flush=True)
    test=subprocess.run([sys.executable,'-m','pytest','-q','--tb=short'],cwd=ROOT)
    if test.returncode:raise SystemExit(test.returncode)
    metrics=json.loads((ROOT/'results/metrics.json').read_text(encoding='utf-8'))
    workflow=json.loads((ROOT/'results/workflow_evaluation.json').read_text(encoding='utf-8'))
    selected=next(m for m in metrics['classification'] if m['model']==metrics['selected'])
    full=next(m for m in workflow['ablations'] if m['variant']=='完整流程')
    print('Synthetic records:',metrics['rows'])
    print('Group-disjoint splits:',metrics['split_counts'])
    print('Selected by validation:',metrics['selected'])
    print('Classification Macro-F1:',round(selected['macro_f1'],4))
    print('Automatic link precision:',round(full['automatic_link_precision'],4))
    print('Automatic links:',full['automatic_link_count'])
    print('Duplicate accounting rate:',round(full['duplicate_accounting_rate'],4))
    print('Human review request rate:',round(full['review_request_rate'],4))
    print('All metrics are measured on clearly labeled synthetic data.')
