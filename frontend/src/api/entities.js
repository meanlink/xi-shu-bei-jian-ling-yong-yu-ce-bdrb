import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const sync={status:()=>api('/sync/status'),rounds:()=>api('/sync/rounds'),round:id=>api('/sync/rounds/'+id),start:data=>api('/sync/rounds',{method:'POST',body:JSON.stringify(data)}),pause:id=>api('/sync/rounds/'+id+'/pause',{method:'POST'}),resume:id=>api('/sync/rounds/'+id+'/resume',{method:'POST'}),ledger:()=>api('/sync/ledger')};
export const erp={events:()=>api('/erp/events'),advance:data=>api('/erp/advance',{method:'POST',body:JSON.stringify(data)}),repair:()=>api('/erp/repair',{method:'POST'})};
