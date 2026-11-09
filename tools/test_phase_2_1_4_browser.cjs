const Q=require('./phase_2_1_3_chrome.cjs'),fs=require('node:fs/promises'),path=require('node:path');
const wait=ms=>new Promise(r=>setTimeout(r,ms));
let client;
(async()=>{const q=client=await Q.connect(),out=path.join(__dirname,'../docs/screenshots/phase-2.1.4-premium-seats');await fs.mkdir(out,{recursive:true});
const {windowId}=await q.call('Browser.getWindowForTarget');await q.call('Browser.setWindowBounds',{windowId,bounds:{windowState:'normal'}});await q.call('Emulation.setFocusEmulationEnabled',{enabled:true});
const run=s=>q.evaluate(`document.querySelector('#v').contentWindow.eval(${JSON.stringify(s)})`);
const shot=async n=>{const r=await q.call('Page.captureScreenshot',{format:'png'});await fs.writeFile(path.join(out,n+'.png'),Buffer.from(r.data,'base64'));};
const records=[];const baseline=process.argv[2]==='baseline',integrityOnly=process.argv[2]==='integrity';
for(const key of baseline?['jagadamba']:process.argv[2] && !integrityOnly?[process.argv[2]]:['inox','melody','jagadamba','recliner','couple']){
 await q.call('Page.navigate',{url:'http://127.0.0.1:5014/__qa__/?theater='+key});await q.call('Browser.setWindowBounds',{windowId,bounds:{windowState:'normal'}});await q.call('Page.bringToFront');
 for(let i=0;i<100;i++){try{if(await run('typeof __qa!=="undefined" && cinewavePreviewMetrics().sceneUsableMs>0'))break;}catch{}await wait(300);}
 await run('__qa.overview();__qa.light("house");__qa.settleCamera()');await wait(integrityOnly?200:8000);
 const samples=[];for(let i=0;i<(integrityOnly?0:5);i++){samples.push(await run('cinewavePreviewMetrics()'));await wait(1100);}
 const integrity=await run(`(()=>{let checked=0;const errors=[];seatRegistry.forEach(s=>{checked++;if(s.instanceParts.some(p=>p.mesh.userData.instanceSeatIds[p.index]!==s.id))errors.push(s.id);s.meshes.forEach(p=>{const c=new THREE.Color();p.mesh.getColorAt(p.index,c);if(!c.toArray().every(Number.isFinite))errors.push(s.id);});});seatInstanceMeshes.forEach(mesh=>{for(let i=0;i<mesh.count;i++)if(!seatRegistry.has(mesh.userData.instanceSeatIds[i]))errors.push("unmapped draw instance "+i);});return{checked,errors};})()`);if(integrity.errors.length)throw Error('Instance integrity failure');
 if(!integrityOnly && !samples.some(s=>s.averageFps>0))throw Error('Renderer paused: no usable FPS samples');
 const mapping=await run('__qa.sampleSeatIds().map(cinewavePreviewSeatMapping)');if(mapping.some(m=>!m.mappingValid))throw Error('mapping failure');
 records.push({key,capturedAt:new Date().toISOString(),browser:await q.evaluate('navigator.userAgent'),samples,mapping,integrity});if(integrityOnly){await fs.writeFile(path.join(out,"integrity.json"),JSON.stringify(records,null,2));console.log(key,"integrity passed",integrity.checked);continue;}await shot((baseline?'before-':'after-')+key+'-overview');
 if(!baseline && ['inox','melody','jagadamba'].includes(key)){
   records.at(-1).lighting=[];
   for(const mode of ['movie','preshow','house']){
     await run(`__qa.overview();__qa.light('${mode}');__qa.settleCamera()`);await wait(2200);
     const metrics=await run('cinewavePreviewMetrics()');
     if(!(metrics.averageFps>0 && metrics.sceneUsableMs>0))throw Error('Invalid lighting metrics: '+key+' '+mode);
     records.at(-1).lighting.push({mode,metrics});await shot(key+'-'+mode+'-overview');
   }
 }
 if(!baseline){await run('__qa.closeup(false)');await wait(800);await shot(key+'-standard-close');await run('__qa.closeup(true)');await wait(800);await shot(key+'-premium-close');
 if(key==='inox'){
 const detailId=await run('[...seatRegistry.values()].filter(s=>!s.isVIP&&!s.isRecliner&&!s.isOccupied).sort((a,b)=>a.worldPos.z-b.worldPos.z||Math.abs(a.worldPos.x)-Math.abs(b.worldPos.x))[0].id');
 for(const [name,pos] of [['Standard-seat-front-view',[0,1.9,-1.8]],['Standard-seat-side-view',[1.5,1.6,-0.55]],['Seat-material-details',[0.65,1.7,-1.25]]]){
   await run(`__qa.closeup(false,${JSON.stringify(detailId)});(()=>{const s=seatRegistry.get(${JSON.stringify(detailId)});cameraTargetPos.copy(s.group.localToWorld(new THREE.Vector3(...${JSON.stringify(pos)})));desiredLookAtTarget.copy(s.group.localToWorld(new THREE.Vector3(0,0.85,0)));__qa.settleCamera()})()`);await wait(350);await shot(name);
 }
 records.at(-1).stateColors=await run(`(()=>{const a=seatRegistry.get('E1'),b=seatRegistry.get('E2'),s=seatRegistry.get(${JSON.stringify(detailId)});const read=s=>{const p=s.instanceParts.find(p=>p.kind==='state-back'),c=new THREE.Color();p.mesh.getColorAt(p.index,c);return{status:s.status,color:c.toArray(),mapping:cinewavePreviewSeatMapping(s.id)}};const category=s.isVIP?matVipAvail:matStdAvail;selectedSeats.add(s.id);refreshAllSeatMaterials();const marker=read(s),c=new THREE.Color();s.meshes[0].mesh.getColorAt(s.meshes[0].index,c);const selected=c.toArray();selectedSeats.delete(s.id);activePOVSeatId='';refreshAllSeatMaterials();s.meshes[0].mesh.getColorAt(s.meshes[0].index,c);return{booked:read(a),held:read(b),selectedMarker:marker,selectedUpholstery:selected,restored:c.toArray(),category:category.color.toArray()}})()`);
 await run(`__qa.closeup(false,${JSON.stringify(detailId)});selectedSeats.add(${JSON.stringify(detailId)});refreshAllSeatMaterials();__qa.settleCamera()`);await shot('Selected-seat-highlighting');
 for(const [w,h] of [[1920,1080],[1366,768],[390,844]]){await q.call('Emulation.setDeviceMetricsOverride',{width:w,height:h,deviceScaleFactor:1,mobile:false});await run("if(innerWidth<500){document.querySelector('#metrics-panel').classList.add('details-collapsed');document.querySelector('#minimap-drawer').style.display='none';} __qa.overview();__qa.settleCamera()");await wait(800);await shot('overview-'+w);}
 await q.call('Emulation.setDeviceMetricsOverride',{width:1600,height:900,deviceScaleFactor:1,mobile:false});
 for(const [label,expr] of [['front','0'],['middle','Math.floor(seats.length/2)'],['rear','seats.length-1']]){await run(`(()=>{const seats=[...seatRegistry.values()].sort((a,b)=>a.worldPos.z-b.worldPos.z);const s=seats[${expr}];selectAndFlyToSeat(s.row,s.num,false);__qa.settleCamera();})()`);await wait(800);await shot(label+'-seat-POV');}}
 if(key==='couple'){const id=await run('[...seatRegistry.values()].find(s=>s.instanceParts.filter(p=>p.kind==="back").length===2)?.id');if(!id)throw Error('No real couple seat found');await run('__qa.closeup(true,'+JSON.stringify(id)+')');await wait(900);await shot('Couple-seat-close-up');records.at(-1).couple=await run('cinewavePreviewSeatMapping('+JSON.stringify(id)+')');}
 if(key==='recliner'){const motion=[];for(const level of [0,1,2]){await run(`(()=>{const s=[...seatRegistry.values()].filter(s=>s.isRecliner).sort((a,b)=>a.worldPos.z-b.worldPos.z||Math.abs(a.worldPos.x)-Math.abs(b.worldPos.x))[0];__qa.closeup(true,s.id);activePOVSeatId=s.id;setSeatRecline(${level});cameraTargetPos.copy(s.group.localToWorld(new THREE.Vector3(1.3,2.1,-1.3)));desiredLookAtTarget.copy(s.group.localToWorld(new THREE.Vector3(0,0.6,-0.1)));setCameraFieldOfView(54);__qa.settleCamera();})()`);motion.push(await run('[...seatRegistry.values()].find(s=>s.id===activePOVSeatId).instanceParts.filter(p=>["back","footrest","headrest"].includes(p.kind)).map(p=>({kind:p.kind,position:p.position.toArray(),angle:p.rotationX}))'));await shot('recliner-'+level);}records.at(-1).motion=motion;}}
 console.log(key,'captured');await fs.writeFile(path.join(out,baseline?'before.json':process.argv[2]?process.argv[2]+'-detail.json':'after.json'),JSON.stringify(records,null,2));}
 if(q.errors.length)throw Error('Chrome runtime exceptions: '+JSON.stringify(q.errors));
 q.ws.close();})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>client?.ws.close());
