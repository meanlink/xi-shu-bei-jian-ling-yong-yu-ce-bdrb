from sqlalchemy import String, Double, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class ErpEvent(Base):
    """本地演练 ERP 变更源的事件日志；id 即源端事件序号，作为接续游标。"""
    __tablename__ = 'erp_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_no: Mapped[int]
    voucher: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[int]
    kind: Mapped[str] = mapped_column(String(10))  # upsert 更正 | revoke 撤销
    part: Mapped[str] = mapped_column(String(20), default='')
    day: Mapped[str] = mapped_column(String(10), default='')
    demand: Mapped[float] = mapped_column(Double, default=0)
    revocation_token: Mapped[str] = mapped_column(String(80), default='')
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)     # 演练：源端缺页，取不到
    withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)  # 演练：源端撤回错发事件
    emitted_at: Mapped[float] = mapped_column(Double)


class SyncRound(Base):
    """一轮同步：从上一截止点接续到本轮截止点，对账通过后发布新日历批次。"""
    __tablename__ = 'sync_rounds'
    id: Mapped[int] = mapped_column(primary_key=True)
    round_no: Mapped[int] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(String(20), default='syncing')  # syncing/reconciling/blocked/failed/published
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    start_after: Mapped[int]  # 上一已发布截止点（不含）
    cutoff: Mapped[int]       # 本轮截止点（含），同轮分页固定不变
    cursor: Mapped[int]       # 已接续到的事件序号
    pages_expected: Mapped[int] = mapped_column(default=0)
    pages_done: Mapped[int] = mapped_column(default=0)
    applied: Mapped[int] = mapped_column(default=0)
    rejected: Mapped[int] = mapped_column(default=0)
    inject: Mapped[bool] = mapped_column(Boolean, default=False)  # 演练：同轮分页期间源端并发补发
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
    block_reason: Mapped[str] = mapped_column(String(500), default='')
    error: Mapped[str] = mapped_column(String(500), default='')
    created_at: Mapped[float] = mapped_column(Double)
    updated_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class SyncEntry(Base):
    """每条源端事件的取舍记录；(round_id, event_id) 唯一保证重试不重复入账。"""
    __tablename__ = 'sync_entries'
    __table_args__ = (UniqueConstraint('round_id', 'event_id', name='uq_sync_entry_event'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey('sync_rounds.id'))
    event_id: Mapped[int]
    voucher: Mapped[str] = mapped_column(String(40))
    version: Mapped[int]
    kind: Mapped[str] = mapped_column(String(10))
    decision: Mapped[str] = mapped_column(String(20))  # applied/duplicate/stale_rejected/revoked/conflict
    reason: Mapped[str] = mapped_column(String(300), default='')
    at: Mapped[float] = mapped_column(Double)


class CorrectionLedger(Base):
    """按来源凭证接续的更正台账；撤销凭据留痕，晚到旧版不得翻回。"""
    __tablename__ = 'correction_ledger'
    id: Mapped[int] = mapped_column(primary_key=True)
    voucher: Mapped[str] = mapped_column(String(40), unique=True)
    version: Mapped[int]
    part: Mapped[str] = mapped_column(String(20), default='')
    day: Mapped[str] = mapped_column(String(10), default='')
    demand: Mapped[float] = mapped_column(Double, default=0)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    revocation_token: Mapped[str] = mapped_column(String(80), default='')
    last_event_id: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[float] = mapped_column(Double, default=0)


class SyncState(Base):
    """单行全局状态：已发布截止点与轮次/源端批次计数。"""
    __tablename__ = 'sync_state'
    id: Mapped[int] = mapped_column(primary_key=True)
    last_published_cutoff: Mapped[int] = mapped_column(default=0)
    round_counter: Mapped[int] = mapped_column(default=0)
    source_batch_counter: Mapped[int] = mapped_column(default=0)
