"""本地可演练的 ERP 变更源。

确定性生成每日领用更正/撤销事件，供同步引擎按截止点分页拉取。
演练能力：源端缺页（hidden）、错发事件撤回（withdrawn）、同版本内容冲突。
源端台账以对账快照形式提供，同步引擎不得反向写入本模块。
"""
import hashlib
import random
import time
from datetime import date, timedelta
from sqlalchemy import select, func
from src.models import ErpEvent, SyncState
from src.utils.serialization import checksum

BASE_START = date(2026, 4, 1)  # 与演示基础日历同一段 180 个自然日
BASE_DAYS = 180
PARTS = ('R17', 'G22')
SCENARIOS = ('normal', 'missing_page', 'conflict')


def get_state(db):
    st = db.get(SyncState, 1)
    if not st:
        st = SyncState(id=1, last_published_cutoff=0, round_counter=0, source_batch_counter=0)
        db.add(st)
        db.flush()
    return st


def head(db):
    """源端事件序号最大值（含缺页/撤回事件），作为开轮截止点锚。"""
    return db.scalar(select(func.max(ErpEvent.id))) or 0


def servable(db):
    """当前可送达的事件（排除缺页与撤回）。"""
    return select(ErpEvent).where(ErpEvent.hidden == False, ErpEvent.withdrawn == False)


def pending_count(db, after):
    return db.scalar(select(func.count()).select_from(ErpEvent).where(
        ErpEvent.id > after, ErpEvent.hidden == False, ErpEvent.withdrawn == False)) or 0


def _token(voucher, version, part, day):
    return 'REV-' + hashlib.sha256(f'{voucher}|{version}|{part}|{day}'.encode()).hexdigest()[:12].upper()


def voucher_state(db, cutoff=None):
    """按事件序号重放可送达事件，得到源端在 cutoff 处的凭证台账（对账基准）。"""
    q = servable(db)
    if cutoff is not None:
        q = q.where(ErpEvent.id <= cutoff)
    state = {}
    for e in db.scalars(q.order_by(ErpEvent.id)):
        cur = state.get(e.voucher)
        if e.kind == 'upsert':
            if cur is None or e.version >= cur['version']:
                state[e.voucher] = {'version': e.version, 'part': e.part, 'day': e.day,
                                    'demand': e.demand, 'revoked': False, 'revocation_token': ''}
        elif cur is not None and e.version >= cur['version']:
            state[e.voucher] = {'version': e.version, 'part': cur['part'], 'day': cur['day'],
                                'demand': cur['demand'], 'revoked': True, 'revocation_token': e.revocation_token}
    return state


def snapshot(db, cutoff):
    """源端在截止点的对账快照：凭证数、有效/撤销数与内容指纹。"""
    state = voucher_state(db, cutoff)
    payload = sorted((v, s['version'], s['part'], s['day'], s['demand'], s['revoked'], s['revocation_token'])
                     for v, s in state.items())
    return {'cutoff': cutoff, 'vouchers': len(state),
            'active': sum(1 for s in state.values() if not s['revoked']),
            'revoked': sum(1 for s in state.values() if s['revoked']),
            'checksum': checksum(payload)}


def generate_batch(db, scenario='normal'):
    """生成一天的更正批次。正常批含：新凭证、版本升级、撤销（带凭据）、晚到旧版。"""
    if scenario not in SCENARIOS:
        raise ValueError('未知演练场景')
    st = get_state(db)
    st.source_batch_counter += 1
    n = st.source_batch_counter
    rng = random.Random(9000 + n)
    state = voucher_state(db)
    active = sorted(v for v, s in state.items() if not s['revoked'])
    events = []

    def emit(**kw):
        events.append(ErpEvent(batch_no=n, emitted_at=time.time(), **kw))

    for k in range(rng.randint(3, 4)):  # 新凭证更正
        emit(voucher=f'RQ-2026-{1000 + n * 10 + k}', version=1, kind='upsert',
             part=rng.choice(PARTS), day=str(BASE_START + timedelta(days=rng.randrange(BASE_DAYS))),
             demand=float(rng.randint(1, 6)), revocation_token='')
    if active:  # 既有凭证版本升级
        v = rng.choice(active)
        s = state[v]
        emit(voucher=v, version=s['version'] + 1, kind='upsert', part=s['part'], day=s['day'],
             demand=float(rng.randint(1, 8)), revocation_token='')
    revoked_voucher = None
    if active:  # 撤销一张既有凭证，出具撤销凭据
        revoked_voucher = rng.choice(active)
        s = state[revoked_voucher]
        emit(voucher=revoked_voucher, version=s['version'] + 1, kind='revoke', part=s['part'], day=s['day'],
             demand=0.0, revocation_token=_token(revoked_voucher, s['version'] + 1, s['part'], s['day']))
    if revoked_voucher:  # 晚到旧版：不得恢复已撤销记录
        s = state[revoked_voucher]
        emit(voucher=revoked_voucher, version=s['version'], kind='upsert', part=s['part'], day=s['day'],
             demand=s['demand'], revocation_token='')
    if scenario == 'conflict':  # 源端错发：同凭证同版本不同内容
        if active:
            v, s = active[0], state[active[0]]
            emit(voucher=v, version=s['version'], kind='upsert', part=s['part'], day=s['day'],
                 demand=s['demand'] + 9.0, revocation_token='')
        elif events:
            e0 = events[0]
            emit(voucher=e0.voucher, version=e0.version, kind='upsert', part=e0.part, day=e0.day,
                 demand=e0.demand + 9.0, revocation_token='')
    db.add_all(events)
    db.flush()
    if scenario == 'missing_page' and len(events) >= 3:  # 源端缺页：中间一页取不到
        events[len(events) // 2].hidden = True
        db.flush()
    return events


def repair(db):
    """修复源端：恢复缺页事件；同凭证同版本同类型但内容不同的错发事件予以撤回。"""
    restored = 0
    for e in db.scalars(select(ErpEvent).where(ErpEvent.hidden == True)):
        e.hidden = False
        restored += 1
    withdrawn = 0
    seen = {}
    for e in db.scalars(select(ErpEvent).where(ErpEvent.withdrawn == False).order_by(ErpEvent.id)):
        key = (e.voucher, e.version, e.kind)
        payload = (e.part, e.day, e.demand)
        if key in seen and seen[key] != payload:
            e.withdrawn = True
            withdrawn += 1
        else:
            seen.setdefault(key, payload)
    db.flush()
    return {'restored': restored, 'withdrawn': withdrawn}
