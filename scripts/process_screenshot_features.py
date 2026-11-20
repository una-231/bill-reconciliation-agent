import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy import sparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.features import NUMERIC_FEATURES, extract_features, matching_features
from backend.ml import bundle


def process(input_dir, output_dir, reference_date=None):
    input_dir, output_dir = Path(input_dir).resolve(), Path(output_dir).resolve()
    private = ROOT / 'data/private'
    if not input_dir.is_relative_to(private) or not output_dir.is_relative_to(private):
        raise ValueError('真实截图输入和特征输出须位于data/private内')
    manifest = json.loads((input_dir / 'manifest.json').read_text(encoding='utf-8'))
    ocr = {r['file']: r for r in json.loads((input_dir / 'baseline.json').read_text(encoding='utf-8'))}
    records = []
    for source in manifest['files']:
        image = ROOT / source['file']
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        if digest != source['sha256']:
            raise ValueError('原图哈希改变，请重新核验来源')
        features = extract_features(ocr[image.name]['text'], digest, image.name,
            source['platform'], '我的' + source['platform'], reference_date)
        for record in features:
            record['display_id'] = f'{image.name[:2]}-{record["block_index"]:02d}'
        records.extend(features)
    output_dir.mkdir(parents=True, exist_ok=True)
    pairs = matching_features(records)
    values = np.array([[np.nan if r['features'][name] is None else r['features'][name]
        for name in NUMERIC_FEATURES] for r in records], dtype=np.float64)
    np.savez_compressed(output_dir / 'numeric_features.npz', values=values,
        columns=np.array(NUMERIC_FEATURES), row_ids=np.array([r['id'] for r in records]),
        missing_mask=np.isnan(values))
    model_path = ROOT / 'models/active.joblib'
    before = hashlib.sha256(model_path.read_bytes()).hexdigest()
    model = bundle()
    vectorizer = model['classifier'].steps[0][1]
    texts = [r['text_for_classifier'] for r in records]
    matrix = vectorizer.transform(texts)
    sparse.save_npz(output_dir / 'tfidf_features.npz', matrix)
    vocabulary = vectorizer.get_feature_names_out()
    for i, r in enumerate(records):
        row = matrix.getrow(i)
        top = sorted(zip(row.indices, row.data), key=lambda x: -x[1])[:8]
        r['tfidf_nonzero_count'] = int(row.nnz)
        r['tfidf_out_of_vocabulary'] = row.nnz == 0
        if row.nnz == 0:
            r['issues'].append('训练词表未覆盖文本')
        r['tfidf_top_terms'] = [dict(term=str(vocabulary[j]), weight=float(weight)) for j, weight in top]
    assert hashlib.sha256(model_path.read_bytes()).hexdigest() == before
    summary = dict(created_at=datetime.now().isoformat(), platform_counts=dict(Counter(r['platform'] for r in records)),
        visible_appearances=len(records), amount_valid=sum(r['features']['amount_cents'] is not None for r in records),
        complete_timestamp=sum(r['timestamp'] is not None for r in records),
        missing_year=sum(r['features']['missing_year'] for r in records),
        missing_clock=sum(r['features']['missing_clock'] for r in records),
        relative_dates=sum(bool(r['relative_date']) for r in records),
        refund_records=sum(r['features']['is_refund'] for r in records),
        refund_annotations=sum(r['features']['has_refund_annotation'] for r in records),
        truncated_merchants=sum(r['features']['merchant_truncated'] for r in records),
        numeric_shape=list(values.shape), tfidf_shape=list(matrix.shape), tfidf_nnz=int(matrix.nnz),
        tfidf_empty_rows=sum(r['tfidf_out_of_vocabulary'] for r in records),
        vectorizer_ngram_range=list(vectorizer.ngram_range), vectorizer_fit_on_real=False,
        model_version=model['version'], model_sha256=before, matching_candidates=len(pairs),
        reference_date=reference_date, label_fields_in_input=False, llm_calls=0,
        rules=['原始OCR和清洗文本分开保存，截断名称不补全。',
            '金额以整数分保存；OCR金额异常保留缺失，不用人工转录标签替代模型输入。',
            '月日和时分可单独形成特征；年份未知时不推断星期，不生成完整时间。',
            '截图已退款备注是原消费的特征，不额外生成退款交易。',
            '数值缺失使用NaN并附缺失掩码，JSON使用null；0与缺失分开。',
            '字符级TF-IDF仅调用已训练向量器transform，不在真实样例上fit或更新模型。',
            '训练词表未覆盖的文本单独标记，不能将全零向量当作可靠分类依据。',
            '匹配候选只提示，不自动合并，也不将候选当作真值。'])
    def write(name, value):
        (output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    write('transactions.json', records)
    write('matching_features.json', pairs)
    write('processing_summary.json', summary)
    write('tfidf_columns.json', dict(row_ids=[r['id'] for r in records], vocabulary=vocabulary.tolist()))
    for name in ['transactions.json', 'numeric_features.npz', 'tfidf_features.npz']:
        if subprocess.run(['git', 'check-ignore', '--quiet', str(output_dir / name)], cwd=ROOT).returncode:
            raise ValueError('特征文件未被Git忽略')
    print(json.dumps({k: summary[k] for k in ['visible_appearances', 'platform_counts', 'numeric_shape', 'tfidf_shape', 'matching_candidates']}, ensure_ascii=False))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--reference-date', help='仅填写用户确认的截图拍摄日期')
    args = parser.parse_args()
    process(args.input_dir, args.output_dir, args.reference_date)
