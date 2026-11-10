from typing import Literal
from pydantic import BaseModel, Field, field_validator
from datetime import date as Date
from decimal import Decimal, InvalidOperation

CATEGORIES = ['餐饮', '交通', '购物', '居住缴费', '医疗', '教育', '娱乐', '生活服务', '其他']


class Transaction(BaseModel):
    id: str
    platform: Literal['微信', '支付宝']
    account: str
    time: str
    direction: Literal['支出', '收入', '不计收支']
    amount: int = Field(ge=0)
    merchant: str = ''
    description: str = ''
    order_id: str = ''
    reference: str = ''
    status: str = '成功'
    kind: str = '消费'
    category: str = ''
    confidence: float = 0
    excluded: bool = False
    linked_id: str = ''
    review_status: str = '待处理'
    sources: list[dict] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)


class ReviewAnswer(BaseModel):
    action: Literal['confirm', 'category', 'link', 'keep', 'exclude']
    category: str | None = None
    target_id: str | None = None


class TextInput(BaseModel):
    text: str = Field(min_length=1, max_length=60000)
    platform: Literal['微信', '支付宝'] = '微信'
    account: str = '我的微信'
    synthetic: bool = False


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    allow_remote: bool = False


class MappingInput(BaseModel):
    mapping: dict[str, str]
    platform: Literal['微信', '支付宝']
    account: str


class LedgerPatch(BaseModel):
    category: str | None = None
    excluded: bool | None = None


class NoteEntry(BaseModel):
    id: str = Field(default='', max_length=40)
    date: Date | None = None
    time: str | None = Field(default=None, pattern=r'^\d{2}:\d{2}$')
    merchant: str = Field(default='', max_length=160)
    amount_yuan: str | None = None
    direction: Literal['支出', '收入', '不计收支'] | None = None
    kind: Literal['消费', '收入', '退款', '转账'] = '消费'
    platform: Literal['微信', '支付宝'] | None = None
    account: str = Field(default='', max_length=100)
    description: str = Field(default='', max_length=500)
    evidence: str = Field(default='', max_length=1500)

    @field_validator('amount_yuan', mode='before')
    @classmethod
    def exact_amount(cls, value):
        if value is None or value == '': return None
        if isinstance(value, bool): raise ValueError('金额不能是布尔值')
        try:
            amount = Decimal(str(value))
            if not amount.is_finite() or amount < 0 or amount > 100000000 or amount * 100 != (amount * 100).to_integral_value():
                raise ValueError('金额须为非负数，最多两位小数')
            return format(amount, '.2f')
        except InvalidOperation as exc:
            raise ValueError('金额无法识别') from exc


class NoteInput(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    platform: Literal['微信', '支付宝'] = '微信'
    account: str = Field(default='我的微信', min_length=1, max_length=100)
    synthetic: bool = False
    allow_remote: bool = False
    reference_date: Date | None = None
    draft_id: str | None = None
    revision: int | None = None
    items: list[NoteEntry] | None = Field(default=None, max_length=10)


class NoteCommit(BaseModel):
    revision: int = Field(ge=1)
    acknowledge_questions: bool = False
    items: list[NoteEntry] = Field(min_length=1, max_length=10)
