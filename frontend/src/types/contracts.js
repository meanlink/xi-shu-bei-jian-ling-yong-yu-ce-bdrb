/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{id:number,round_no:number,status:string,paused:boolean,start_after:number,cutoff:number,cursor:number,pages_expected:number,pages_done:number,applied:number,rejected:number,dataset_id:number|null,block_reason:string,error:string}} SyncRound */
/** @typedef {{id:number,event_id:number,voucher:string,version:number,kind:string,decision:string,reason:string,at:number}} SyncEntry */
/** @typedef {{voucher:string,version:number,part:string,day:string,demand:number,revoked:boolean,revocation_token:string}} LedgerRow */
/** @typedef {{id:number,batch_no:number,voucher:string,version:number,kind:string,part:string,day:string,demand:number,revocation_token:string,hidden:boolean,withdrawn:boolean}} ErpEvent */
export {};
