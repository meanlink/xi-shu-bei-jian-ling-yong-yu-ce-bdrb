import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report, SyncRound
from src.services.business import analyze
from src.services.reports import deliver
from src.services import sync as sync_engine
from src.services.audit import record
logging.basicConfig(level=logging.INFO)
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()
def sync_step(round_id):
    # 单轮单步：拉一页、提交检查点；异常整轮标记失败，可从游标恢复
    with Session() as db:
        r=db.get(SyncRound,round_id)
        if not r:return
        try:
            sync_engine.step(db,r)  # 引擎内部按页提交检查点
            if r.status=='published':record(db,'worker','sync.published',{'round':r.round_no,'cutoff':r.cutoff,'dataset':r.dataset_id})
            elif r.status=='blocked':record(db,'worker','sync.blocked',{'round':r.round_no,'reason':r.block_reason})
            db.commit()
        except Exception as e:
            db.rollback()
            logging.exception('Sync step failed')
            r=db.get(SyncRound,round_id)
            if r and r.status!='published':
                r.status='failed';r.error=str(e)[:490];r.updated_at=time.time()
                record(db,'worker','sync.failed',{'round':r.round_no,'error':r.error})
                db.commit()
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        active=list(db.scalars(select(SyncRound.id).where(SyncRound.status=='syncing',SyncRound.paused==False).limit(1)))
    for round_id in active:sync_step(round_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        db.commit()
    # 同步轮恢复：核对中的轮次重新对账（日历已生成但进度未保存时按批次名找回）；待接续的由 tick 接续
    with Session() as db:
        for rnd in db.scalars(select(SyncRound).where(SyncRound.status=='reconciling')):
            try:
                sync_engine.reconcile(db,rnd);db.commit()
                record(db,'worker','sync.recovered',{'round':rnd.round_no,'status':rnd.status});db.commit()
            except Exception:
                db.rollback();logging.exception('Sync reconcile recovery failed')
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
