import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.schema import CATEGORIES, Transaction

CAT_WORDS = {
    '餐饮': ['面馆午餐', '咖啡饮品', '外卖晚餐', '食堂早餐', '烘焙蛋糕'],
    '交通': ['地铁乘车', '公交车票', '出租车出行', '共享单车', '高铁车票'],
    '购物': ['超市日用品', '服装鞋帽', '数码配件', '电商商品', '文具采购'],
    '居住缴费': ['生活电费', '自来水费', '房租缴纳', '宽带月费', '物业缴费'],
    '医疗': ['门诊挂号', '药店购药', '体检费用', '牙科诊疗', '医疗检查'],
    '教育': ['课程学费', '教材图书', '培训报名', '考试报名', '学习资料'],
    '娱乐': ['电影门票', '游戏会员', '音乐订阅', '游乐门票', '演出门票'],
    '生活服务': ['洗衣服务', '快递寄件', '理发服务', '家政清洁', '维修服务'],
    '其他': ['公益捐款', '礼金往来', '杂项费用', '临时支出', '个人赠与'],
}


def generate():
    rng = random.Random(20261110)
    rows = []
    for i in range(2400):
        cat = CATEGORIES[i % 9]
        merchant_group = (i // 9) % 30
        split = 'train' if merchant_group < 18 else ('validation' if merchant_group < 24 else 'test')
        group = f'{cat}-{merchant_group:02}'
        word = rng.choice(CAT_WORDS[cat])
        brand = f'{["青禾","云间","星桥","南巷","拾光","远山"][merchant_group % 6]}{merchant_group:02}'
        merchant = brand + word[:2]
        templates={'train':['{}','{} 支付','门店消费 {}'],
            'validation':['{}订单结算','线上服务 {}'],
            'test':['本次{}付款','结算记录：{}']}
        desc = rng.choice(templates[split]).format(word)
        if rng.random() < .055:
            merchant, desc = brand, '扫码支付'
        amount = rng.randint(500, 18000)
        anomaly = rng.random() < .035
        if anomaly:
            amount = rng.randint(90000, 250000)
        when = datetime(2026, 4, 1) + timedelta(days=rng.randrange(180), hours=rng.randrange(8, 23), minutes=rng.randrange(60))
        platform = '微信' if i % 2 else '支付宝'
        tx = Transaction(id=f'SYN{i:05}', platform=platform, account='我的'+platform,
            time=when.isoformat(), direction='支出', amount=amount, merchant=merchant,
            description=desc, order_id=f'ORDER{i:07}', sources=[{'file':'构造账单','row':i+1}]).model_dump()
        tx.update(truth_category=cat, truth_relation='', truth_link='', truth_anomaly=anomaly, group=group, split=split, template_family=split, synthetic=True)
        rows.append(tx)
    for i in range(150):
        original = rows[i * 13 % 2400]
        r = original.copy()
        r.update(id=f'INC{i:04}', direction='收入', kind='收入', merchant='构造工资账户', description='工资入账',
            amount=rng.randint(200000, 800000), order_id=f'INCORDER{i}', truth_category='', truth_anomaly=False)
        rows.append(r)
    for i in range(100):
        base = rows[i * 17 % 2400]
        when = datetime.fromisoformat(base['time'])
        for incoming in [False, True]:
            r = base.copy()
            platform = '支付宝' if incoming else '微信'
            r.update(id=f'TR{i:04}{int(incoming)}', platform=platform, account='我的'+platform,
                merchant='我的微信' if incoming else '我的支付宝', description='本人账户余额划转',
                kind='转账', direction='收入' if incoming else '支出', amount=(i%20+1)*10000,
                order_id=f'TRORDER{i}-{int(incoming)}', reference=f'OWN{i:04}',
                time=(when+timedelta(minutes=2 if incoming else 0)).isoformat(),
                truth_category='', truth_relation='transfer', truth_link=f'TR{i:04}{int(not incoming)}', truth_anomaly=False)
            rows.append(r)
    for i in range(150):
        base = rows[i * 11 % 2400]
        r = base.copy()
        r.update(id=f'REF{i:04}', direction='收入', kind='退款', description=base['description']+' 退款',
            amount=base['amount'] if i%3 else max(1,base['amount']//2),
            time=(datetime.fromisoformat(base['time'])+timedelta(days=i%35+1)).isoformat(),
            order_id=f'REFORDER{i}', reference=base['order_id'] if i%4 else '',
            truth_relation='refund', truth_link=base['id'], truth_anomaly=False)
        rows.append(r)
    for i in range(100):
        base = rows[i * 19 % 2400]
        r = base.copy()
        r.update(id=f'DUP{i:04}', truth_relation='duplicate', truth_link=base['id'], truth_anomaly=False,
            sources=[dict(file='构造账单重复导出',row=i+1)])
        rows.append(r)
    assert len(rows) == 3000
    (ROOT/'data').mkdir(exist_ok=True)
    (ROOT/'data/synthetic.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2),encoding='utf-8')
    (ROOT/'data/DATA_CARD.md').write_text('''# 构造账单数据说明

本目录全部公开账单均为程序构造，不代表真实用户、真实支付或真实商户。
固定种子 20261110；共 3000 条：2400 消费、150 收入、200 转账记录（100 对）、150 退款、100 重复副本。
9 个消费类别，270 个商户组；商户组按 18/6/6 分为训练、验证、测试。关联事件及副本继承原交易组。
训练、验证、测试使用互不相同的句式模板族；类目词共享，歧义样例仍统一为“扫码支付”。
group、split、template_family、synthetic 及 truth_* 仅供实验，不提供给模型特征或账单导入器。
文本由有限模板构造，类别词较明显，不能据此声称真实账单达到相同指标。
小概率去掉类别词形成歧义，按 3.5% 概率注入大额交易作为异常标签；标签不是欺诈结论。
生成数据采用 CC0-1.0；真实样例须经授权放在 data/private/，不公开。
''',encoding='utf-8')
    print(json.dumps({'rows':len(rows),'seed':20261110},ensure_ascii=False))
    return rows


if __name__ == '__main__':
    generate()
