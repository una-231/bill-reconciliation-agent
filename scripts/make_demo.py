import csv
import json
import sys
from datetime import datetime,timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.schema import Transaction


def make():
    rows=[]
    templates=[('青禾面馆','午餐面馆消费','餐饮',2800),('拾光咖啡','咖啡饮品','餐饮',2400),('城市地铁','地铁乘车','交通',600),('星桥超市','超市日用品','购物',8600),('小巷洗衣','洗衣服务','生活服务',3500),('知行书店','教材图书','教育',6800),('光影影院','电影门票','娱乐',4500),('民生药房','药店购药','医疗',4200),('城市水务','自来水费','居住缴费',7900)]
    for i in range(54):
        merchant,desc,cat,amount=templates[i%len(templates)]
        platform='微信' if i%2 else '支付宝'
        date=datetime(2026,7,1)+timedelta(days=i*1.55,hours=12,minutes=i%60)
        r=Transaction(id=f'DEMO{i:04}',platform=platform,account='我的'+platform,time=date.isoformat(),direction='支出',amount=amount+(i%4)*100,
            merchant=merchant,description=desc,order_id=f'DEMOORDER{i:04}',sources=[dict(file='构造演示账单',row=i+1)],raw={'演示标记':'明确构造数据'}).model_dump()
        rows.append(r)
    def extra(id,**kwargs):
        base=dict(platform='微信',account='我的微信',time='2026-09-25T12:30:00',direction='支出',amount=10000,merchant='构造商户',description='构造交易',order_id=id,sources=[dict(file='构造演示账单',row=len(rows)+1)],raw={'演示标记':'明确构造数据'})
        base.update(kwargs);r=Transaction(id=id,**base).model_dump();rows.append(r);return r
    extra('DEMO-OWN-OUT',merchant='我的支付宝',kind='转账',amount=120000,reference='DEMO-SELF-1',description='本人账户划转')
    extra('DEMO-OWN-IN',platform='支付宝',account='我的支付宝',merchant='我的微信',kind='转账',direction='收入',amount=120000,reference='DEMO-SELF-1',time='2026-09-25T12:32:00',description='本人账户划转')
    extra('DEMO-FRIEND',merchant='张同学（构造）',kind='转账',amount=4800,description='聚餐分摊转账')
    extra('DEMO-UNKNOWN',merchant='云间商贸（构造）',amount=13900,description='扫码支付')
    original=rows[48]
    extra('DEMO-REFUND',account=original['account'],platform=original['platform'],merchant=original['merchant'],kind='退款',direction='收入',amount=original['amount']//2,reference=original['order_id'],description='部分退款')
    extra('DEMO-REFUND-MISSING',merchant='星桥超市',kind='退款',direction='收入',amount=99900,description='原订单未导入')
    duplicate=dict(rows[45]);duplicate['id']='DEMO-DUP';duplicate['sources']=[dict(file='构造演示重复副本',row=2)];rows.append(duplicate)
    extra('DEMO-UNUSUAL',merchant='远山数码（构造）',amount=389900,description='数码商品大额消费')
    extra('DEMO-SAME-1',merchant='拾光咖啡',amount=2400,order_id='',time='2026-09-26T15:00:00',description='咖啡饮品 扫码支付')
    extra('DEMO-SAME-2',merchant='拾光咖啡',amount=2400,order_id='',time='2026-09-26T15:01:00',description='咖啡饮品 扫码支付')
    extra('DEMO-CLOSED',merchant='构造电商',amount=88800,status='交易关闭',description='关闭的商品订单')
    (ROOT/'data/demo.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    for platform in ['微信','支付宝']:
        path=ROOT/f'data/demo_{platform}.csv'
        with path.open('w',encoding='utf-8-sig',newline='') as f:
            f.write('明确构造账单，非真实用户数据\n')
            writer=csv.DictWriter(f,fieldnames=['交易时间','交易对方','商品说明','收/支','金额(元)','当前状态','交易单号','原订单号','交易类型','账户'])
            writer.writeheader()
            for r in rows:
                if r['platform']==platform:writer.writerow(dict(zip(writer.fieldnames,[r['time'],r['merchant'],r['description'],r['direction'],f'{r["amount"]/100:.2f}',r['status'],r['order_id'],r['reference'],r['kind'],r['account']])))
    (ROOT/'data/demo_text.txt').write_text('明确构造账单\n2026-09-08 12:30 青禾面馆 支出 28.00元\n2026-09-08 18:00 城市地铁 支出 6.00元\n',encoding='utf-8')
    from PIL import Image,ImageDraw,ImageFont
    im=Image.new('RGB',(1500,630),'#fafcf9');draw=ImageDraw.Draw(im)
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',30);title=ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc',40)
    draw.text((55,45),'构造账单测试图（非真实支付截图）',font=title,fill='#285f49')
    for i,line in enumerate(['2026-09-08 12:30 青禾面馆 支出 28.00元','2026-09-08 18:00 城市地铁 支出 6.00元','2026-09-09 10:20 知行书店 支出 68.00元']):
        y=160+i*115;draw.line((55,y-20,1445,y-20),fill='#d9e3d4',width=2);draw.text((65,y),line,font=font,fill='#334835')
    im.save(ROOT/'data/demo_screenshot.png')
    im.resize((600,252)).resize(im.size).save(ROOT/'data/demo_screenshot_blurred.png')
    print(f'已生成 {len(rows)} 条构造演示记录及CSV、文字、OCR测试图')


if __name__=='__main__':make()
