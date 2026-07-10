from pydantic import BaseModel


class QnaItem(BaseModel):
    index: int  # 1-based (Q1, Q2 ...)
    question: str
    answer: str | None = None
    follow_up_depth: int = 0  # 꼬리물기 단계 (최대 3)


class QnaAnswer(BaseModel):
    index: int
    answer: str
