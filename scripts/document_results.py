import json
import importlib.metadata as meta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


if __name__=='__main__':
    m=json.loads((ROOT/'results/metrics.json').read_text(encoding='utf-8'))
    w=json.loads((ROOT/'results/workflow_evaluation.json').read_text(encoding='utf-8'))
    lines=['# 实验设计与实际结果','','所有数字来自固定种子构造数据的实际运行，未使用真实账单。','','## 数据与划分','',
        f'共{m["rows"]}条记录，训练/验证/测试数量为'+str(m['split_counts'])+'。商户组和关联事件不跨集合；不同集合使用不同句式模板族，类目关键词共享。TF-IDF只在训练集拟合。',
        '',f'模型按验证集Macro-F1选择为 **{m["selected"]}**，不按测试集最高分挑选。分类阈值为{m["category_threshold"]}，也是在验证集选择。','','## 消费分类','',
        '|方法|Macro-F1|准确率|','|---|---:|---:|']
    lines += [f'|{x["model"]}|{x["macro_f1"]:.4f}|{x["accuracy"]:.4f}|' for x in m['classification']]
    lines += ['',f'自动分类覆盖率为{m["classification_coverage"]:.2%}，被自动接受样例的正确率为{m["classification_auto_precision"]:.2%}。完整类别Precision/Recall/F1见results/metrics.json，错误记录见results/classification_errors.json。','','## 匹配与端到端流程','',
        '|任务（候选对级）|Precision|Recall|F1|候选召回|','|---|---:|---:|---:|---:|']
    lines += [f'|{k}|{v["precision"]:.4f}|{v["recall"]:.4f}|{v["f1"]:.4f}|{v["candidate_recall"]:.4f}|' for k,v in m['matching'].items()]
    lines += ['','匹配模型按金额、时间等筛选候选后评分；同订单、本人账户和退款累计约束由工作流另外验证。候选对级表现不能当作自动关联效果。','','|流程|自动关联数|自动关联精确率|重复计账率|请求核对记录比例|','|---|---:|---:|---:|---:|']
    for r in w['ablations']:
        lines.append(f'|{r["variant"]}|{r["automatic_link_count"]}|{r["automatic_link_precision"]:.4f}|{r["duplicate_accounting_rate"]:.2%}|{r["review_request_rate"]:.2%}|')
    lines += ['','没有任何自动关联时精确率记0，仅为导出约定，不代表执行了错误关联。重复计账率的分母为实际纳入汇总的记录数；误合并率分母为已排除且有关联的记录数。',
        '完整流程仍有待核对项，当前净支出不能当作最终支出；不把暂时排除待核对记录导致的金额减少称为节省支出。',
        '',f'异常检测在有此前月份历史的{m["anomaly"]["evaluated"]}条消费上，Precision={m["anomaly"]["precision"]:.4f}、Recall={m["anomaly"]["recall"]:.4f}、F1={m["anomaly"]["f1"]:.4f}。标签是构造的大额交易，不是欺诈标签。',
        '','','## 纠正反馈、体检与OCR','',
        f'个性化适应使用18条自习空间消费纠正，12个不同商户留出测试，准确率从{w["personalization"]["accuracy_before"]:.0%}变为{w["personalization"]["accuracy_after"]:.0%}。留出样例共享同一种服务描述，这是单一偏好适应探针，不代表普遍泛化。',
        '人工反馈比例使用真值模拟计算，不是招募真实用户得到的实测结果。',
        '体检独立探针30条记录中人为删除5个商户，检测5个；关闭体检的主测试结果不变，因为主测试字段完整。','','|构造截图|正确记录数|金额精确率|时间精确率|商户精确率|','|---|---:|---:|---:|---:|']
    for r in w['ocr']:
        if 'error' not in r:lines.append(f'|{r["file"]}|{r["records"]}/{r["expected_records"]}|{r["amount_exact"]:.0%}|{r["time_exact"]:.0%}|{r["merchant_exact"]:.0%}|')
        else:lines.append(f'|{r["file"]}|失败：{r["error"]}|—|—|—|')
    lines += ['','## 已发现问题与修复证据','',
        '- 初版撤销后重新确认不能结束任务：补充终止检查点重新进入finish的处理，回归测试覆盖完整路径。',
        '- 初版OCR按文本块换行，列被拆开：按检测框纵向位置合并，再做字段提取；压缩图片中的日期与时间无空格也已覆盖。',
        '- 初版在采样负例上选择匹配阈值，实际候选分布的精确率较低：改用验证集全部候选选阈值，保留训练时的负例采样；不使用测试集选阈值。',
        '- 模糊商户“扫码支付”仍缺少可靠类别依据，保留人工核对；异常检测存在误报，用户确认后才纳入汇总。',
        '', '## 当前验收边界','',
        '本地功能与公开构造样例已实测；真实API验证以results/api_validation.json的实际记录为准，详见docs/API_VALIDATION.md。真实账单兼容性仍等待用户授权样例，不将其标记为已完成。',
        '', '复现命令见README。完整机器可读记录在results/metrics.json、results/workflow_evaluation.json和results/ablations.csv。']
    (ROOT/'docs/EVALUATION.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    versions={n:meta.version(n) for n in ['fastapi','pydantic','pandas','openpyxl','scikit-learn','langgraph','langgraph-checkpoint-sqlite','rapidocr','onnxruntime','httpx','numpy','pytest']}
    (ROOT/'results/component_versions.json').write_text(json.dumps(versions,indent=2),encoding='utf-8')
    print(json.dumps(versions,indent=2))
