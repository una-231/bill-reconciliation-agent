# 复用组件与许可说明

精确Python依赖版本见requirements-lock.txt，前端依赖见frontend/package-lock.json。OCR模型名及推理行为见results/workflow_evaluation.json与本机运行日志。

|组件|来源|许可证或服务条款|用途与归属|
|---|---|---|---|
|LangGraph及SQLite检查点|https://github.com/langchain-ai/langgraph|MIT|复用图执行与中断机制，节点、状态和核对语义自行实现|
|scikit-learn|https://github.com/scikit-learn/scikit-learn|BSD-3-Clause|复用TF-IDF、NB、逻辑回归、IsolationForest与指标；自行设计特征、划分及评估|
|RapidOCR|https://github.com/RapidAI/RapidOCR|Apache-2.0；模型许可随上游|复用本地OCR；自行合并坐标文本、解析账单并强制复核|
|ONNX Runtime|https://github.com/microsoft/onnxruntime|MIT|CPU OCR推理|
|pandas / openpyxl|https://github.com/pandas-dev/pandas / https://openpyxl.readthedocs.io/|BSD-3-Clause / MIT|读写表格，字段适配和账务口径自行实现|
|FastAPI / Pydantic|https://github.com/fastapi/fastapi / https://github.com/pydantic/pydantic|MIT|接口与结构化校验|
|React / Vite / TypeScript|https://react.dev/ / https://vite.dev/ / https://www.typescriptlang.org/|MIT / MIT / Apache-2.0|界面基础设施，页面与交互自行实现|
|Lucide / Recharts|https://lucide.dev/ / https://recharts.org/|ISC / MIT|图标及趋势图|
|CSV Data Summarizer 2.1.0|https://github.com/coffeefuelbump/csv-data-summarizer-claude-skill|上游README声明MIT，无单独LICENSE|审阅并适配其数据体检工作流；上游原文件仅保留供核查|
|Qwen-Flash API|https://help.aliyun.com/zh/model-studio/|阿里云服务条款，不把API等同本地开源权重|可配置的文字结构化和对话服务|
|公开构造账单|scripts/generate_data.py、scripts/make_demo.py|CC0-1.0|本项目自行生成，无真实用户账单|

## 深入核验的 Skill

上游提交固定为 `9b3affd270f85aaf1c8a7a457f510034d5736cde`；原始SKILL.md、analyze.py、README和依赖文件及SHA-256保存在third_party/csv-data-summarizer。

原技能接受CSV路径，使用pandas读取，输出文本统计并在当前工作目录生成图表。它按英文date/time列名识别日期，通用地统计数值列；不理解退款、内部转账和账本核对。原说明要求自动完成分析且不询问，这与账务歧义必须确认的任务不符。原代码在空表缺失值占比计算上存在除零风险，图表固定文件名也不适合多个导入任务。

本项目读取并审查了原说明和源码，没有直接运行下载的脚本。改造版输入为已验证的交易列表，输出结构化质量结果；接入中文表头、整数金额和来源信息，空表安全返回，问题送往核对队列；图表由前端绘制，不覆盖当前目录。原提示中的禁止询问被移除，账务口径交给独立确定性工具处理。

改造技能位于skills/bill-data-quality/SKILL.md，实际工具为backend/quality.py。该工具只访问内存中的标准化记录，无外部服务或命令执行权限。测试核验空表、缺字段、中文CSV/XLSX和错误日期；独立30条数据中注入5个缺失商户，检测5个。字段完整的主测试集上关闭体检不会改变金额结果，不能据此宣称体检提高分类F1。

原文件没有单独LICENSE，本项目保留README中的声明并如实披露这一点，不将上游许可信息缺失包装成已完成独立法律审查。自身代码MIT许可不覆盖第三方文件。
