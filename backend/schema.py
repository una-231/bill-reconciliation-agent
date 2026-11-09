from typing import Literal
from pydantic import BaseModel, Field

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
