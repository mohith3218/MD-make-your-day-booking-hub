/* QA-only script injected by phase_2_1_3_qa.py, never by the production app. */
(() => {
    const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
    const save = data => fetch('/__qa__/results', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
    });
    const status = text => {
        const el = window.top.document.getElementById('status');
        if (el) el.textContent = text;
    };
    if (!location.pathname.endsWith('/vr-preview')) return;
    window.__qa = {
        light(mode) {
            for (let i = 0; i < 3 && lightingMode !== mode; i++) cycleHouseLights();
        },
        overview() { setCameraMode('overview'); },
        settleCamera() {
            hideHoverPreview();clearTimeout(hoverTimer);clearTimeout(hoverTelemetryTimer);clearTimeout(hoverEchoTimer);
            tooltipEl.classList.add('hidden');
            yawOffset=targetYawOffset=0;pitchOffset=targetPitchOffset=0;
            camera.position.copy(cameraTargetPos);currentLookAtTarget.copy(desiredLookAtTarget);
            camera.lookAt(currentLookAtTarget);
        },
        sampleSeatIds() {
            const seats=[...seatRegistry.values()], byDepth=[...seats].sort((a,b)=>a.worldPos.z-b.worldPos.z);
            return [...new Set([byDepth[0],byDepth[Math.floor(byDepth.length/2)],byDepth.at(-1),
                seats.reduce((a,b)=>a.worldPos.x<b.worldPos.x?a:b),seats.reduce((a,b)=>a.worldPos.x>b.worldPos.x?a:b),
                seats.find(s=>s.isVIP),seats.find(s=>s.isRecliner)].filter(Boolean).map(s=>s.id))];
        },
        closeup(premium) {
            this.light('house');
            const seats = [...seatRegistry.values()];
            const category = seats.filter(s => premium ? s.isVIP || s.isRecliner : !s.isVIP && !s.isRecliner);
            const centre = [...category].sort((a,b)=>Math.abs(a.worldPos.x)-Math.abs(b.worldPos.x));
            const seat = centre[Math.min(2, centre.length-1)] || seats[0];
            selectedSeats.clear();
            activePOVSeatId = '';
            refreshAllSeatMaterials();
            this.settleCamera();
            updateSeatTelemetryUI(seat);
            cameraMode = 'qa-detail';
            // Inspect existing geometry from its screen-facing side; no chair is rebuilt.
            cameraTargetPos.copy(seat.group.localToWorld(new THREE.Vector3(1.4, 2.5, -3.4)));
            desiredLookAtTarget.copy(seat.worldPos).add(new THREE.Vector3(0, 0.55, 0));
            targetYawOffset = targetPitchOffset = 0;
            setCameraFieldOfView(43);
            activePOVSeatId = seat.id;
            updateSeatTelemetryUI(seat);
            // Keep the inspected upholstery at its category colour, rather
            // than replacing it with the active-POV tint for this QA close-up.
            activePOVSeatId = '';
            refreshAllSeatMaterials();
            status(`${seat.id} · ${seat.tier} · ₹${seat.price}`);
        },
        snapshot() {
            return {diagnostics: cinewavePreviewDiagnostics(),
                materialPipeline: {outputEncoding: renderer.outputEncoding,
                    textureEncoding: seatFabricTexture.encoding, toneMapping: renderer.toneMapping,
                    exposure: renderer.toneMappingExposure,
                    standard: matStdAvail.color.toArray(), premium: matVipAvail.color.toArray(),
                    recliner: matReclinerAvail.color.toArray(),
                    batches: seatInstanceMeshes.map(m => ({count: m.count, roughness: m.material.roughness}))},
                rows: currentAudi.rowDefs.map(r => ({label:r.label, count:r.count, category:r.className})),
                mapping: this.sampleSeatIds().map(id => cinewavePreviewSeatMapping(id))};
        }
    };
    window.addEventListener('load', async () => {
        await wait(8000);
        const samples = [];
        for (let i = 0; i < 5; i++) { samples.push(cinewavePreviewMetrics()); await wait(1100); }
        await save({name: 'renderer-' + location.pathname.split('/')[2],
            capturedAt: new Date().toISOString(), userAgent:navigator.userAgent,
            viewport:[innerWidth,innerHeight], samples, ...window.__qa.snapshot()});
        status(`${currentAudi.name}: ${seatRegistry.size} seats · QA saved`);
    });
})();
