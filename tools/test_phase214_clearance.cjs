const Q=require('./phase_2_1_3_chrome.cjs'),fs=require('node:fs/promises'),path=require('node:path');
const wait=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{const q=await Q.connect();try{
 const run=s=>q.evaluate(`document.querySelector('#v').contentWindow.eval(${JSON.stringify(s)})`),records=[];
 for(const key of ['inox','melody','jagadamba','recliner','couple']){
  await q.call('Page.navigate',{url:'http://127.0.0.1:5014/__qa__/?theater='+key});
  let ready=false;for(let i=0;i<100;i++){try{if(await run('typeof __qa!=="undefined" && cinewavePreviewMetrics().sceneUsableMs>0')){ready=true;break;}}catch{}await wait(300);}if(!ready)throw Error('Preview unavailable');
  await run(await fs.readFile(path.join(__dirname,'phase214-clearance.js'),'utf8'));
  const ids=await run(`[...new Set([...__qa.sampleSeatIds(),...currentAudi.rowDefs.flatMap(row=>row.aislesAfter.flatMap(n=>[row.label+n,row.label+(n+1)]))])].filter(id=>seatRegistry.has(id))`);
  const samples=[];
  for(const id of ids){const reclining=await run(`seatRegistry.get(${JSON.stringify(id)}).isRecliner`);for(const level of reclining?[0,1,2]:[0]){
   samples.push(await run(`activePOVSeatId=${JSON.stringify(id)};reclineLevel=${level};refreshAllSeatMaterials();({...phase214Clearance(${JSON.stringify(id)}),level:${level}})`));
  }}
  records.push({key,samples});console.log(key,'checked',samples.length,'poses;',samples.filter(s=>s.collisions.length||s.aisleViolations.length).length,'overlap/aisle failures');
 }
 await fs.writeFile('docs/screenshots/phase-2.1.4-premium-seats/clearance.json',JSON.stringify(records,null,2));
 if(records.some(r=>r.samples.some(s=>s.collisions.length||s.aisleViolations.length)))throw Error('Chair clearance failed; inspect clearance.json');
}finally{q.ws.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
