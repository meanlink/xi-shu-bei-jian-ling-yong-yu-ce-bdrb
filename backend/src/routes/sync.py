from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from src.config.database import get_db
from src.models import ErpEvent, SyncRound, SyncEntry, CorrectionLedger, SyncState
from src.schemas.sync import RoundStart, SourceAdvance
from src.middlewares.auth import current_user, can_write
from src.services import sync as engine, erpsource
from src.services.audit import record
from src.utils.serialization import round_dict, entry_dict, ledger_dict, erp_event_dict

router = APIRouter()


@router.get('/sync/status')
def status(db=Depends(get_db), u=Depends(current_user)):
    st = db.get(SyncState, 1)
    cutoff = st.last_published_cutoff if st else 0
    counts = {s: db.scalar(select(func.count()).select_from(SyncRound).where(SyncRound.status == s))
              for s in ('syncing', 'reconciling', 'blocked', 'failed', 'published')}
    active = db.scalar(select(SyncRound).where(SyncRound.status.in_(engine.ACTIVE)).order_by(SyncRound.id.desc()))
    hidden = db.scalar(select(func.count()).select_from(ErpEvent).where(ErpEvent.hidden == True))
    return {'state': {'last_published_cutoff': cutoff,
                      'round_counter': st.round_counter if st else 0,
                      'source_batches': st.source_batch_counter if st else 0},
            'source': {'head': erpsource.head(db), 'pending': erpsource.pending_count(db, cutoff), 'hidden': hidden},
            'counts': counts,
            'active_round': round_dict(active) if active else None}


@router.get('/sync/rounds')
def rounds(db=Depends(get_db), u=Depends(current_user)):
    return [round_dict(r) for r in db.scalars(select(SyncRound).order_by(SyncRound.id.desc()).limit(50))]


@router.get('/sync/rounds/{id}')
def round_detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    r = engine.get_round(db, id)
    entries = db.scalars(select(SyncEntry).where(SyncEntry.round_id == r.id).order_by(SyncEntry.event_id))
    return {**round_dict(r), 'entries': [entry_dict(e) for e in entries]}


@router.post('/sync/rounds', status_code=201)
def start(data: RoundStart, db=Depends(get_db), u=Depends(can_write)):
    r = engine.start(db, data.simulate_concurrent)
    record(db, u.email, 'sync.start', {'round': r.round_no, 'cutoff': r.cutoff})
    db.commit()
    return round_dict(r)


@router.post('/sync/rounds/{id}/pause')
def pause(id: int, db=Depends(get_db), u=Depends(can_write)):
    r = engine.pause(db, engine.get_round(db, id))
    record(db, u.email, 'sync.pause', {'round': r.round_no})
    db.commit()
    return round_dict(r)


@router.post('/sync/rounds/{id}/resume')
def resume(id: int, db=Depends(get_db), u=Depends(can_write)):
    r = engine.get_round(db, id)
    engine.resume(db, r)
    record(db, u.email, 'sync.resume', {'round': r.round_no, 'status': r.status})
    db.commit()
    return round_dict(r)


@router.get('/sync/ledger')
def ledger(db=Depends(get_db), u=Depends(current_user)):
    return [ledger_dict(l) for l in db.scalars(select(CorrectionLedger).order_by(CorrectionLedger.voucher))]


@router.get('/erp/events')
def events(db=Depends(get_db), u=Depends(current_user)):
    return [erp_event_dict(e) for e in db.scalars(select(ErpEvent).order_by(ErpEvent.id.desc()).limit(60))]


@router.post('/erp/advance', status_code=201)
def advance(data: SourceAdvance, db=Depends(get_db), u=Depends(can_write)):
    evs = erpsource.generate_batch(db, data.scenario)
    record(db, u.email, 'erp.advance', {'scenario': data.scenario, 'events': len(evs)})
    db.commit()
    return {'events': [erp_event_dict(e) for e in evs]}


@router.post('/erp/repair')
def repair(db=Depends(get_db), u=Depends(can_write)):
    result = erpsource.repair(db)
    record(db, u.email, 'erp.repair', result)
    db.commit()
    return result
