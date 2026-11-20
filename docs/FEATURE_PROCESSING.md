# 截图特征处理

截图账本与特征样本分开处理：字段未齐全的记录不能入账，但可以保留已知月日、时分和商户文本，生成带缺失标记的特征。

`backend/features.py`从OCR交易块提取以下特征，不读取人工类别或匹配标签：

- 文本：保留原商户名称，使用NFKC统一字符、去除独立图标文字及标点；分店编号保留，省略号单独标记，不补全名称或按相似度合并商户。
- 金额：整数分、带收支符号金额、`log1p(金额元)`。异常OCR金额不使用人工参考答案填补。
- 日期：年、月、日、时、分、星期和时段正弦／余弦；缺少年份时仍保留可见月日，星期和完整时间保持缺失。相对日期仅在明确拍摄日期后解析。
- 账务线索：收支、退款、转账和原消费退款备注。转账标记不等于本人内部转账；退款备注不额外产生交易。
- 缺失：金额、年份、日和时分的独立缺失标记；JSON使用null，数值矩阵使用NaN和`missing_mask`，真实0不会被当作缺失。
- 匹配：金额差、金额相对差、完整时间差、文本相似度、方向、账户、平台及可见月日和时分一致性。完整时间未知时，时间差保持缺失；候选不自动合并。

`scripts/process_screenshot_features.py`复用已有分类模型的字符级TF-IDF向量器，只执行`transform`，不在真实样例上拟合、更新词表或重新训练。全零向量用`tfidf_out_of_vocabulary`标记，不能当作可靠分类依据。

本地截图验证目录包含`manifest.json`、`baseline.json`和原图。清单声明平台和原图SHA-256，OCR来源文件与清单对应；处理前校验原图哈希。命令中的输入与输出目录必须位于Git已忽略的`data/private/`中：

```powershell
.\.venv\Scripts\python.exe scripts/process_screenshot_features.py --input-dir data/private/<本地验证目录> --output-dir data/private/<本地验证目录>/features
```

输出`transactions.json`（原文、清洗结果、缺失信息及行ID）、`matching_features.json`（关系对照）、`numeric_features.npz`（数值矩阵、列名、行ID及缺失掩码）、`tfidf_features.npz`（稀疏矩阵）、`tfidf_columns.json`（对应词表及行ID）和`processing_summary.json`（配置、哈希与处理统计）。

真实截图及其逐笔派生特征仅用于本地兼容性核验，不提交仓库、不发送外部模型API。不能用参与调试的少量样例证明泛化性能。
