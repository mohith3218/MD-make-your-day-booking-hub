/* Pure, read-only seat mapping checks; shared by the renderer and regression tests. */
(function (root) {
    'use strict';
    function classifySeat(row) {
        const name = String(row.className || '');
        const code = String(row.classCode || '');
        if (/reclin|insignia|luxe/i.test(name + ' ' + code)) return 2;
        if (/non[\s_-]*prem/i.test(name + ' ' + code)) return 0;
        return /vip|prime|premium|gold/i.test(name) || /^PREM(?:_|$)/i.test(code) ? 1 : 0;
    }
    function inspectMapping(seatId, registry, batches, rowDefs) {
        const id = String(seatId);
        const seat = registry.get(id);
        if (!seat) return {seatId:id, found:false, instances:[], mappingValid:false, errors:['missing-seat']};
        const errors = [];
        if (!seat.instanceParts.length) errors.push('missing-seat-components');
        const expected = new Set();
        const keyFor = (mesh, index) => `${batches.indexOf(mesh)}:${index}`;
        const instances = seat.instanceParts.map(ref => {
            const batch = batches.indexOf(ref.mesh);
            const key = keyFor(ref.mesh, ref.index);
            if (expected.has(key)) errors.push(`duplicate-reference:${key}`);
            expected.add(key);
            if (batch < 0 || !Number.isInteger(ref.index) || ref.index < 0 || ref.index >= ref.mesh.count)
                errors.push(`missing-instance:${key}`);
            const resolvedSeatId = ref.mesh.userData.instanceSeatIds[ref.index];
            if (resolvedSeatId !== id) errors.push(`wrong-seat:${key}`);
            return {batch, index:ref.index, kind:ref.kind || ref.mesh.userData.partKind,
                resolvedSeatId, part:resolvedSeatId};
        });
        batches.forEach((mesh, batch) => {
            for (let index = 0; index < mesh.count; index++) {
                if (mesh.userData.instanceSeatIds[index] === id && !expected.has(`${batch}:${index}`))
                    errors.push(`unexpected-instance:${batch}:${index}`);
            }
        });
        registry.forEach(other => {
            if (other === seat) return;
            other.instanceParts.forEach(ref => {
                if (expected.has(keyFor(ref.mesh, ref.index))) errors.push(`shared-instance:${other.id}`);
            });
        });
        const occurrences = rowDefs.filter(row => Object.prototype.hasOwnProperty.call(row.seats, id)).length;
        if (occurrences !== 1) errors.push(`seat-id-occurrences:${occurrences}`);
        return {seatId:id, found:true, row:seat.row, number:seat.num, rowIndex:seat.rowIndex,
            category:seat.tier, price:seat.price, unavailable:seat.isOccupied,
            instances, mappingValid:errors.length === 0, errors};
    }
    const api = {inspectMapping, classifySeat};
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.CinewaveSeatState = api;
})(typeof window === 'object' ? window : globalThis);
