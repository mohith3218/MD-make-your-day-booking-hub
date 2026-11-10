/* QA-only conservative collision test for transformed component boxes.
 * SAT includes face normals and edge cross-products, including affine shear.
 * A separated bounding box proves the contained chair meshes do not intersect.
 */
window.phase214Clearance = function(seatId) {
    const seat=seatRegistry.get(seatId), axes=[];
    const box = part => {
        const g=part.mesh.geometry;if(!g.boundingBox)g.computeBoundingBox();
        const m=new THREE.Matrix4();part.mesh.getMatrixAt(part.index,m);
        const center=g.boundingBox.getCenter(new THREE.Vector3()).applyMatrix4(m);
        const half=g.boundingBox.getSize(new THREE.Vector3()).multiplyScalar(0.5);
        const edges=[0,1,2].map(i=>new THREE.Vector3().setFromMatrixColumn(m,i).multiplyScalar(half.getComponent(i)));
        return {center,edges};
    };
    const overlaps=(a,b)=>{
        axes.length=0;
        for(const edges of [a.edges,b.edges])for(let i=0;i<3;i++)axes.push(new THREE.Vector3().crossVectors(edges[(i+1)%3],edges[(i+2)%3]));
        for(const x of a.edges)for(const y of b.edges)axes.push(new THREE.Vector3().crossVectors(x,y));
        const delta=b.center.clone().sub(a.center);
        return axes.every(axis=>{
            if(axis.lengthSq()<1e-14)return true;axis.normalize();
            const radius=edges=>edges.reduce((r,e)=>r+Math.abs(e.dot(axis)),0);
            return Math.abs(delta.dot(axis)) < radius(a.edges)+radius(b.edges)-0.003;
        });
    };
    const solid=p=>!p.kind.includes('state-') && p.mesh.userData.partKind!=='stitch';
    const parts=seat.instanceParts.filter(solid).map(p=>({name:p.componentName,box:box(p)}));
    const collisions=[];
    for(const other of seatRegistry.values()){
        if(other===seat||other.worldPos.distanceTo(seat.worldPos)>2.5)continue;
        for(const p of other.instanceParts.filter(solid)){
            const b=box(p);
            for(const a of parts)if(overlaps(a.box,b))collisions.push({part:a.name,neighbor:other.id,other:p.componentName});
        }
    }
    const row=currentAudi.rowDefs[seat.rowIndex], aisleViolations=[];
    const halfCell=Number(row.seatSpan||1)*0.31;
    for(const p of parts){
        const radius=p.box.edges.reduce((r,e)=>r+Math.abs(e.x),0);
        if(row.aislesAfter.includes(seat.num) && p.box.center.x+radius>seat.worldPos.x+halfCell+0.003)aisleViolations.push(p.name+':right');
        if(row.aislesAfter.includes(seat.num-1) && p.box.center.x-radius<seat.worldPos.x-halfCell-0.003)aisleViolations.push(p.name+':left');
    }
    return {seatId,checkedParts:parts.length,collisions,aisleViolations};
};
