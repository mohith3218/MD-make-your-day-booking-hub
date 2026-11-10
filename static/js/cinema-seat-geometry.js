/* Shared procedural chair assets; works with the locally bundled Three r128. */
(function(root) {
    'use strict';
    function roundedPadding(THREE, widthSegments, heightSegments, exponent) {
        const geometry = new THREE.SphereGeometry(1, widthSegments, heightSegments);
        const p = geometry.attributes.position, n = geometry.attributes.normal;
        const uv = geometry.attributes.uv, normal = new THREE.Vector3();
        const rounded = v => Math.sign(v) * Math.pow(Math.abs(v), exponent);
        const gradient = v => Math.sign(v) * Math.pow(Math.abs(v), 2 / exponent - 1);
        for (let i = 0; i < p.count; i++) {
            const x = rounded(p.getX(i)), y = rounded(p.getY(i)), z = rounded(p.getZ(i));
            p.setXYZ(i, x, y, z);
            normal.set(gradient(x), gradient(y), gradient(z)).normalize();
            n.setXYZ(i, normal.x, normal.y, normal.z);
            const axis = [Math.abs(normal.x), Math.abs(normal.y), Math.abs(normal.z)];
            const dominant = axis.indexOf(Math.max(...axis));
            uv.setXY(i, ((dominant === 0 ? z : x) + 1)/2, ((dominant === 1 ? z : y) + 1)/2);
        }
        return geometry;
    }
    function padding(THREE, detail = 'near') {
        return roundedPadding(THREE, detail === 'far' ? 8 : 12, detail === 'far' ? 6 : 8, 0.64);
    }
    function backrest(THREE, detail = 'near') {
        // Seven rounded cross-sections give a tapered crown, shoulder wings
        // and a lumbar curve. Indexed vertices replace the dense extrusion.
        const rings = [
            [0.02,0.35,0.055], [0.10,0.45,0.095], [0.30,0.47,0.105],
            [0.60,0.48,0.105], [0.90,0.47,0.10], [1.14,0.42,0.085], [1.24,0.30,0.045]
        ];
        const segments = detail === 'far' ? 8 : 12, positions = [], uvs = [], indices = [];
        const soft = v => Math.sign(v)*Math.pow(Math.abs(v),0.72);
        rings.forEach(([y,width,depth], row) => {
            for (let j = 0; j < segments; j++) {
                const angle = j*Math.PI*2/segments;
                const x = width*soft(Math.cos(angle));
                const z = 0.07 + depth*soft(Math.sin(angle))
                    + 0.065*Math.pow((y-0.58)/0.7,2) + 0.025*Math.pow(x/0.48,2);
                positions.push(x,y,z); uvs.push(x+0.5,y/1.26);
                if (row < rings.length-1) {
                    const a = row*segments+j, b = a+segments;
                    const d = row*segments+(j+1)%segments, c = d+segments;
                    indices.push(a,b,c,a,c,d);
                }
            }
        });
        for (const top of [false,true]) {
            const row = top ? rings.length-1 : 0, y = rings[row][0];
            const center = positions.length/3;
            positions.push(0,y,0.07+0.065*Math.pow((y-0.58)/0.7,2));uvs.push(0.5,y/1.26);
            for (let j = 0; j < segments; j++) {
                const a=row*segments+j,b=row*segments+(j+1)%segments;
                indices.push(center,top?b:a,top?a:b);
            }
        }
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
        geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uvs,2));
        geometry.setIndex(indices);geometry.computeVertexNormals();
        geometry.computeBoundingBox();geometry.computeBoundingSphere();
        return geometry;
    }
    function armrest(THREE, detail = 'near') {
        if (detail === 'far') return roundedPadding(THREE,8,4,0.42).scale(1,1,0.95);
        // Rounded console with a real opening for the separately instanced
        // cup well. Same normalized envelope as the previous armrest.
        const shape = new THREE.Shape(), a=0.98, r=0.36;
        shape.moveTo(-a+r,-a);shape.lineTo(a-r,-a);
        shape.quadraticCurveTo(a,-a,a,-a+r);shape.lineTo(a,a-r);
        shape.quadraticCurveTo(a,a,a-r,a);shape.lineTo(-a+r,a);
        shape.quadraticCurveTo(-a,a,-a,a-r);shape.lineTo(-a,-a+r);
        shape.quadraticCurveTo(-a,-a,-a+r,-a);
        const opening = new THREE.Path();
        opening.absellipse(0,-0.42,0.68,0.10,0,Math.PI*2,true);
        shape.holes.push(opening);
        const g=new THREE.ExtrudeGeometry(shape,{depth:2,bevelEnabled:true,bevelSize:0.02,bevelThickness:0.08,bevelSegments:1,curveSegments:3});
        g.rotateX(Math.PI/2);g.translate(0,1,0);g.scale(1,1/1.08,0.95);
        g.computeVertexNormals();g.computeBoundingBox();g.computeBoundingSphere();
        return g;
    }
    function cupHolder(THREE, detail = 'near') {
        return new THREE.LatheGeometry([
            new THREE.Vector2(0,-0.065),new THREE.Vector2(0.026,-0.065),
            new THREE.Vector2(0.032,-0.008),new THREE.Vector2(0.036,0),
            new THREE.Vector2(0.043,-0.003),new THREE.Vector2(0.038,-0.075),
            new THREE.Vector2(0,-0.075)
        ],detail === 'far' ? 6 : 8);
    }
    const api = {padding,backrest,armrest,cupHolder};
    if (typeof module === 'object' && module.exports) module.exports=api;
    else root.CinewaveChairGeometry=api;
})(typeof window === 'object' ? window : globalThis);
