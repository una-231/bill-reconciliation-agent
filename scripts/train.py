import json
import sys
import time
import platform
from pathlib import Path
import random
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.pipeline import make_pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import MultinomialNB
from sklearn.metrics import classification_report, f1_score, precision_recall_fscore_support, confusion_matrix
from backend.ml import text_of, candidates, pair_features, anomaly_alerts
from backend.schema import CATEGORIES
from scripts.generate_data import generate, CAT_WORDS


def train():
    start=time.perf_counter()
    rows=json.loads((ROOT/'data/synthetic.json').read_text(encoding='utf-8')) if (ROOT/'data/synthetic.json').exists() else generate()
    splits={s:[r for r in rows if r['split']==s] for s in ['train','validation','test']}
    groups={s:set(r['group'] for r in rs) for s,rs in splits.items()}
    assert not groups['train']&groups['test'] and not groups['validation']&groups['test'] and not groups['train']&groups['validation']
    expenses={s:[r for r in rs if r['id'].startswith('SYN')] for s,rs in splits.items()}
    train_rows=expenses['train']
    feedback_count=0
    try:
        from backend.storage import init,connect
        init()
        with connect() as con:
            feedback=con.execute('SELECT text,category FROM feedback').fetchall()
        for f in feedback:
            train_rows=train_rows+[dict(merchant='',description=f['text'],truth_category=f['category'])]
        feedback_count=len(feedback)
    except Exception:
        pass
    x=[text_of(r) for r in train_rows]; y=[r['truth_category'] for r in train_rows]
    vx=[text_of(r) for r in expenses['validation']]; vy=[r['truth_category'] for r in expenses['validation']]
    tx=[text_of(r) for r in expenses['test']]; ty=[r['truth_category'] for r in expenses['test']]
    models=[]
    for name,clf in [('NB',MultinomialNB(alpha=.3)),('Logistic-C0.5',LogisticRegression(C=.5,max_iter=1000)),('Logistic-C2',LogisticRegression(C=2,max_iter=1000)),('Logistic-C8',LogisticRegression(C=8,max_iter=1000))]:
        model=make_pipeline(TfidfVectorizer(analyzer='char',ngram_range=(2,4),min_df=2,sublinear_tf=True),clf)
        model.fit(x,y)
        models.append((f1_score(vy,model.predict(vx),average='macro'),name,model))
    _,selected,model=max(models,key=lambda item:item[0])
    vp=model.predict_proba(vx)
    threshold=1.01
    for t in np.arange(.4,.991,.01):
        keep=vp.max(axis=1)>=t
        if keep.sum()>=10 and np.mean(model.classes_[vp[keep].argmax(axis=1)]==np.array(vy)[keep])>=.97:
            threshold=float(round(t,2));break
    rng=random.Random(42)
    def make_pairs(rs,sample_negatives=True):
        features=[];labels=[];ids=[]
        for a in rs:
            cs=candidates(a,rs)
            def relation(b):
                if b['id']==a.get('truth_link'):return a['truth_relation']
                if b.get('truth_relation')=='duplicate' and b.get('truth_link')==a['id']:return 'duplicate'
                return 'none'
            positive=[b for b in cs if relation(b)!='none']
            negatives=[b for b in cs if relation(b)=='none']
            for b in positive+(rng.sample(negatives,min(len(negatives),8)) if sample_negatives else negatives):
                label=relation(b)
                features.append(pair_features(a,b));labels.append(label);ids.append((a['id'],b['id']))
        return features,labels,ids
    xf,yf,_=make_pairs(splits['train'])
    matcher=LogisticRegression(C=5,max_iter=1500,class_weight='balanced').fit(xf,yf)
    vxf,vyf,_=make_pairs(splits['validation'],sample_negatives=False)
    probs=matcher.predict_proba(vxf)
    match_thresholds={}
    for kind in ['refund','transfer','duplicate']:
        col=list(matcher.classes_).index(kind)
        threshold_kind=1.01
        for t in np.arange(.5,.991,.01):
            keep=probs[:,col]>=t
            if keep.sum()>=3 and np.mean(np.array(vyf)[keep]==kind)>=.95:
                threshold_kind=float(round(t,2));break
        match_thresholds[kind]=threshold_kind
    version=time.strftime('%Y%m%d-%H%M%S')
    b=dict(classifier=model,matcher=matcher,category_threshold=threshold,match_thresholds=match_thresholds,
        selected=selected,version=version,feedback_count=feedback_count)
    (ROOT/'models').mkdir(exist_ok=True)
    joblib.dump(b,ROOT/'models/active.joblib')
    joblib.dump(b,ROOT/f'models/{version}.joblib')
    def keyword(text):
        for cat,words in CAT_WORDS.items():
            if any(w[:2] in text for w in words):return cat
        return '其他'
    metrics=[]
    baselines=[('多数类',[Counter(y).most_common(1)[0][0]]*len(ty)),('关键词规则',[keyword(t) for t in tx])]
    baselines += [(name,m.predict(tx)) for _,name,m in models]
    for name,pred in baselines:
        metrics.append(dict(model=name,macro_f1=f1_score(ty,pred,average='macro'),accuracy=float(np.mean(np.array(ty)==pred))))
    pred=model.predict(tx); confidence=model.predict_proba(tx).max(axis=1)
    report=classification_report(ty,pred,output_dict=True,zero_division=0)
    errors=[dict(id=r['id'],text=text_of(r),truth=t,prediction=str(p),confidence=float(c)) for r,t,p,c in zip(expenses['test'],ty,pred,confidence) if t!=p]
    eval_pairs={}; candidate_stats={}
    for kind in ['refund','transfer','duplicate']:
        truth=[]; predicted=[]; scores=[]; total=0;recall_count=0
        for a in splits['test']:
            cs=candidates(a,splits['test'])
            if a.get('truth_relation')==kind:
                total+=1;recall_count+=any(b['id']==a.get('truth_link') for b in cs)
            if not cs:continue
            ps=matcher.predict_proba([pair_features(a,b) for b in cs])[:,list(matcher.classes_).index(kind)]
            for b,p in zip(cs,ps):
                truth.append((a.get('truth_relation')==kind and b['id']==a.get('truth_link')) or (kind=='duplicate' and b.get('truth_relation')=='duplicate' and b.get('truth_link')==a['id']))
                predicted.append(p>=match_thresholds[kind]);scores.append(float(p))
        pr,re,f1,_=precision_recall_fscore_support(truth,predicted,average='binary',zero_division=0)
        eval_pairs[kind]=dict(precision=float(pr),recall=float(re),f1=float(f1),candidate_recall=recall_count/max(total,1),positive_records=total,pairs=len(truth),threshold=match_thresholds[kind])
    alerts=anomaly_alerts(splits['test'])
    anrows=[r for r in splits['test'] if r['id'].startswith('SYN') and r['time'][:7]>'2026-04']
    apr,are,af,_=precision_recall_fscore_support([r['truth_anomaly'] for r in anrows],[r['id'] in alerts for r in anrows],average='binary',zero_division=0)
    result=dict(seed=20261110,rows=len(rows),split_counts={k:len(v) for k,v in splits.items()},group_disjoint=True,
        selected=selected,validation_scores={name:score for score,name,m in models},category_threshold=threshold,
        classification=metrics,per_category=report,classification_coverage=float(np.mean(confidence>=threshold)),
        classification_auto_precision=float(np.mean(np.array(ty)[confidence>=threshold]==pred[confidence>=threshold])) if np.any(confidence>=threshold) else None,
        matching=eval_pairs,anomaly=dict(precision=float(apr),recall=float(are),f1=float(af),evaluated=len(anrows),note='四月冷启动不计入异常指标；仅用此前月份拟合'),
        model_version=version,feedback_count=feedback_count,seconds=time.perf_counter()-start,
        environment=dict(python=platform.python_version(),sklearn=sklearn.__version__),
        limitations=['有限模板构造数据，不能推断真实账单效果','真实接口与真实账单验证需要用户配置及授权样例'])
    (ROOT/'results').mkdir(exist_ok=True)
    (ROOT/'results/metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'results/classification_errors.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(metrics).to_csv(ROOT/'results/classification.csv',index=False,encoding='utf-8-sig')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    fig,ax=plt.subplots(figsize=(8,4.5)); ax.barh([m['model'] for m in metrics],[m['macro_f1'] for m in metrics],color='#247466');ax.set_xlim(0,1.05);ax.set_xlabel('Macro-F1（构造测试集）');fig.tight_layout();fig.savefig(ROOT/'results/classification.png',dpi=160);plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,7));cm=confusion_matrix(ty,pred,labels=CATEGORIES);ax.imshow(cm,cmap='Greens');ax.set_xticks(range(9),CATEGORIES,rotation=45,ha='right');ax.set_yticks(range(9),CATEGORIES)
    for i in range(9):
        for j in range(9):ax.text(j,i,str(cm[i,j]),ha='center',va='center',color='white' if cm[i,j]>cm.max()/2 else '#222')
    ax.set_xlabel('预测');ax.set_ylabel('真实');fig.tight_layout();fig.savefig(ROOT/'results/confusion.png',dpi=150);plt.close(fig)
    print(json.dumps({k:result[k] for k in ['rows','selected','classification','matching','anomaly','seconds']},ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    train()
