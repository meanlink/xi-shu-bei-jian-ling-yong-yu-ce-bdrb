"""ERP 变更接续引擎。

一轮同步固定一个截止点，分页拉取源端事件并逐条取舍入账：
- 按来源凭证与版本接续台账，撤销凭据留痕，晚到旧版不恢复已撤销记录；
- 每页提交检查点，中断后从游标接续；(round,event) 唯一约束保证重试不重复入账；
- 缺页或版本冲突立即阻断发布；整轮对账通过才生成新日历批次开放试算；
- 日历批次先于轮次进度落库，进度丢失时按批次名与指纹找回原批次。
"""
import math
import time
from fastapi import HTTPException
from sqlalchemy import select, func
from src.models import Dataset, ErpEvent, SyncRound, SyncEntry, CorrectionLedger
from src.services import erpsource
from src.services.business import metadata
from src.utils.serialization import checksum

PAGE_SIZE = 4
ACTIVE = ('syncing', 'reconciling')


class SourceConflict(Exception):
    """版本冲突：阻断发布，等待源端修复。"""


def get_round(db, round_id):
    r = db.get(SyncRound, round_id)
    if not r:
        raise HTTPException(404, '同步轮次不存在')
    return r


def start(db, simulate_concurrent=False):
    st = erpsource.get_state(db)
    existing = db.scalar(select(SyncRound).where(SyncRound.status.in_(ACTIVE)))
    if existing:
        raise HTTPException(409, f'第 {existing.round_no} 轮尚未结束（{existing.status}），请先继续或恢复该轮')
    head = erpsource.head(db)
    pending = erpsource.pending_count(db, st.last_published_cutoff)
    if head <= st.last_published_cutoff or pending == 0:
        raise HTTPException(409, '源端暂无新的变更，请先补发今日更正')
    st.round_counter += 1
    start_after = st.last_published_cutoff
    r = SyncRound(round_no=st.round_counter, status='syncing', paused=False,
                  start_after=start_after, cutoff=head, cursor=start_after,
                  pages_expected=math.ceil(pending / PAGE_SIZE), pages_done=0,
                  applied=0, rejected=0, inject=bool(simulate_concurrent),
                  created_at=time.time(), updated_at=time.time())
    db.add(r)
    db.flush()
    return r


def pause(db, r):
    if r.status != 'syncing' or r.paused:
        raise HTTPException(409, '仅待接续中的轮次可以暂停')
    r.paused = True
    r.updated_at = time.time()
    return r


def resume(db, r):
    """恢复接续：暂停、阻断或失败的轮次回到待接续；已对齐截止点的直接重新对账。"""
    if r.status == 'published':
        raise HTTPException(409, '该轮已发布，无需恢复')
    if r.status == 'syncing' and not r.paused:
        raise HTTPException(409, '该轮正在接续中，无需恢复')
    r.paused = False
    r.block_reason = ''
    r.error = ''
    r.updated_at = time.time()
    if r.status in ('blocked', 'failed'):
        r.status = 'syncing'
    if r.status == 'reconciling' or r.cursor >= r.cutoff:
        r.status = 'reconciling'
        db.flush()
        reconcile(db, r)
    return r


def _block(db, r, reason):
    r.status = 'blocked'
    r.block_reason = reason
    r.updated_at = time.time()
    db.flush()
    return r


def _apply(db, r, e):
    """单事件幂等入账；版本冲突抛 SourceConflict 由上层阻断。"""
    existing = db.scalar(select(SyncEntry).where(SyncEntry.round_id == r.id, SyncEntry.event_id == e.id))
    if existing and existing.decision != 'conflict':
        return  # 重试不重复入账；冲突记录不算已入账，修复前仍会再次阻断
    led = db.scalar(select(CorrectionLedger).where(CorrectionLedger.voucher == e.voucher))
    decision, reason = 'applied', ''
    if e.kind == 'upsert':
        if led is None:
            db.add(CorrectionLedger(voucher=e.voucher, version=e.version, part=e.part, day=e.day,
                                    demand=e.demand, revoked=False, revocation_token='',
                                    last_event_id=e.id, updated_at=time.time()))
            reason = f'新凭证入账，版本 v{e.version}'
        elif e.version > led.version:
            led.version, led.part, led.day, led.demand = e.version, e.part, e.day, e.demand
            led.revoked, led.revocation_token = False, ''
            led.last_event_id, led.updated_at = e.id, time.time()
            reason = f'版本接续至 v{e.version}'
        elif e.version == led.version and not led.revoked and \
                led.part == e.part and led.day == e.day and led.demand == e.demand:
            decision, reason = 'duplicate', '同版本同内容重复补发，跳过'
        elif e.version == led.version:
            raise SourceConflict(f'版本冲突：凭证 {e.voucher} v{e.version} 与台账内容不一致')
        else:
            decision = 'stale_rejected'
            reason = '凭证已撤销，晚到旧版不恢复' if led.revoked else f'晚到旧版 v{e.version}，当前 v{led.version}，忽略'
    else:  # revoke 撤销
        if led is None:
            raise SourceConflict(f'版本冲突：撤销未知凭证 {e.voucher}，疑似缺页或乱序')
        if led.revoked and led.version == e.version:
            decision, reason = 'duplicate', '重复撤销，凭据已留存'
        elif e.version >= led.version:
            led.version, led.revoked, led.revocation_token = e.version, True, e.revocation_token
            led.last_event_id, led.updated_at = e.id, time.time()
            decision, reason = 'revoked', f'撤销入账，凭据 {e.revocation_token}'
        else:
            decision, reason = 'stale_rejected', f'晚到旧版撤销 v{e.version}，当前 v{led.version}，忽略'
    db.add(SyncEntry(round_id=r.id, event_id=e.id, voucher=e.voucher, version=e.version,
                     kind=e.kind, decision=decision, reason=reason, at=time.time()))
    if decision in ('applied', 'revoked'):
        r.applied += 1
    elif decision == 'stale_rejected':
        r.rejected += 1


def step(db, r):
    """拉取一页并提交检查点；到达截止点后转入对账。仅供 worker 调用。"""
    if r.status != 'syncing' or r.paused:
        return r
    page = list(db.scalars(erpsource.servable(db).where(
        ErpEvent.id > r.cursor, ErpEvent.id <= r.cutoff).order_by(ErpEvent.id).limit(PAGE_SIZE)))
    if not page:
        # 余下序号若均为源端撤回事件则直接对齐截止点；仍有可取事件却取不到即缺页
        rest = list(db.scalars(select(ErpEvent).where(
            ErpEvent.id > r.cursor, ErpEvent.id <= r.cutoff, ErpEvent.withdrawn == False)))
        if rest:
            return _block(db, r, f'源端缺页：接续点 {r.cursor + 1} 之后取不到事件，截止点 {r.cutoff} 无法凑齐')
        r.cursor = r.cutoff
    else:
        # 本页范围内的可取事件必须全部到齐（撤回事件除外），否则按缺页阻断
        in_range = db.scalar(select(func.count()).select_from(ErpEvent).where(
            ErpEvent.id > r.cursor, ErpEvent.id <= page[-1].id, ErpEvent.withdrawn == False))
        if in_range != len(page):
            return _block(db, r, f'源端缺页：接续点 {r.cursor + 1} 至事件 {page[-1].id} 之间存在取不到的事件')
        try:
            for e in page:
                _apply(db, r, e)
        except SourceConflict as ex:
            if not db.scalar(select(SyncEntry).where(SyncEntry.round_id == r.id, SyncEntry.event_id == e.id)):
                db.add(SyncEntry(round_id=r.id, event_id=e.id, voucher=e.voucher, version=e.version,
                                 kind=e.kind, decision='conflict', reason=str(ex), at=time.time()))
            return _block(db, r, str(ex))
        r.cursor = page[-1].id
        r.pages_done += 1
    r.updated_at = time.time()
    if r.inject and r.pages_done == 1:
        erpsource.generate_batch(db)  # 演练：同轮分页期间源端并发补发，序号落在截止点之外
    db.commit()  # 页级检查点：中断后从游标接续
    if r.cursor >= r.cutoff:
        r.status = 'reconciling'
        db.commit()
        reconcile(db, r)
    return r


def _calendar(db, r, ledger):
    """基础日历叠加有效更正，得到本轮完整日历；更正越界则阻断。"""
    base = db.scalar(select(Dataset).where(Dataset.name == metadata()['dataset_name']))
    if not base:
        return None, '缺少基础领用日历批次，请先在数据接入导入'
    records = [dict(row) for row in base.records]
    index = {(str(row['part']), str(row['day'])): row for row in records}
    for l in ledger.values():
        if l.revoked:
            continue
        key = (l.part, l.day)
        if key not in index:
            return None, f'对账失败：凭证 {l.voucher} 指向基础日历之外的 {l.part} {l.day}'
        index[key]['demand'] = l.demand
    return records, ''


def _publish(db, r, records):
    """日历批次先落库；同名同指纹说明进度未保存，找回原批次。"""
    name = f'ERP领用日历·第{r.round_no}轮·截止{r.cutoff}'
    digest = checksum(records)
    existing = db.scalar(select(Dataset).where(Dataset.name == name))
    if existing:
        if existing.checksum != digest:
            return None, f'对账失败：批次 {name} 已存在但内容指纹不一致'
        return existing, ''  # 日历已生成但进度未保存：找回原批次
    d = Dataset(name=name, source='erp-sync', records=records, checksum=digest, created_at=time.time())
    db.add(d)
    db.flush()
    return d, ''


def reconcile(db, r):
    """整轮对账：事件覆盖完整、台账与源端截止点快照一致，才发布新批次。"""
    expected = set(db.scalars(select(ErpEvent.id).where(
        ErpEvent.id > r.start_after, ErpEvent.id <= r.cutoff,
        ErpEvent.hidden == False, ErpEvent.withdrawn == False)))
    got = set(db.scalars(select(SyncEntry.event_id).where(SyncEntry.round_id == r.id)))
    missing = sorted(expected - got)
    if missing:
        return _block(db, r, f'对账失败：事件 {missing[:5]} 缺少取舍记录，疑似缺页')
    snap = erpsource.snapshot(db, r.cutoff)
    ledger = {l.voucher: l for l in db.scalars(select(CorrectionLedger))}
    local = sorted((v, l.version, l.part, l.day, l.demand, l.revoked, l.revocation_token)
                   for v, l in ledger.items())
    if checksum(local) != snap['checksum']:
        return _block(db, r, '对账失败：本地台账与源端截止点快照不一致，已阻断发布')
    records, err = _calendar(db, r, ledger)
    if err:
        return _block(db, r, err)
    dataset, err = _publish(db, r, records)
    if err:
        return _block(db, r, err)
    db.commit()  # 日历批次先于轮次进度落库
    r.dataset_id = dataset.id
    r.status = 'published'
    r.finished_at = time.time()
    r.updated_at = time.time()
    st = erpsource.get_state(db)
    st.last_published_cutoff = max(st.last_published_cutoff, r.cutoff)
    db.commit()
    return r
