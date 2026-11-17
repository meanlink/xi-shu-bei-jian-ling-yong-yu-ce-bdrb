from pydantic import BaseModel
from typing import Literal


class RoundStart(BaseModel):
    simulate_concurrent: bool = False  # 演练：同轮分页期间源端并发补发


class SourceAdvance(BaseModel):
    scenario: Literal['normal', 'missing_page', 'conflict'] = 'normal'
