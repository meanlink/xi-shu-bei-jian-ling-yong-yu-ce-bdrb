import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
def round_dict(r):
    return {k:getattr(r,k) for k in ['id','round_no','status','paused','start_after','cutoff','cursor','pages_expected','pages_done','applied','rejected','dataset_id','block_reason','error','created_at','updated_at','finished_at']}
def entry_dict(e):
    return {k:getattr(e,k) for k in ['id','event_id','voucher','version','kind','decision','reason','at']}
def ledger_dict(l):
    return {k:getattr(l,k) for k in ['voucher','version','part','day','demand','revoked','revocation_token','last_event_id','updated_at']}
def erp_event_dict(e):
    return {k:getattr(e,k) for k in ['id','batch_no','voucher','version','kind','part','day','demand','revocation_token','hidden','withdrawn','emitted_at']}
