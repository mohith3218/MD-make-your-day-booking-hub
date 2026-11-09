/* Trusted Chrome pointer input against the actual booking page and WebGL canvas. */
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const ChromeQA=require('./phase_2_1_3_chrome.cjs');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let chrome;
const result={startedAt:new Date().toISOString(),checks:[]};
const book=expr=>chrome.evaluate(`document.querySelector('#v').contentWindow.eval(${JSON.stringify(expr)})`);
const preview=expr=>book(`document.querySelector('#vr-inline-frame').contentWindow.eval(${JSON.stringify(expr)})`);
async function until(fn,message){const end=Date.now()+45000;while(Date.now()<end){try{if(await fn())return;}catch(_){}await sleep(300);}throw new Error(message);}
async function click(x,y){
 await chrome.call('Input.dispatchMouseEvent',{type:'mouseMoved',x,y});
 await chrome.call('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'left',clickCount:1});
 await chrome.call('Input.dispatchMouseEvent',{type:'mouseReleased',x,y,button:'left',clickCount:1});
 await sleep(350);
}
async function seat2D(id){
 await book(`toggleTheaterView('2d');document.querySelector('.seat[data-seat="${id}"]').scrollIntoView({block:'center',inline:'center'})`);
 const p=await chrome.evaluate(`(()=>{const f=document.querySelector('#v'),b=f.contentDocument.querySelector('.seat[data-seat="${id}"]');const a=f.getBoundingClientRect(),r=b.getBoundingClientRect();return{x:a.x+r.x+r.width/2,y:a.y+r.y+r.height/2,disabled:b.disabled}})()`);
 await click(p.x,p.y);return p;
}
async function state(){
 return {book:await book(`({ids:document.querySelector('#selected_seats_input').value.split(',').filter(Boolean),total:Number(document.querySelector('#total-price').textContent.replace(/[^0-9.]/g,'')),active:activePovSeat?.dataset.seat})`),
  preview:await preview(`({ids:[...selectedSeats],active:activePOVSeatId,title:document.querySelector('#metric-seat-title').textContent,category:document.querySelector('#metric-tier-badge').textContent,price:document.querySelector('#metric-seat-price-value').textContent,cameraMode,target:cameraTargetPos.toArray(),eye:seatRegistry.get(activePOVSeatId)?.eyePos.toArray()})`)};
}
async function canvasPoint(id){
 const point=await preview(`(()=>{
    const ray=new THREE.Raycaster(),ndc=new THREE.Vector2();
    for(let y=innerHeight*0.32;y<innerHeight-30;y+=6)for(let x=30;x<innerWidth-30;x+=6){
      if(document.elementFromPoint(x,y)!==renderer.domElement)continue;
      ndc.set(x/innerWidth*2-1,-y/innerHeight*2+1);ray.setFromCamera(ndc,camera);
      const hit=ray.intersectObjects(interactiveSeatMeshes,false)[0];
      if(hit){const found=seatIdFromHit(hit);if(${id?`found===${JSON.stringify(id)}`:"found && !seatRegistry.get(found).isOccupied && !selectedSeats.has(found)"})return{x,y,id:found};}
    }return null;
 })()`);
 assert.ok(point,'No visible canvas point for '+(id||'available seat'));
 const offset=await chrome.evaluate(`(()=>{const a=document.querySelector('#v').getBoundingClientRect(),b=document.querySelector('#v').contentDocument.querySelector('#vr-inline-frame').getBoundingClientRect();return{x:a.x+b.x,y:a.y+b.y}})()`);
 return {...point,x:point.x+offset.x,y:point.y+offset.y};
}
async function main(){
 chrome=await ChromeQA.connect();
 chrome.screenshot=async name=>{const capture=await chrome.call('Page.captureScreenshot',{format:'png'});await fs.writeFile(path.join(__dirname,'../docs/screenshots/phase-2.1.4-premium-seats',name+'.png'),Buffer.from(capture.data,'base64'));};
 const {windowId}=await chrome.call('Browser.getWindowForTarget');
 await chrome.call('Browser.setWindowBounds',{windowId,bounds:{windowState:'normal'}});
 await chrome.call('Page.bringToFront');
 await chrome.call('Emulation.setFocusEmulationEnabled',{enabled:true});
 await chrome.call('Page.navigate',{url:'http://127.0.0.1:5014/__qa__/?theater=inox&booking=1'});
 await chrome.call('Page.bringToFront');
 await until(async()=>await preview('cinewavePreviewMetrics().renderedSeats===200'),'Booking preview never built');
 await seat2D('E8');
 await until(async()=> (await state()).preview.ids.includes('E8'),'2D selection did not reach 3D');
 let s=await state();assert.deepEqual(s.book.ids,['E8']);assert.equal(s.preview.active,'E8');
 assert.equal(s.preview.title,'Row E · Seat 8');assert.equal(s.preview.category,'Classic');
 assert.equal(s.preview.cameraMode,'seat');assert.deepEqual(s.preview.target,s.preview.eye);
 result.checks.push({name:'2D to 3D, exact ID/details/category/price/camera',state:s});
 await seat2D('E8');await until(async()=>!(await state()).preview.ids.length,'Deselect failed');
 await seat2D('A8');await until(async()=>(await state()).preview.ids.includes('A8'),'Premium selection failed');
 s=await state();assert.equal(s.preview.category,'Prime');assert.equal(s.preview.price,'₹189');
 assert.equal(s.book.total,189);
 result.checks.push({name:'Deselect and change category to Prime',state:s});
 await seat2D('E8');await until(async()=>(await state()).preview.ids.length===2,'Multi-seat cart failed');
 s=await state();assert.equal(s.book.total,324);assert.equal(new Set(s.book.ids).size,2);
 result.checks.push({name:'Mixed category cart prices and no duplicates',state:s});
 for(const id of ['E1','E2']){
  const before=(await state()).book.ids;const p=await seat2D(id);assert.equal(p.disabled,true);
  assert.deepEqual((await state()).book.ids,before);
  assert.equal(await preview(`seatRegistry.get('${id}').isOccupied`),true);
  await book(`toggleTheaterView('3d');document.querySelector('#vr-inline-frame').scrollIntoView({block:'center'})`);
  await preview(`(()=>{const seat=seatRegistry.get('${id}');cameraMode='qa-detail';
    cameraTargetPos.copy(seat.group.localToWorld(new THREE.Vector3(0,2.5,-3.4)));
    desiredLookAtTarget.copy(seat.worldPos).add(new THREE.Vector3(0,0.55,0));
    setCameraFieldOfView(43);__qa.settleCamera();})()`);
  await sleep(1000);
  const blockedPoint=await preview(`(()=>{const seat=seatRegistry.get('${id}');
    const point=seat.group.localToWorld(new THREE.Vector3(0,1,0.3)).project(camera);
    const ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2(point.x,point.y),camera);
    const hit=ray.intersectObjects(interactiveSeatMeshes,false)[0];
    return {x:(point.x+1)*innerWidth/2,y:(1-point.y)*innerHeight/2,id:hit&&seatIdFromHit(hit)};})()`);
  assert.equal(blockedPoint.id,id,'Unavailable fixture must actually be hit');
  const off=await chrome.evaluate(`(()=>{const a=document.querySelector('#v').getBoundingClientRect(),b=document.querySelector('#v').contentDocument.querySelector('#vr-inline-frame').getBoundingClientRect();return{x:a.x+b.x,y:a.y+b.y}})()`);
  await click(blockedPoint.x+off.x,blockedPoint.y+off.y);
  await sleep(350);assert.deepEqual((await state()).book.ids,before);
  const mapping=await preview(`cinewavePreviewSeatMapping('${id}')`);
  assert.equal(mapping.mappingValid,true);assert.equal(mapping.unavailable,true);
  result.checks.push({name:(id==='E1'?'Booked':'Held')+' seat blocked in 2D and 3D',seat:id,mapping});
 }
 await book(`toggleTheaterView('3d');document.querySelector('#vr-inline-frame').scrollIntoView({block:'center'})`);
 await preview(`setCameraMode('overview');__qa.light('house')`);await sleep(2200);
 const p=await canvasPoint();await click(p.x,p.y);
 await until(async()=>(await state()).book.ids.includes(p.id),'Canvas raycast did not reach 2D');
 s=await state();assert.equal(s.book.active,p.id);assert.equal(s.preview.active,p.id);
 assert.ok(await book(`document.querySelector('.seat-btn[data-seat="${p.id}"]').classList.contains('seat-sel')`));
 assert.equal(new Set(s.book.ids).size,3);
 result.checks.push({name:'Trusted 3D canvas click to exact 2D seat',clicked:p.id,state:s});
 await preview(`setCameraMode('overview')`);await sleep(1800);
 await chrome.call('Input.dispatchMouseEvent',{type:'mouseMoved',x:4,y:4});
 await preview('__qa.settleCamera()');
 await preview(`(()=>{const seat=seatRegistry.get('E8');cameraMode='qa-detail';
    cameraTargetPos.copy(seat.group.localToWorld(new THREE.Vector3(1.4,2.5,-3.4)));
    desiredLookAtTarget.copy(seat.worldPos).add(new THREE.Vector3(0,0.55,0));
    setCameraFieldOfView(43);__qa.light('house');__qa.settleCamera();})()`);
 await sleep(1500);
 await chrome.screenshot('Selected-seat-highlighting');
 // Show both actual application surfaces together for the synchronization
 // evidence image. Only QA layout visibility changes; the app DOM is retained.
 await book(`(()=>{const wrap=document.createElement('div');wrap.style.cssText='position:fixed;inset:75px 10px 10px;z-index:300;display:grid;grid-template-columns:1fr 1fr;gap:12px;background:#0b0b12';document.body.append(wrap);
    const view=document.querySelector('#ar-theater-wrapper'),map=document.querySelector('#seating-viewport');
    wrap.append(view,map);view.style.cssText='position:relative;width:100%;height:100%;';
    map.classList.remove('hidden');map.style.cssText='height:100%;overflow:auto;padding:12px;';window.dispatchEvent(new Event('resize'));})()`);
 await until(async()=>await preview("typeof __qa==='object' && cinewavePreviewMetrics().renderedSeats===200"),'Rearranged QA iframe did not reload');
 await book('postVRPreviewState()');
 await until(async()=>(await state()).preview.ids.length===3,'Rearranged preview lost the shared cart');
 await preview("__qa.overview();__qa.light('house');__qa.settleCamera()");await sleep(1000);
 await chrome.evaluate(`document.querySelector('#status').textContent='PASS: 2D and 3D share the same three cart IDs and total'`);
 await chrome.screenshot('2D-3D-seat-synchronization');
 console.log('PASS',result.checks.map(x=>x.name));
}
main().catch(error=>{result.failure=String(error.stack||error);console.error(error);process.exitCode=1;})
 .finally(async()=>{await fs.writeFile(path.join(__dirname,'../docs/screenshots/phase-2.1.4-premium-seats/synchronization-results.json'),JSON.stringify(result,null,2));if(chrome)chrome.ws.close();});
