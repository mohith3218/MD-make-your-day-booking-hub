/* Real installed Chrome + real Flask app. Start phase_2_1_3_qa.py on port 5014
 * and Chrome on debugging port 9214 with a disposable profile before running.
 * All selection changes stay in the browser; no checkout is submitted.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const ChromeQA = require('./phase_2_1_3_chrome.cjs');
const output = path.join(__dirname, '../docs/screenshots/phase-2.1.3-seat-materials');
const sleep = ms => new Promise(resolve=>setTimeout(resolve,ms));
let chrome;
const report = {startedAt:new Date().toISOString(), screens:[], checks:[]};
const run = expression => chrome.evaluate(`document.querySelector('#v').contentWindow.eval(${JSON.stringify(expression)})`);
async function until(expression, message, timeout=60000) {
    const deadline=Date.now()+timeout;
    while (Date.now()<deadline) {
        try {if(await chrome.evaluate(expression))return;} catch(_) {}
        await sleep(500);
    }
    throw new Error(message);
}
async function preview(key, expected) {
    await chrome.call('Page.navigate',{url:`http://127.0.0.1:5014/__qa__/?theater=${key}`});
    await chrome.call('Page.bringToFront');
    await until(`document.querySelector('#v')?.contentWindow?.cinewavePreviewMetrics?.().renderedSeats === ${expected}`,key+' did not build');
    const d=await run('cinewavePreviewDiagnostics()');
    assert.equal(d.fallbackActive,false); assert.equal(d.webglContextLost,false);
    await run('__qa.overview()');
    await until(`document.querySelector('#v')?.contentWindow?.cinewavePreviewMetrics?.().sceneUsableMs > 0`,key+' never rendered a usable frame');
    await sleep(8000);
    const samples=[];
    for(let i=0;i<5;i++){samples.push(await run('cinewavePreviewMetrics()'));await sleep(1100);}
    assert.ok(samples.every(sample=>sample.drawCalls>0 && sample.averageFps>0),key+' renderer was paused during sampling');
    const mappedSeats=await run(`(()=>{let checked=0;seatRegistry.forEach(seat=>{if(seat.instanceParts.every(ref=>ref.mesh.userData.instanceSeatIds[ref.index]===seat.id))checked++;});return checked;})()`);
    assert.equal(mappedSeats,expected);
    const mappings=await run('__qa.sampleSeatIds().map(id=>cinewavePreviewSeatMapping(id))');
    assert.ok(mappings.every(m=>m.mappingValid),key+' invalid seat mapping');
    assert.equal((await run("cinewavePreviewSeatMapping('__missing__')")).found,false);
    const colorCheck=await run(`(() => {
        const errors=[]; let checked=0;
        seatRegistry.forEach(seat=>{
            const expected=seat.isOccupied?matOccupied.color:selectedSeats.has(seat.id)?matSelectedCart.color:
                seat.id===activePOVSeatId?matActivePOV.color:seat.isRecliner?matReclinerAvail.color:seat.isVIP?matVipAvail.color:matStdAvail.color;
            seat.meshes.forEach(ref=>{
                const actual=new THREE.Color();ref.mesh.getColorAt(ref.index,actual);checked++;
                if(!actual.toArray().every(Number.isFinite)||actual.toArray().some((v,i)=>Math.abs(v-expected.toArray()[i])>0.000001))errors.push(seat.id);
            });
        });return {checked,errors};
    })()`);
    assert.deepEqual(colorCheck.errors,[],key+' invalid instance colour buffer');
    const diagnostics=await run('cinewavePreviewDiagnostics()');
    const pipeline=await run('__qa.snapshot().materialPipeline');
    const entry={key,capturedAt:new Date().toISOString(),diagnostics,samples,pipeline,mappedSeats,mappings,colorCheck,lighting:[]};
    report.screens=report.screens.filter(screen=>screen.key!==key);
    report.screens.push(entry);
    for(const mode of ['movie','preshow','house']){
        await chrome.call('Input.dispatchMouseEvent',{type:'mouseMoved',x:4,y:4});
        await run(`__qa.overview();__qa.light('${mode}');__qa.settleCamera()`); await sleep(1500);
        const camera=await run('({position:camera.position.toArray(),target:currentLookAtTarget.toArray(),rotation:camera.quaternion.toArray(),fov:camera.fov})');
        entry.lighting.push({mode,camera});
        await chrome.screenshot(`${key}-${mode==='movie'?'Showtime':mode==='preshow'?'Preshow':'House-lights'}`);
    }
    assert.ok(entry.lighting.every(x=>x.camera.position.every((v,i)=>Math.abs(v-entry.lighting[0].camera.position[i])<0.001)));
    assert.ok(entry.lighting.every(x=>x.camera.rotation.every((v,i)=>Math.abs(v-entry.lighting[0].camera.rotation[i])<0.001) && x.camera.fov===entry.lighting[0].camera.fov));
    if(key==='jagadamba'){
        await run("setCameraPreset('birdseye');__qa.settleCamera()");await sleep(1500);
        await chrome.screenshot('Jagadamba-886-seat-birdseye');
    }
    console.log(`${key}: ${expected} mappings pass, lighting screenshots saved; FPS samples ${samples.map(s=>s.averageFps).join(', ')}`);
    await fs.writeFile(path.join(output,'browser-results.json'),JSON.stringify(report,null,2));
}
async function main(){
    if(process.argv[2]){
        Object.assign(report,JSON.parse(await fs.readFile(path.join(output,'browser-results.json'),'utf8')));
        report.repeatStartedAt=new Date().toISOString();
        delete report.failure;
    }
    chrome=await ChromeQA.connect();
    const {windowId}=await chrome.call('Browser.getWindowForTarget');
    await chrome.call('Browser.setWindowBounds',{windowId,bounds:{windowState:'normal'}});
    await chrome.call('Page.bringToFront');
    await chrome.call('Emulation.setFocusEmulationEnabled',{enabled:true});
    report.browser=await chrome.call('Browser.getVersion');
    for(const [key,count] of [['melody',774],['inox',200],['jagadamba',886]]){
        if(process.argv[2] && key!==process.argv[2])continue;
        await preview(key,count);
        if(key==='inox'){
            await run('__qa.closeup(false)');await sleep(1800);await chrome.screenshot('Standard-seat-close-up');
            await run('__qa.closeup(true)');await sleep(1800);await chrome.screenshot('Premium-seat-close-up');
        }
    }
    if(!process.argv[2] || process.argv[2]==='recliner'){
        await preview('recliner',58);
        await run('__qa.closeup(true)');await sleep(1800);await chrome.screenshot('Recliner-seat-close-up');
        await run(`(()=>{const seats=[...seatRegistry.values()].filter(s=>s.isRecliner).sort((a,b)=>Math.abs(a.worldPos.x)-Math.abs(b.worldPos.x));
            const seat=seats[2];cameraMode='qa-detail';
            cameraTargetPos.copy(seat.group.localToWorld(new THREE.Vector3(1,1.4,-1.4)));
            desiredLookAtTarget.copy(seat.group.localToWorld(new THREE.Vector3(0,0.22,-0.72)));
            setCameraFieldOfView(70);__qa.settleCamera();updateSeatTelemetryUI(seat);
            document.querySelector('#metrics-panel').style.display='none';
            document.querySelector('#minimap-drawer').style.display='none';})()`);
        await sleep(1500);await chrome.screenshot('Recliner-footrest-detail');
    }
    console.log('All material captures complete');
}
main().catch(error=>{report.failure=String(error.stack||error);console.error(error);process.exitCode=1;})
    .finally(async()=>{await fs.writeFile(path.join(output,'browser-results.json'),JSON.stringify(report,null,2));if(chrome)chrome.ws.close();});
