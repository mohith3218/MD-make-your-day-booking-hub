/* The seat map and auditorium preview share the same reservation state. */
const bookingContext = JSON.parse(document.getElementById('booking-context').textContent);
const MAX_SEATS = bookingContext.maxSeats;
const reservedSeats = bookingContext.reservedSeats;
const draftKey = bookingContext.draftKey;
const selected = new Map();
let activePovSeat = null;
let pendingPreviewTrailer = false;
let fullPreviewTrigger = null;
let fullPreviewOverflow = '';
let showExitPathHighlight = false;
const povView = { yaw: 0, pitch: 0, format: 'wide', crowd: true, dim: true, recline: 0, dragging: false, x: 0, y: 0 };
const input = document.getElementById('selected_seats_input');
const display = document.getElementById('selected-display');
const classLine = document.getElementById('selected-classes');
const priceOut = document.getElementById('total-price');
const btn = document.getElementById('confirm-btn');

let activePartyCode = bookingContext.partyCode;
const partyCSRF = bookingContext.partyCSRF;
const cinemaLayout = bookingContext.layout;

// Compute nearest exit info for any seat button
function computeExitInfo(elem) {
  const layoutRows = (cinemaLayout.classes || []).flatMap(cls => cls.rows || []);
  const totalRows = Math.max(1, layoutRows.length);
  const seatId = elem?.dataset?.seat || '';
  const rowLabel = elem?.dataset?.seatRow || seatId.replace(/\d+$/, '') || (layoutRows[0]?.label || 'A');
  const seatNumber = parseInt(elem?.dataset?.seatNumber || seatId.replace(/^\D+/, '') || '1', 10);

  let rIdx = layoutRows.findIndex(r => r.label === rowLabel);
  if (rIdx === -1) rIdx = Math.floor(totalRows / 2);

  const rowObj = layoutRows[rIdx] || { count: 14, start: 1 };
  const rowCount = Math.max(1, Number(rowObj.count || 14));
  const rowStart = Number(rowObj.start || 1);
  const colIdx = Math.max(0, seatNumber - rowStart);
  const colProgress = Math.max(0, Math.min(1, colIdx / Math.max(1, rowCount - 1)));
  const rowProgress = totalRows > 1 ? (rIdx / (totalRows - 1)) : 0.5;

  const isLeft = colProgress <= 0.5;
  const isFront = rowProgress >= 0.45;
  const exitName = isFront
    ? (isLeft ? 'Exit 1 (Front Left)' : 'Exit 2 (Front Right)')
    : (isLeft ? 'Exit 3 (Rear Left)' : 'Exit 4 (Rear Right)');

  // Realistic walking distance in meters along row + aisle
  const seatsToWall = isLeft ? (colIdx + 1) : (rowCount - colIdx);
  const rowsToDoor = isFront ? (totalRows - 1 - rIdx) : rIdx;
  const distMeters = Math.max(2.2, (seatsToWall * 0.62 + rowsToDoor * 1.15)).toFixed(1);

  return {
    exitName,
    distMeters,
    isLeft,
    isFront,
    label: `${exitName} · ${distMeters}m`
  };
}

function updateInspector(elem) {
  if (!elem || !elem.dataset.seat) return;
  activePovSeat = elem;
  const exitInfo = computeExitInfo(elem);

  document.getElementById('insp-seat-id').textContent = elem.dataset.seat;
  document.getElementById('insp-zone-name').textContent = elem.dataset.povName || 'Standard Seat';
  document.getElementById('insp-badge').textContent = elem.dataset.povBadge || 'Standard View';
  document.getElementById('insp-vibe-badge').textContent = elem.dataset.vibeBadge || '🎭 Standard Vibe';
  document.getElementById('insp-angle').textContent = elem.dataset.povAngle || '15°';
  document.getElementById('insp-dist').textContent = elem.dataset.povDist || '50%';
  document.getElementById('insp-sound-score').textContent = elem.dataset.soundScore || '—';
  const exitEl = document.getElementById('insp-exit-info');
  if (exitEl) exitEl.textContent = `🚪 ${exitInfo.label}`;

  // Highlight active POV seat with a cyan outline so user sees where arrows moved
  document.querySelectorAll('.seat-btn').forEach(b => b.classList.remove('ring-2', 'ring-cyan-400'));
  elem.classList.add('ring-2', 'ring-cyan-400');
}

function filterVibe(vibeCode, btnElem) {
  document.querySelectorAll('.vibe-filter-btn').forEach(b => {
    b.className = "vibe-filter-btn px-3 py-1 rounded-xl text-xs font-bold transition bg-slate-800 text-slate-300 hover:text-white";
  });
  btnElem.className = "vibe-filter-btn px-3 py-1 rounded-xl text-xs font-bold transition bg-[#C9A84C] text-white";

  document.querySelectorAll('.seat-btn').forEach(b => {
    const v = b.dataset.vibeCode;
    if (vibeCode === 'ALL' || v === vibeCode) {
      b.style.opacity = '1.0';
    } else {
      b.style.opacity = '0.25';
    }
  });
}

function paint(sync = true) {
  const seats = [...selected.keys()];
  const total = [...selected.values()].reduce((a, s) => a + s.price, 0);
  input.value = seats.join(',');
  display.textContent = seats.length ? seats.join(', ') : 'No seats selected';
  if (!reservedSeats.length) {
    try { sessionStorage.setItem(draftKey, JSON.stringify(seats)); } catch {}
  }
  priceOut.textContent = '₹' + total.toFixed(0);
  btn.disabled = seats.length === 0;

  const counts = {};
  selected.forEach(s => { counts[s.cls] = (counts[s.cls] || 0) + 1; });
  classLine.textContent = Object.entries(counts).map(([c, n]) => `${n} × ${c}`).join('  ·  ');

  updateImmersiveBookingPanel();

  if (sync && activePartyCode) syncParty();
}

// Build the booking view from this screen's saved layout and live seat states.
// The 3D preview and the regular seat map use the same seat IDs and selection state.
function updateImmersiveBookingPanel() {
  const panel = document.getElementById('immersive-seat-sidebar');
  if (!panel) return;
  const classesRoot = panel.querySelector('[data-seat-classes]');
  if (classesRoot) {
    classesRoot.replaceChildren();
    (cinemaLayout.classes || []).forEach((cls, index) => {
      const seats = [...document.querySelectorAll('.seat-btn')].filter(seat =>
        seat.dataset.classCode === cls.code || seat.dataset.class === cls.name
      );
      const available = seats.filter(seat => !seat.disabled && !seat.classList.contains('seat-sel')).length;
      const color = ['#f6bd45','#9a77ff','#20cda5','#438cff'][index % 4];
      const card = document.createElement('div');
      card.className = 'immersive-class-card';
      card.innerHTML = `<span class="immersive-class-swatch" style="--class-color:${color}"></span><div class="min-w-0 flex-1"><strong></strong><small></small></div><div class="text-right"><b></b><small></small></div>`;
      card.querySelector('strong').textContent = cls.name || cls.code || 'Seats';
      card.querySelector('small').textContent = cls.description || 'Choose seats in the auditorium';
      card.querySelector('b').textContent = `₹${Math.round(Number(seats[0]?.dataset.price ?? cls.price ?? 0))}`;
      card.querySelectorAll('small')[1].textContent = `${available} left`;
      classesRoot.appendChild(card);
    });
  }
  const selectedNames = [...selected.keys()];
  const seatsOut = panel.querySelector('[data-selected-seats]');
  if (seatsOut) seatsOut.textContent = selectedNames.length ? selectedNames.join(' · ') : 'Tap any available seat in the hall';
  const countOut = panel.querySelector('[data-selected-count]');
  if (countOut) countOut.textContent = String(selectedNames.length);
  const totalOut = panel.querySelector('[data-selected-total]');
  if (totalOut) totalOut.textContent = priceOut.textContent;
  const checkout = panel.querySelector('[data-immersive-checkout]');
  if (checkout) checkout.disabled = selectedNames.length === 0;
}

function immersiveBestSeats() {
  const size = document.getElementById('immersive-party-size').value;
  document.getElementById('smart-party-size').value = size;
  suggestSmartSeats();
}

// ---- 👁️ AR / VR SEAT PREVIEW ENGINE ----
const moviePosterUrl = bookingContext.movie.poster;
const movieTitleStr = bookingContext.movie.title;
const movieLanguageStr = bookingContext.movie.language;
const movieCertStr = bookingContext.movie.certificate;
const movieDurationStr = bookingContext.movie.duration;
const movieRatingStr = bookingContext.movie.tmdbRating;

const posterImg = new Image();
posterImg.crossOrigin = 'anonymous';
if (moviePosterUrl) {
  posterImg.src = moviePosterUrl;
  posterImg.onload = () => { refreshPovViews(); };
}

function traceRoundedRect(ctx, x, y, width, height, radius) {
  if (typeof ctx.roundRect === 'function') ctx.roundRect(x, y, width, height, radius);
  else {
    const r = Math.min(radius, width/2, height/2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + width, y, x + width, y + height, r);
    ctx.arcTo(x + width, y + height, x, y + height, r);
    ctx.arcTo(x, y + height, x, y, r);
    ctx.arcTo(x, y, x + width, y, r);
    ctx.closePath();
  }
}

function drawCinemaView(canvas, elem, forTrailer = false) {
  if (!canvas) return null;
  const bounds = canvas.getBoundingClientRect();
  const w = Math.max(1, bounds.width);
  const h = Math.max(1, bounds.height);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const pixelW = Math.round(w * dpr);
  const pixelH = Math.round(h * dpr);
  if (canvas.width !== pixelW || canvas.height !== pixelH) {
    canvas.width = pixelW;
    canvas.height = pixelH;
  }
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const nowSec = performance.now() * 0.001;

  // 1. Identify Seat Position & Perspective from Layout
  const layoutRows = (cinemaLayout.classes || []).flatMap(cls =>
    (cls.rows || []).map(row => ({ ...row, classCode: cls.code, className: cls.name, price: cls.price }))
  );
  const totalRows = Math.max(1, layoutRows.length);

  const seatId = elem?.dataset?.seat || '';
  const rowLabel = elem?.dataset?.seatRow || seatId.replace(/\d+$/, '') || (layoutRows[0]?.label || 'A');
  const seatNumber = parseInt(elem?.dataset?.seatNumber || seatId.replace(/^\D+/, '') || '1', 10);

  let selectedRowIndex = layoutRows.findIndex(r => r.label === rowLabel);
  if (selectedRowIndex === -1) {
    selectedRowIndex = Number.isFinite(parseInt(elem?.dataset?.povRowIndex, 10))
      ? parseInt(elem.dataset.povRowIndex, 10)
      : Math.floor(totalRows / 2);
  }

  const rowProgress = totalRows > 1
    ? Math.max(0, Math.min(1, selectedRowIndex / (totalRows - 1)))
    : 0.5;

  const rowObj = layoutRows[selectedRowIndex] || layoutRows[0];
  const rowCount = Math.max(1, Number(rowObj?.count || 14));
  const rowStart = Number(rowObj?.start || 1);
  const colIdx = Math.max(0, seatNumber - rowStart);
  const colProgress = Math.max(0, Math.min(1, colIdx / Math.max(1, rowCount - 1)));
  const sideFactor = (colProgress - 0.5) * 2; // -1.0 (left) to +1.0 (right)

  const visibleRows = layoutRows.slice(selectedRowIndex + 1);
  const neckAngle = 14 + (rowProgress * 28);
  const userPitch = povView.pitch - (povView.recline * 0.12);
  const verticalAim = Math.max(-1.2, Math.min(1.2, ((neckAngle - 18) / 14) + userPitch));
  const normalizedYaw = Math.max(-1.2, Math.min(1.2, (sideFactor * 0.42) + povView.yaw));
  const cameraShift = -normalizedYaw * w * 0.28;

  const isShowtime = povView.lighting === 'movie' || (!povView.lighting && povView.dim);
  const isHouse = povView.lighting === 'house';

  // 2. Auditorium Background Gradients
  const roomGrad = ctx.createLinearGradient(0, 0, 0, h);
  if (isHouse) {
    roomGrad.addColorStop(0, '#222530');
    roomGrad.addColorStop(0.5, '#191822');
    roomGrad.addColorStop(1, '#111118');
  } else if (isShowtime) {
    roomGrad.addColorStop(0, '#090a10');
    roomGrad.addColorStop(0.5, '#06070c');
    roomGrad.addColorStop(1, '#030406');
  } else {
    roomGrad.addColorStop(0, '#13151f');
    roomGrad.addColorStop(0.5, '#0f0e16');
    roomGrad.addColorStop(1, '#08080d');
  }
  ctx.fillStyle = roomGrad;
  ctx.fillRect(0, 0, w, h);

  // 3. Vanishing Point & Room Depth Geometry
  const vanishX = w * 0.5 + cameraShift * 0.85;
  const vanishY = h * (0.43 + verticalAim * 0.08);

  // Live pulsing screen glow
  const pulseBoost = 0.04 * Math.sin(nowSec * 2.2);
  const glowRadius = w * (0.55 + rowProgress * 0.25);
  const glowX = vanishX;
  const glowY = vanishY - h * 0.04;
  const screenAtmosphere = ctx.createRadialGradient(glowX, glowY, 10, glowX, glowY, glowRadius);
  if (isShowtime) {
    screenAtmosphere.addColorStop(0, `rgba(125, 175, 255, ${0.24 + pulseBoost})`);
    screenAtmosphere.addColorStop(0.3, 'rgba(70, 110, 210, 0.12)');
    screenAtmosphere.addColorStop(0.65, 'rgba(30, 45, 90, 0.04)');
    screenAtmosphere.addColorStop(1, 'rgba(0, 0, 0, 0)');
  } else if (isHouse) {
    screenAtmosphere.addColorStop(0, 'rgba(255, 220, 180, 0.18)');
    screenAtmosphere.addColorStop(0.4, 'rgba(210, 170, 130, 0.08)');
    screenAtmosphere.addColorStop(1, 'rgba(0, 0, 0, 0)');
  } else {
    screenAtmosphere.addColorStop(0, 'rgba(225, 180, 110, 0.18)');
    screenAtmosphere.addColorStop(0.4, 'rgba(150, 110, 70, 0.07)');
    screenAtmosphere.addColorStop(1, 'rgba(0, 0, 0, 0)');
  }
  ctx.fillStyle = screenAtmosphere;
  ctx.fillRect(0, 0, w, h);

  // Projector Dust Beam
  if (isShowtime) {
    ctx.save();
    const beamGrad = ctx.createLinearGradient(w * 0.5, 0, glowX, glowY);
    beamGrad.addColorStop(0, 'rgba(255, 255, 255, 0.1)');
    beamGrad.addColorStop(0.4, 'rgba(180, 215, 255, 0.04)');
    beamGrad.addColorStop(1, 'rgba(100, 150, 255, 0)');
    ctx.fillStyle = beamGrad;
    ctx.beginPath();
    ctx.moveTo(w * 0.5 - w * 0.08, 0);
    ctx.lineTo(w * 0.5 + w * 0.08, 0);
    ctx.lineTo(glowX + w * 0.38, glowY);
    ctx.lineTo(glowX - w * 0.38, glowY);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  // 4. Ceiling with Acoustic Louvers
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(w, 0);
  ctx.lineTo(vanishX + w * 0.38, vanishY - h * 0.14);
  ctx.lineTo(vanishX - w * 0.38, vanishY - h * 0.14);
  ctx.closePath();
  const ceilGrad = ctx.createLinearGradient(0, 0, 0, vanishY);
  ceilGrad.addColorStop(0, isHouse ? '#222530' : '#11131a');
  ceilGrad.addColorStop(1, isHouse ? '#151720' : '#08090d');
  ctx.fillStyle = ceilGrad;
  ctx.fill();

  ctx.strokeStyle = isHouse ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.035)';
  ctx.lineWidth = 1;
  for (let c = 1; c <= 6; c++) {
    const cy = (c / 6) * (vanishY - h * 0.14);
    const span = w * 0.5 * (1 - c * 0.09);
    ctx.beginPath();
    ctx.moveTo(vanishX - span, cy);
    ctx.lineTo(vanishX + span, cy);
    ctx.stroke();
  }

  // 5. Side Walls
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(vanishX - w * 0.38, vanishY - h * 0.14);
  ctx.lineTo(vanishX - w * 0.38, Math.min(h * 0.76, vanishY + h * 0.28));
  ctx.lineTo(0, h);
  ctx.closePath();
  const leftGrad = ctx.createLinearGradient(0, 0, vanishX, 0);
  leftGrad.addColorStop(0, isHouse ? '#1c1e27' : '#0f1017');
  leftGrad.addColorStop(1, isHouse ? '#111218' : '#07080c');
  ctx.fillStyle = leftGrad;
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(w, 0);
  ctx.lineTo(vanishX + w * 0.38, vanishY - h * 0.14);
  ctx.lineTo(vanishX + w * 0.38, Math.min(h * 0.76, vanishY + h * 0.28));
  ctx.lineTo(w, h);
  ctx.closePath();
  const rightGrad = ctx.createLinearGradient(w, 0, vanishX, 0);
  rightGrad.addColorStop(0, isHouse ? '#1c1e27' : '#0f1017');
  rightGrad.addColorStop(1, isHouse ? '#111218' : '#07080c');
  ctx.fillStyle = rightGrad;
  ctx.fill();

  function drawWallFixtures(isLeft) {
    for (let i = 1; i <= 3; i++) {
      const t = i / 3.8;
      const wx = isLeft ? (vanishX - w * 0.38) * t : w - (w - (vanishX + w * 0.38)) * t;
      const wy = vanishY - h * 0.05 + (t * h * 0.18);

      if (!isShowtime || isHouse) {
        ctx.save();
        const sconceGlow = ctx.createRadialGradient(wx, wy, 1, wx, wy, 35 * t);
        sconceGlow.addColorStop(0, 'rgba(245, 185, 110, 0.45)');
        sconceGlow.addColorStop(0.5, 'rgba(245, 185, 110, 0.12)');
        sconceGlow.addColorStop(1, 'rgba(245, 185, 110, 0)');
        ctx.fillStyle = sconceGlow;
        ctx.beginPath();
        ctx.arc(wx, wy, 35 * t, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      ctx.fillStyle = '#0a0b0e';
      ctx.strokeStyle = 'rgba(255,255,255,0.1)';
      ctx.lineWidth = 1;
      const spkW = Math.max(3, 8 * t);
      const spkH = Math.max(5, 14 * t);
      ctx.fillRect(wx - spkW / 2, wy - spkH / 2, spkW, spkH);
      ctx.strokeRect(wx - spkW / 2, wy - spkH / 2, spkW, spkH);

      ctx.fillStyle = '#38bdf8';
      ctx.beginPath();
      ctx.arc(wx, wy, Math.max(1, 1.5 * t), 0, Math.PI * 2);
      ctx.fill();
    }
  }
  drawWallFixtures(true);
  drawWallFixtures(false);

  // 6. Floor & Stage Proscenium
  const floorTop = vanishY + h * 0.08;
  const floorAvailableDepth = Math.max(1, h - floorTop);
  ctx.beginPath();
  ctx.moveTo(vanishX - w * 0.38, floorTop);
  ctx.lineTo(vanishX + w * 0.38, floorTop);
  ctx.lineTo(w * 1.15, h);
  ctx.lineTo(-w * 0.15, h);
  ctx.closePath();
  const carpetGrad = ctx.createLinearGradient(0, floorTop, 0, h);
  carpetGrad.addColorStop(0, '#111118');
  carpetGrad.addColorStop(0.5, '#0b0b10');
  carpetGrad.addColorStop(1, '#060608');
  ctx.fillStyle = carpetGrad;
  ctx.fill();

  // 6B. ILLUMINATED 3D EXIT WAY DOORS (LEFT & RIGHT) + GREEN FLOOR EGRESS STRIPS
  const leftExitX = Math.max(18, vanishX - w * 0.36);
  const rightExitX = Math.min(w - 18, vanishX + w * 0.36);
  const exitDoorBottomY = floorTop + h * 0.06;
  const exitDoorW = Math.max(18, w * 0.032);
  const exitDoorH = Math.max(32, h * 0.11);

  function drawExitDoorAssembly(doorCenterX, labelText, isNearest) {
    ctx.save();
    const doorTopY = exitDoorBottomY - exitDoorH;

    // Emerald ambient glow around exit door
    const exitGlow = ctx.createRadialGradient(doorCenterX, doorTopY, 2, doorCenterX, doorTopY + exitDoorH * 0.4, exitDoorW * (isNearest ? 3.2 : 2.0));
    exitGlow.addColorStop(0, isNearest ? 'rgba(16, 185, 129, 0.55)' : 'rgba(16, 185, 129, 0.28)');
    exitGlow.addColorStop(1, 'rgba(16, 185, 129, 0)');
    ctx.fillStyle = exitGlow;
    ctx.beginPath();
    ctx.arc(doorCenterX, doorTopY + exitDoorH * 0.3, exitDoorW * 3, 0, Math.PI * 2);
    ctx.fill();

    // Acoustic Exit Door Frame
    ctx.fillStyle = '#07120e';
    ctx.strokeStyle = isNearest ? '#10b981' : 'rgba(16, 185, 129, 0.45)';
    ctx.lineWidth = isNearest ? 2 : 1;
    ctx.beginPath();
    traceRoundedRect(ctx, doorCenterX - exitDoorW / 2, doorTopY, exitDoorW, exitDoorH, 3);
    ctx.fill();
    ctx.stroke();

    // Illuminated Push-Bar Handle
    ctx.fillStyle = '#10b981';
    ctx.fillRect(doorCenterX - exitDoorW * 0.35, doorTopY + exitDoorH * 0.52, exitDoorW * 0.7, 2.5);

    // Overhead Glowing Green EXIT Signboard
    const signW = Math.max(34, exitDoorW * 1.45);
    const signH = 13;
    const signY = doorTopY - signH - 4;
    ctx.fillStyle = '#064e3b';
    ctx.strokeStyle = '#34d399';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    traceRoundedRect(ctx, doorCenterX - signW / 2, signY, signW, signH, 3);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = '#ecfdf5';
    ctx.font = 'bold 8px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(`🏃 ${labelText}`, doorCenterX, signY + 9.5);
    ctx.restore();
  }

  const nearestIsLeft = sideFactor <= 0;
  drawExitDoorAssembly(leftExitX, 'EXIT 1', nearestIsLeft);
  drawExitDoorAssembly(rightExitX, 'EXIT 2', !nearestIsLeft);

  // Draw Glowing Green Floor Egress Route from User's Seat to Nearest Exit
  const targetExitX = nearestIsLeft ? leftExitX : rightExitX;
  ctx.save();
  ctx.strokeStyle = showExitPathHighlight ? 'rgba(16, 185, 129, 0.95)' : 'rgba(16, 185, 129, 0.38)';
  ctx.lineWidth = showExitPathHighlight ? 4 : 2;
  ctx.setLineDash([6, 4]);
  ctx.lineDashOffset = -nowSec * 18;
  ctx.beginPath();
  ctx.moveTo(w * 0.5, h - 18); // From user seat feet
  ctx.lineTo(targetExitX, h - 28); // Along row to side aisle
  ctx.lineTo(targetExitX, exitDoorBottomY); // Down side aisle to Exit Door
  ctx.stroke();
  ctx.restore();

  // Stage Front Subwoofer Base
  const stageH = Math.max(8, h * 0.05);
  const stageTop = floorTop - stageH;
  ctx.fillStyle = '#08080b';
  ctx.fillRect(vanishX - w * 0.36, stageTop, w * 0.72, stageH);
  ctx.strokeStyle = 'rgba(255,255,255,0.06)';
  ctx.strokeRect(vanishX - w * 0.36, stageTop, w * 0.72, stageH);

  // Floor Reflection
  const reflW = w * (0.35 + rowProgress * 0.3);
  const reflH = Math.max(14, floorAvailableDepth * 0.28);
  const reflGrad = ctx.createLinearGradient(vanishX, floorTop, vanishX, floorTop + reflH);
  if (isShowtime) {
    reflGrad.addColorStop(0, 'rgba(125, 175, 255, 0.16)');
    reflGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
  } else {
    reflGrad.addColorStop(0, 'rgba(245, 185, 110, 0.12)');
    reflGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
  }
  ctx.fillStyle = reflGrad;
  ctx.beginPath();
  ctx.ellipse(vanishX, floorTop + reflH * 0.45, reflW * 0.5, reflH * 0.5, 0, 0, Math.PI * 2);
  ctx.fill();

  // 7. REAL 3D SCREEN PERSPECTIVE & DISTANCE SCALING
  const distScale = 0.44 + (rowProgress * 0.44);
  const screenConfig = cinemaLayout.screen || {};
  const screenWidthMeters = Number(screenConfig.width_m) > 0 ? Number(screenConfig.width_m) : 18;
  const seatDistanceMeters = 18 - (rowProgress * 11.5);
  const referenceViewAngle = Math.atan(18 / (2 * 12));
  const actualViewAngle = Math.atan(screenWidthMeters / (2 * seatDistanceMeters));
  const physicalSizeScale = Math.max(0.65, Math.min(1.35, actualViewAngle / referenceViewAngle));
  let screenWidth = w * distScale * physicalSizeScale;

  // Use the real screen geometry saved with this screen's seating layout.
  // The format buttons remain useful as projection previews, while "wide"
  // follows the auditorium's configured physical width and height.
  const configuredAspect = Number(screenConfig.width_m) > 0 && Number(screenConfig.height_m) > 0
    ? Number(screenConfig.width_m) / Number(screenConfig.height_m)
    : Number(screenConfig.aspect_ratio) > 0 ? Number(screenConfig.aspect_ratio) : 1.85;
  let screenAspect = configuredAspect;
  if (povView.format === 'scope') screenAspect = 2.39;
  else if (povView.format === 'imax') screenAspect = 1.43;

  let screenHeight = screenWidth / screenAspect;
  if (screenHeight > h * 0.62) {
    screenHeight = h * 0.62;
    screenWidth = screenHeight * screenAspect;
  }

  const screenElevation = (1 - rowProgress) * (h * 0.06) - (rowProgress * h * 0.04);
  const screenCenterY = vanishY - screenHeight * 0.48 + screenElevation;
  const screenCenterX = vanishX - (sideFactor * w * 0.07);

  const kFactor = Math.abs(sideFactor) * 0.18;
  const leftHeightFactor = sideFactor < 0 ? (1 + kFactor) : (1 - kFactor);
  const rightHeightFactor = sideFactor > 0 ? (1 + kFactor) : (1 - kFactor);

  const sLeft = screenCenterX - screenWidth * 0.5;
  const sRight = screenCenterX + screenWidth * 0.5;

  const topLeftY = screenCenterY - (screenHeight * 0.5 * leftHeightFactor);
  const botLeftY = screenCenterY + (screenHeight * 0.5 * leftHeightFactor);
  const topRightY = screenCenterY - (screenHeight * 0.5 * rightHeightFactor);
  const botRightY = screenCenterY + (screenHeight * 0.5 * rightHeightFactor);
  const curveRatio = Math.max(0, Math.min(0.6,
    Number.isFinite(Number(screenConfig.curve)) ? Number(screenConfig.curve) : 0.22));
  const curveBows = Math.max(3, screenWidth * curveRatio * 0.08);

  // 8. RENDER CURVED CINEMA SCREEN
  ctx.save();
  ctx.shadowColor = isShowtime ? 'rgba(96, 165, 250, 0.45)' : 'rgba(251, 191, 36, 0.25)';
  ctx.shadowBlur = Math.max(6, screenWidth * 0.04);

  ctx.fillStyle = '#050608';
  ctx.beginPath();
  ctx.moveTo(sLeft - 4, topLeftY - 4);
  ctx.quadraticCurveTo(screenCenterX, topLeftY - 4 + curveBows, sRight + 4, topRightY - 4);
  ctx.lineTo(sRight + 4, botRightY + 4);
  ctx.quadraticCurveTo(screenCenterX, botRightY + 4 - curveBows, sLeft - 4, botLeftY + 4);
  ctx.closePath();
  ctx.fill();
  ctx.shadowBlur = 0;

  ctx.beginPath();
  ctx.moveTo(sLeft, topLeftY);
  ctx.quadraticCurveTo(screenCenterX, topLeftY + curveBows, sRight, topRightY);
  ctx.lineTo(sRight, botRightY);
  ctx.quadraticCurveTo(screenCenterX, botRightY - curveBows, sLeft, botLeftY);
  ctx.closePath();

  const screenFillGrad = ctx.createLinearGradient(sLeft, topLeftY, sRight, botRightY);
  screenFillGrad.addColorStop(0, '#1c2430');
  screenFillGrad.addColorStop(0.5, '#283547');
  screenFillGrad.addColorStop(1, '#151b24');
  ctx.fillStyle = screenFillGrad;
  ctx.fill();

  ctx.save();
  ctx.clip();

  if (forTrailer) {
    ctx.fillStyle = '#000000';
    ctx.fillRect(sLeft, Math.min(topLeftY, topRightY), screenWidth, screenHeight * 1.5);
  } else {
    if (posterImg && posterImg.complete && posterImg.naturalWidth > 0) {
      ctx.globalAlpha = 0.45;
      ctx.drawImage(posterImg, sLeft, topLeftY, screenWidth, Math.max(botLeftY, botRightY) - Math.min(topLeftY, topRightY));
      ctx.globalAlpha = 1.0;
    }

    // Real-time animated light sweep across screen
    const sweepX = sLeft + ((nowSec * 0.22) % 1.4 - 0.2) * screenWidth;
    const sweepGrad = ctx.createLinearGradient(sweepX - 60, topLeftY, sweepX + 60, botRightY);
    sweepGrad.addColorStop(0, 'rgba(255,255,255,0)');
    sweepGrad.addColorStop(0.5, 'rgba(56, 189, 248, 0.14)');
    sweepGrad.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = sweepGrad;
    ctx.fillRect(sLeft, Math.min(topLeftY, topRightY), screenWidth, screenHeight * 1.5);

    const overlay = ctx.createLinearGradient(sLeft, topLeftY, sLeft, Math.max(botLeftY, botRightY));
    overlay.addColorStop(0, 'rgba(8, 12, 20, 0.5)');
    overlay.addColorStop(0.6, 'rgba(10, 15, 25, 0.68)');
    overlay.addColorStop(1, 'rgba(4, 6, 10, 0.92)');
    ctx.fillStyle = overlay;
    ctx.fillRect(sLeft, Math.min(topLeftY, topRightY), screenWidth, screenHeight * 1.5);

    const titleY = screenCenterY - screenHeight * 0.08;
    ctx.textAlign = 'center';

    ctx.fillStyle = 'rgba(201, 168, 76, 0.25)';
    const pillW = Math.max(120, screenWidth * 0.45);
    const pillH = Math.max(16, screenHeight * 0.1);
    ctx.beginPath();
    traceRoundedRect(ctx, screenCenterX - pillW/2, titleY - pillH - 12, pillW, pillH, pillH/2);
    ctx.fill();
    ctx.strokeStyle = 'rgba(201, 168, 76, 0.6)';
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.fillStyle = '#fbbf24';
    ctx.font = `bold ${Math.max(8, Math.round(screenHeight * 0.048))}px sans-serif`;
    ctx.fillText(`NOW SHOWING · ${cinemaLayout.screen_label || 'DOLBY CINEMA 4K'}`, screenCenterX, titleY - 17);

    ctx.fillStyle = '#ffffff';
    ctx.shadowColor = 'rgba(0,0,0,0.85)';
    ctx.shadowBlur = 6;
    ctx.font = `900 ${Math.max(12, Math.round(screenHeight * 0.1))}px sans-serif`;
    ctx.fillText(movieTitleStr, screenCenterX, titleY + 4);
    ctx.shadowBlur = 0;

    ctx.fillStyle = '#cbd5e1';
    ctx.font = `600 ${Math.max(8, Math.round(screenHeight * 0.046))}px sans-serif`;
    const movieFacts = [movieLanguageStr, movieCertStr, movieDurationStr && movieDurationStr + ' min',
      movieRatingStr !== null && 'TMDB ' + movieRatingStr + '/10'].filter(Boolean).join(' · ');
    ctx.fillText(movieFacts, screenCenterX, titleY + screenHeight * 0.1);

    const ctaY = titleY + screenHeight * 0.24;
    const ctaW = Math.max(140, screenWidth * 0.5);
    const ctaH = Math.max(22, screenHeight * 0.14);
    ctx.fillStyle = 'rgba(234, 88, 12, 0.88)';
    ctx.beginPath();
    traceRoundedRect(ctx, screenCenterX - ctaW/2, ctaY, ctaW, ctaH, ctaH/2);
    ctx.fill();
    ctx.strokeStyle = '#fdba74';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    ctx.fillStyle = '#ffffff';
    ctx.font = `bold ${Math.max(9, Math.round(screenHeight * 0.054))}px sans-serif`;
    ctx.fillText(`▶  PLAY TRAILER IN VR POV`, screenCenterX, ctaY + ctaH * 0.68);
  }

  ctx.restore();
  ctx.restore();

  // 9. RENDER ROWS OF SEATS IN FRONT
  const maxRowUnits = Math.max(1, ...layoutRows.map(r =>
    Number(r.count || 0) * Math.max(1, Number(r.seat_span || 1)) + (r.aisles_after || []).length * 0.6 + Number(r.offset || 0)
  ));

  if (visibleRows.length > 0 && povView.crowd) {
    for (let r = 0; r < visibleRows.length; r++) {
      const row = visibleRows[r];
      const depth = (r + 1) / visibleRows.length;
      const rowY = floorTop + (depth * depth * floorAvailableDepth * (forTrailer ? 0.35 : 0.8));
      const prevDepth = r / visibleRows.length;
      const rowStep = Math.max(2, (depth * depth - prevDepth * prevDepth) * floorAvailableDepth);

      const seatCount = Math.max(0, Number(row.count || 0));
      const seatSpan = Math.max(1, Number(row.seat_span || 1));
      const aisleAfter = new Set((row.aisles_after || []).map(Number));
      const blocked = new Set(row.blocked || []);
      const rowUnits = seatCount * seatSpan + aisleAfter.size * 0.6 + Number(row.offset || 0);

      const spacing = Math.max(2.4, (w * 0.72) / Math.max(maxRowUnits, rowUnits, 1));
      const seatW = Math.max(2.5, spacing * seatSpan * 0.76);
      const seatH = Math.max(3.5, rowStep * 1.15);
      const rowWidth = spacing * rowUnits;
      let x = vanishX - rowWidth / 2 + Number(row.offset || 0) * spacing + cameraShift * depth * 0.3;
      const firstSeat = Number(row.start || 1);

      for (let sIdx = 0; sIdx < seatCount; sIdx++) {
        const num = firstSeat + sIdx;
        const sId = `${row.label}${num}`;
        if (!blocked.has(sId)) {
          drawCinemaChair(ctx, x + spacing * seatSpan / 2, rowY, seatW, seatH, depth);
          const seed = (num * 37 + r * 19) % 10;
          if (seed < 4 && !forTrailer) {
            drawAudienceHead(ctx, x + spacing * seatSpan / 2, rowY - seatH * 0.5, seatW * 0.55, seatH * 0.85);
          }
        }
        x += spacing * seatSpan;
        if (aisleAfter.has(num)) {
          ctx.fillStyle = 'rgba(16, 185, 129, 0.55)';
          ctx.fillRect(x + 2, rowY + 1, Math.max(2, spacing * 0.3), 1.5);
          x += spacing * 0.6;
        }
      }
    }
  }

  function drawCinemaChair(ctx, cx, cy, sw, sh, depth) {
    const seatTop = cy - sh * 0.58;
    const redTone = Math.round(55 + depth * 12);
    const backGrad = ctx.createLinearGradient(cx - sw/2, seatTop, cx + sw/2, seatTop + sh * 0.7);
    backGrad.addColorStop(0, `rgb(${redTone + 15}, 25, 35)`);
    backGrad.addColorStop(0.5, `rgb(${redTone}, 18, 25)`);
    backGrad.addColorStop(1, `rgb(${redTone - 20}, 10, 15)`);

    ctx.fillStyle = backGrad;
    ctx.beginPath();
    traceRoundedRect(ctx, cx - sw * 0.44, seatTop, sw * 0.88, sh * 0.72, sw * 0.18);
    ctx.fill();

    ctx.strokeStyle = 'rgba(255,255,255,0.18)';
    ctx.lineWidth = Math.max(0.4, sw * 0.02);
    ctx.beginPath();
    ctx.moveTo(cx - sw * 0.3, seatTop + sh * 0.1);
    ctx.quadraticCurveTo(cx, seatTop + sh * 0.03, cx + sw * 0.3, seatTop + sh * 0.1);
    ctx.stroke();

    const cushionGrad = ctx.createLinearGradient(0, seatTop + sh * 0.45, 0, seatTop + sh * 0.9);
    cushionGrad.addColorStop(0, `rgb(${redTone + 10}, 22, 30)`);
    cushionGrad.addColorStop(1, `rgb(${redTone - 15}, 12, 18)`);
    ctx.fillStyle = cushionGrad;
    ctx.beginPath();
    traceRoundedRect(ctx, cx - sw * 0.48, seatTop + sh * 0.46, sw * 0.96, sh * 0.42, sw * 0.12);
    ctx.fill();
  }

  function drawAudienceHead(ctx, cx, cy, hw, hh) {
    ctx.fillStyle = '#050608';
    ctx.beginPath();
    ctx.arc(cx, cy - hh * 0.25, hw * 0.45, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.ellipse(cx, cy + hh * 0.2, hw * 0.85, hh * 0.45, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  // 10. FIRST-PERSON COCKPIT (YOUR SEAT ARMRESTS & CUPHOLDER)
  const reclineDrop = povView.recline * 14;
  const armrestW = Math.max(48, w * 0.11);
  const armrestH = Math.max(70, h * 0.28);
  const armrestY = h - armrestH * 0.75 + reclineDrop;

  function drawCockpitArmrest(isLeft) {
    ctx.save();
    const ax = isLeft ? 0 : w - armrestW;

    const aGrad = ctx.createLinearGradient(ax, armrestY, ax + armrestW, h);
    aGrad.addColorStop(0, '#2d1b22');
    aGrad.addColorStop(0.4, '#1b1216');
    aGrad.addColorStop(1, '#09080b');
    ctx.fillStyle = aGrad;

    ctx.beginPath();
    if (isLeft) {
      ctx.moveTo(0, armrestY + 15);
      ctx.quadraticCurveTo(armrestW * 0.8, armrestY, armrestW, armrestY + 25);
      ctx.lineTo(armrestW * 0.7, h);
      ctx.lineTo(0, h);
    } else {
      ctx.moveTo(w, armrestY + 15);
      ctx.quadraticCurveTo(w - armrestW * 0.8, armrestY, w - armrestW, armrestY + 25);
      ctx.lineTo(w - armrestW * 0.7, h);
      ctx.lineTo(w, h);
    }
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = 'rgba(201, 168, 76, 0.4)';
    ctx.lineWidth = 1;
    ctx.stroke();

    if (!isLeft) {
      const cupX = w - armrestW * 0.52;
      const cupY = armrestY + 36;

      ctx.fillStyle = '#1c1e24';
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.6)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.ellipse(cupX, cupY, 14, 8, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = '#e11d48';
      ctx.beginPath();
      ctx.moveTo(cupX - 10, cupY);
      ctx.lineTo(cupX - 7, cupY - 26);
      ctx.lineTo(cupX + 7, cupY - 26);
      ctx.lineTo(cupX + 10, cupY);
      ctx.closePath();
      ctx.fill();

      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.ellipse(cupX, cupY - 26, 7.5, 3.5, 0, 0, Math.PI * 2);
      ctx.fill();

      ctx.strokeStyle = '#f59e0b';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(cupX, cupY - 26);
      ctx.lineTo(cupX + 4, cupY - 40);
      ctx.stroke();
    }

    if (isLeft) {
      const badgeX = armrestW * 0.18;
      const badgeY = armrestY + 45;
      ctx.fillStyle = 'rgba(0,0,0,0.7)';
      ctx.strokeStyle = 'rgba(201, 168, 76, 0.5)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      traceRoundedRect(ctx, badgeX, badgeY, armrestW * 0.72, 20, 4);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = '#fbbf24';
      ctx.font = 'bold 8px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(`${rowLabel}${seatNumber}`, badgeX + (armrestW * 0.72) / 2, badgeY + 13);
    }

    ctx.restore();
  }

  drawCockpitArmrest(true);
  drawCockpitArmrest(false);

  // 11. Lens Vignette
  const vignette = ctx.createRadialGradient(w/2, h/2, w * 0.25, w/2, h/2, w * 0.75);
  vignette.addColorStop(0, 'rgba(0,0,0,0)');
  vignette.addColorStop(1, 'rgba(0,0,0,0.65)');
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, w, h);

  return {
    left: Math.round(sLeft),
    top: Math.round(Math.min(topLeftY, topRightY)),
    width: Math.round(screenWidth),
    height: Math.round(screenHeight),
    screenWidth: Math.round(screenWidth),
    sideAngle: sideFactor * 25,
    sideFactor: sideFactor,
    rowProgress: rowProgress
  };
}

function showSeatARPreview(elem) {
  if (!elem || !elem.dataset.seat) return;
  activePovSeat = elem;
  const rowLabel = elem.dataset.seatRow || elem.dataset.seat.replace(/\d+$/, '');
  const seatNumber = elem.dataset.seatNumber || elem.dataset.seat.replace(/^\D+/, '');
  const distStr = elem.dataset.povDist || '50%';
  const angleStr = elem.dataset.povAngle || '16°';
  const audioEstimate = elem.dataset.soundScore || '—';
  const exitInfo = computeExitInfo(elem);

  document.getElementById('ar-preview-subtitle').textContent = `Row ${rowLabel} · Seat ${seatNumber} (${elem.dataset.class || 'Standard'}) · 🚪 ${exitInfo.label}`;
  document.getElementById('pov-badge-title').textContent = `Row ${rowLabel} · Seat ${seatNumber} (${elem.dataset.class || 'Standard'})`;
  document.getElementById('pov-badge-detail').textContent = `${distStr} distance · ${angleStr} neck tilt · Audio estimate ${audioEstimate} · 🚪 ${exitInfo.label}`;
  document.getElementById('seat-pov-badge').classList.remove('hidden');

  const infoStrip = document.getElementById('ar-info-strip');
  if (infoStrip) {
    infoStrip.classList.remove('hidden');
    document.getElementById('ar-info-zone').textContent = `Row ${rowLabel} #${seatNumber}`;
    document.getElementById('ar-info-dist').textContent = distStr;
    document.getElementById('ar-info-angle').textContent = `${angleStr} tilt`;
    const sndEl = document.getElementById('ar-info-sound');
    if (sndEl) sndEl.textContent = audioEstimate;
    const extEl = document.getElementById('ar-info-exit');
    if (extEl) extEl.textContent = `${exitInfo.distMeters}m (${exitInfo.isLeft ? 'Left' : 'Right'})`;
  }
  document.getElementById('ar-empty-state').classList.add('hidden');
}

function refreshPovViews() {
  draw3dArScreen();
}

function setPovFormat(format) {
  povView.format = format;
  ['wide', 'scope', 'imax'].forEach(f => {
    const btn = document.getElementById(`pov-format-${f}`);
    const btnModal = document.getElementById(`vr-format-${f}`);
    const isActive = format === f;
    if (btn) {
      btn.classList.toggle('border-amber-300/50', isActive);
      btn.classList.toggle('text-amber-100', isActive);
      btn.classList.toggle('text-slate-300', !isActive);
    }
    if (btnModal) {
      btnModal.classList.toggle('border-amber-300/50', isActive);
      btnModal.classList.toggle('text-amber-100', isActive);
      btnModal.classList.toggle('text-slate-400', !isActive);
    }
  });
  refreshPovViews();
}

function setPovCrowd(show) {
  povView.crowd = show;
  refreshPovViews();
}

function cyclePovLighting() {
  const modes = ['movie', 'preshow', 'house'];
  const idx = modes.indexOf(povView.lighting || 'movie');
  setPovLighting(modes[(idx + 1) % modes.length]);
}

function setPovLighting(mode) {
  povView.lighting = mode;
  const btn = document.getElementById('pov-light-btn');
  const modalBtn = document.getElementById('vr-lighting-btn');
  const label = mode === 'movie' ? '🎬 Dark' : (mode === 'preshow' ? '🍿 Preshow' : '💡 House');
  if (btn) btn.textContent = label;
  if (modalBtn) modalBtn.textContent = label;
  refreshPovViews();
}

function setPovRecline(level) {
  povView.recline = level;
  [0, 1, 2].forEach(value => {
    const button = document.getElementById(`pov-recline-${value}`);
    const buttonModal = document.getElementById(`vr-recline-${value}`);
    const isActive = value === level;
    if (button) {
      button.classList.toggle('text-amber-200', isActive);
      button.classList.toggle('font-bold', isActive);
      button.classList.toggle('text-slate-400', !isActive);
    }
    if (buttonModal) {
      buttonModal.classList.toggle('text-amber-200', isActive);
      buttonModal.classList.toggle('font-bold', isActive);
      buttonModal.classList.toggle('text-slate-400', !isActive);
    }
  });
  refreshPovViews();
}

function resetVrView() {
  povView.yaw = 0;
  povView.pitch = 0;
  showExitPathHighlight = false;
  refreshPovViews();
}

// Pan VR camera to look directly at the nearest illuminated Exit Door
function lookAtNearestExit() {
  if (!activePovSeat) {
    activePovSeat = document.querySelector('.seat-btn.seat-sel') || document.querySelector('.seat-btn.seat-avail');
  }
  if (!activePovSeat) return;
  const exitInfo = computeExitInfo(activePovSeat);
  showExitPathHighlight = true;
  povView.yaw = exitInfo.isLeft ? -0.58 : 0.58;
  povView.pitch = 0.08;
  updateInspector(activePovSeat);
  showSeatARPreview(activePovSeat);
  refreshPovViews();
}

// ---- 4-DIRECTION SEAT HOPPING (◀ LEFT, ▶ RIGHT, ▲ FRONT ROW, ▼ BACK ROW) ----
function stepVrSeat(dRow, dCol) {
  const current = activePovSeat || document.querySelector('.seat-btn.seat-sel') || document.querySelector('.seat-btn.seat-avail');
  if (!current) return;

  const layoutRows = (cinemaLayout.classes || []).flatMap(cls => cls.rows || []);
  const curRowLabel = current.dataset.seatRow;
  const curSeatNum = parseInt(current.dataset.seatNumber || '1', 10);
  const curRowIdx = layoutRows.findIndex(r => r.label === curRowLabel);

  let nextSeat = null;

  if (dCol !== 0) {
    // Move left or right within the same row (skips blocked gaps automatically)
    const rowSeats = [...document.querySelectorAll(`.seat-btn[data-seat-row="${curRowLabel}"]`)];
    const idxInRow = rowSeats.findIndex(b => b === current);
    if (idxInRow !== -1) {
      const targetIdx = idxInRow + dCol;
      if (targetIdx >= 0 && targetIdx < rowSeats.length) {
        nextSeat = rowSeats[targetIdx];
      }
    }
  } else if (dRow !== 0 && curRowIdx !== -1) {
    // Note: layoutRows[0] is back row, layoutRows[last] is front row near screen
    const nextRowIdx = Math.max(0, Math.min(layoutRows.length - 1, curRowIdx + dRow));
    const targetRowLabel = layoutRows[nextRowIdx].label;
    const rowSeats = [...document.querySelectorAll(`.seat-btn[data-seat-row="${targetRowLabel}"]`)];
    if (rowSeats.length) {
      nextSeat = rowSeats.reduce((prev, curr) =>
        Math.abs(parseInt(curr.dataset.seatNumber) - curSeatNum) < Math.abs(parseInt(prev.dataset.seatNumber) - curSeatNum) ? curr : prev
      );
    }
  }

  if (nextSeat) {
    povView.yaw = 0;
    updateInspector(nextSeat);
    showSeatARPreview(nextSeat);
    if (document.getElementById('immersive-booking-layout')?.classList.contains('preview-fullscreen')) {
      draw3dArScreen();
    }
  }
}

// Keep backward compatibility with navVrSeat
function navVrSeat(direction) {
  stepVrSeat(0, direction);
}

function jumpVrSweetspot() {
  const allSeats = [...document.querySelectorAll('.seat-btn')];
  if (!allSeats.length) return;
  let bestSeat = allSeats[0];
  let maxScore = -1;
  allSeats.forEach(s => {
    const score = parseInt(s.dataset.score || '0', 10);
    if (score > maxScore) {
      maxScore = score;
      bestSeat = s;
    }
  });
  if (bestSeat) {
    resetVrView();
    updateInspector(bestSeat);
    showSeatARPreview(bestSeat);
    draw3dArScreen();
  }
}

function toggleVrSeatSelection() {
  if (!activePovSeat || activePovSeat.disabled) return;
  toggleSeatSelection(activePovSeat);
}

// Mobile Device Orientation Gyroscope Look
let gyroActive = false;
let gBaseBeta = null, gBaseGamma = null;

function toggleVrGyro() {
  if (!window.DeviceOrientationEvent) {
    alert("Device orientation (gyroscope) is not supported on this browser or device.");
    return;
  }
  if (typeof DeviceOrientationEvent.requestPermission === 'function') {
    DeviceOrientationEvent.requestPermission().then(state => {
      if (state === 'granted') enableGyro();
      else alert("Gyroscope permission denied.");
    }).catch(() => {});
  } else {
    enableGyro();
  }
}

function enableGyro() {
  gyroActive = !gyroActive;
  const btn = document.getElementById('vr-gyro-btn');
  if (btn) {
    btn.classList.toggle('border-cyan-400', gyroActive);
    btn.classList.toggle('text-cyan-200', gyroActive);
    btn.classList.toggle('bg-cyan-500/20', gyroActive);
  }
  if (gyroActive) {
    window.addEventListener('deviceorientation', handleGyroEvent);
  } else {
    window.removeEventListener('deviceorientation', handleGyroEvent);
    gBaseBeta = null; gBaseGamma = null;
  }
}

function handleGyroEvent(e) {
  if (!gyroActive || e.beta === null || e.gamma === null) return;
  if (gBaseBeta === null) {
    gBaseBeta = e.beta;
    gBaseGamma = e.gamma;
  }
  povView.yaw = Math.max(-1.2, Math.min(1.2, (e.gamma - gBaseGamma) / 30));
  povView.pitch = Math.max(-0.6, Math.min(0.6, (e.beta - gBaseBeta) / 30));
  refreshPovViews();
}

function attachPovDrag(canvas) {
  if (!canvas) return;
  if (canvas.dataset.povDragReady === 'true') return;
  canvas.dataset.povDragReady = 'true';
  canvas.style.touchAction = 'none';

  canvas.addEventListener('pointerdown', event => {
    if (event.target !== canvas) return;
    povView.dragging = true; povView.x = event.clientX; povView.y = event.clientY;
    canvas.setPointerCapture?.(event.pointerId);
  });
  canvas.addEventListener('pointermove', event => {
    if (!povView.dragging) return;
    povView.yaw = Math.max(-1.2, Math.min(1.2, povView.yaw + (event.clientX - povView.x) / Math.max(120, canvas.clientWidth) * 1.8));
    povView.pitch = Math.max(-.65, Math.min(.65, povView.pitch + (event.clientY - povView.y) / Math.max(120, canvas.clientHeight) * 1.4));
    povView.x = event.clientX; povView.y = event.clientY;
    refreshPovViews();
  });
  const stop = () => { povView.dragging = false; };
  canvas.addEventListener('pointerup', stop);
  canvas.addEventListener('pointercancel', stop);
  canvas.addEventListener('lostpointercapture', stop);
}
attachPovDrag(document.getElementById('seatPovCanvas'));

function toggleSeatSelection(seatButton) {
  if (!seatButton || seatButton.disabled || seatButton.dataset.partyOwner || !seatButton.dataset.seat) return false;
  updateInspector(seatButton);
  showSeatARPreview(seatButton);

  const id = seatButton.dataset.seat;
  if (selected.has(id)) {
    selected.delete(id);
    seatButton.classList.remove('seat-sel');
    seatButton.classList.add('seat-avail');
  } else {
    if (selected.size >= MAX_SEATS) {
      alert('You can select up to ' + MAX_SEATS + ' seats in one booking.');
      return false;
    }
    selected.set(id, { price: parseFloat(seatButton.dataset.price), cls: seatButton.dataset.class });
    seatButton.classList.remove('seat-avail');
    seatButton.classList.add('seat-sel');
  }

  paint();
  renderVRCinemaSeatMap(seatButton);
  draw3dArScreen();
  return true;
}

document.querySelectorAll('.seat-btn').forEach(b => {
  b.addEventListener('mouseenter', () => {
    try {
      updateInspector(b);
      showSeatARPreview(b);
      draw3dArScreen();
    } catch (err) {
      console.warn('Seat hover preview error:', err);
    }
  });
  b.addEventListener('click', () => {
    try {
      if (toggleSeatSelection(b)) postVRPreviewState(false, null, true);
    }
    catch (err) { console.warn('Seat selection error:', err); }
  });
});

// ---- WATCH TOGETHER: authenticated, serialized two-second polling ----
let partyPoll = null, partySyncRunning = false, partySyncPending = false;
function partyStatus(message) { document.getElementById('party-status').textContent = message; }
async function partyRequest(path, data = {}) {
  const res = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json', 'X-Party-CSRF':partyCSRF}, body:JSON.stringify(data)});
  let payload;
  try { payload = await res.json(); } catch (_) { throw new Error('Please sign in again or refresh this page.'); }
  return {res, data:payload};
}
function clearPartyMarks() {
  document.querySelectorAll('.seat-btn').forEach(b => {
    delete b.dataset.partyOwner; b.style.border = ''; b.style.boxShadow = '';
    b.title = b.dataset.originalTitle || b.title;
  });
}
function resetParty() {
  clearInterval(partyPoll); partyPoll = null; activePartyCode = '';
  clearPartyMarks();
  document.getElementById('party-squad-banner').classList.add('hidden');
  document.getElementById('party-btn-badge').textContent = 'Squad';
  const url = new URL(location.href); url.searchParams.delete('party'); history.replaceState({}, '', url);
  postVRPreviewState();
}
function activateParty(data) {
  activePartyCode = data.party_code;
  document.getElementById('squad-room-code').textContent = activePartyCode;
  document.getElementById('party-btn-badge').textContent = 'Code: ' + activePartyCode;
  document.getElementById('party-squad-banner').classList.remove('hidden');
  document.getElementById('party-close').classList.toggle('hidden', !data.is_host);
  const url = new URL(location.href); url.searchParams.set('party', activePartyCode); history.replaceState({}, '', url);
  if (!partyPoll) partyPoll = setInterval(() => { if (!document.hidden) syncParty(); }, 2000);
  syncParty();
}
async function initOrShowParty() {
  if (activePartyCode) { document.getElementById('party-squad-banner').classList.toggle('hidden'); return; }
  try {
    const {res, data} = await partyRequest(bookingContext.partyCreateUrl);
    if (!res.ok) throw new Error(data.error);
    activateParty(data);
  } catch (e) { partyStatus(e.message || 'Could not create party.'); }
}
async function joinPartyCode(code = document.getElementById('party-code-input').value) {
  code = code.trim().toUpperCase();
  if (!/^[0-9A-F]{6}$/.test(code)) { if (code === activePartyCode) resetParty(); partyStatus('Enter a valid six-character party code.'); return; }
  try {
    const {res, data} = await partyRequest(`/api/party/${code}/join`);
    if (!res.ok) throw new Error(data.error);
    if (data.showtime_id !== bookingContext.showtimeId) { location.assign(data.join_url); return; }
    if (activePartyCode && activePartyCode !== code) await leaveParty(false);
    activateParty(data);
  } catch (e) { if (code === activePartyCode) resetParty(); partyStatus(e.message || 'Could not join party.'); }
}
async function copySquadLink() {
  try { await navigator.clipboard.writeText(location.href); partyStatus('Party link copied.'); }
  catch (_) { partyStatus('Copy the party code above to share it.'); }
}
async function leaveParty(close) {
  if (!activePartyCode) return;
  try {
    const {res, data} = await partyRequest(`/api/party/${activePartyCode}/${close ? 'close' : 'leave'}`);
    if (!res.ok) throw new Error(data.error);
    resetParty(); partyStatus(close ? 'Party closed.' : 'You left the party.');
  } catch (e) { partyStatus(e.message); }
}
async function syncParty() {
  if (!activePartyCode) return;
  if (partySyncRunning) { partySyncPending = true; return; }
  partySyncRunning = true;
  const code = activePartyCode;
  try {
    const {res, data} = await partyRequest(`/api/party/${code}/sync`, {showtime_id:bookingContext.showtimeId, selected_seats:[...selected.keys()]});
    if (code !== activePartyCode) return;
    if (res.status === 410 || res.status === 404 || res.status === 403 || res.status === 401) { resetParty(); throw new Error(data.error); }
    if (!res.ok && res.status !== 409) throw new Error(data.error);
    partyStatus(data.error || 'Connected · updates every 2 seconds');
    const roster = document.getElementById('squad-member-roster'); roster.replaceChildren();
    (data.members || []).forEach(m => {
      const chip = document.createElement('span');
      chip.className = 'rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white';
      chip.textContent = `${m.user_name}${m.is_me ? ' (You)' : ''}${m.is_host ? ' · Host' : ''}: ${m.seats.length ? m.seats.join(', ') : 'Choosing…'}`;
      roster.appendChild(chip);
    });
    let changed = false;
    (data.conflicts || []).forEach(id => {
      if (selected.delete(id)) changed = true;
      const b = document.querySelector(`.seat-btn[data-seat="${id}"]`);
      b?.classList.remove('seat-sel'); if (b && !b.disabled) b.classList.add('seat-avail');
    });
    clearPartyMarks();
    document.querySelectorAll('.seat-btn').forEach(b => {
      const owner = data.squad_seats?.[b.dataset.seat];
      if (owner && !selected.has(b.dataset.seat)) {
        b.dataset.originalTitle ||= b.title; b.dataset.partyOwner = owner.user_name;
        b.style.border = `2px solid ${owner.color}`; b.title = `${owner.user_name} is selecting ${b.dataset.seat}`;
      }
    });
    if (changed) paint(false);
    postVRPreviewState();
  } catch (e) { partyStatus(e.message || 'Connection interrupted; retrying…'); }
  finally {
    partySyncRunning = false;
    if (partySyncPending) { partySyncPending = false; syncParty(); }
  }
}
if (activePartyCode) joinPartyCode(activePartyCode);
window.addEventListener('pagehide', () => clearInterval(partyPoll));

let availabilityPollRunning = false;
const availabilityPoll = setInterval(async () => {
  if (availabilityPollRunning || document.hidden) return;
  availabilityPollRunning = true;
  try {
    const res = await fetch(bookingContext.availabilityUrl);
    if (!res.ok) throw new Error('Seat availability request failed');
    const data = await res.json();
    const booked = new Set(data.booked || []);
    const held = new Set(data.held || []);
    let selectionChanged = false;
    document.querySelectorAll('.seat-btn').forEach(b => {
      const id = b.dataset.seat;
      const unavailable = booked.has(id) || held.has(id);
      if (unavailable && selected.has(id)) {
        selected.delete(id);
        b.classList.remove('seat-sel');
        selectionChanged = true;
      }
      b.disabled = unavailable;
      b.classList.toggle('seat-avail', !unavailable && !selected.has(id));
      b.classList.toggle('seat-sel', !unavailable && selected.has(id));
      b.classList.toggle('seat-booked', booked.has(id));
      b.classList.toggle('seat-held', held.has(id));
    });
    if (selectionChanged) paint();
    updateImmersiveBookingPanel();
    postVRPreviewState();
  } catch (e) {} finally { availabilityPollRunning = false; }
}, 10000);
window.addEventListener('pagehide', () => clearInterval(availabilityPoll), { once: true });

setInterval(async () => {
  try {
    const res = await fetch(bookingContext.liveInfoUrl);
    const d = await res.json();
    const el = document.getElementById('live-seats-left');
    if (el) el.innerHTML = `${d.seats_left} <span class="text-xs font-medium text-slate-500">/ ${d.total_seats}</span>`;
  } catch(e) {}
}, 15000);

function toggleTheaterView(mode) {
  const viewport = document.getElementById('seating-viewport');
  const previewPanel = document.getElementById('ar-preview-panel');
  const theaterWrapper = document.getElementById('ar-theater-wrapper');
  const btn2d = document.getElementById('btn-view-2d');
  const btn3d = document.getElementById('btn-view-3d');

  if (mode === '3d') {
    btn3d.className = "px-3 py-1 rounded-lg text-xs font-bold transition bg-[#C9A84C] text-white shadow";
    btn2d.className = "px-3 py-1 rounded-lg text-xs font-bold transition text-slate-400 hover:text-white";
    viewport.classList.add('hidden');
    previewPanel.classList.remove('hidden');
    theaterWrapper.classList.add('theater-expanded');
    btn3d.setAttribute('aria-pressed', 'true');
    btn2d.setAttribute('aria-pressed', 'false');
    document.getElementById('immersive-booking-layout')?.classList.remove('hidden');
    ensureInlinePreview();
    postVRPreviewState();
    syncVRPreviewActivity();
  } else {
    btn2d.className = "px-3 py-1 rounded-lg text-xs font-bold transition bg-[#C9A84C] text-white shadow";
    btn3d.className = "px-3 py-1 rounded-lg text-xs font-bold transition text-slate-400 hover:text-white";
    close3dArModal();
    if (inlineTourTimer) toggleInlineTour();
    document.getElementById('immersive-booking-layout')?.classList.add('hidden');
    viewport.classList.remove('hidden');
    previewPanel.classList.add('hidden');
    theaterWrapper.classList.remove('theater-expanded');
    btn3d.setAttribute('aria-pressed', 'false');
    btn2d.setAttribute('aria-pressed', 'true');
    syncVRPreviewActivity();
    const frame = document.getElementById('vr-inline-frame');
    if (frame?.dataset.loaded) {
      frame.contentWindow?.postMessage({ type: 'cinewave:release-trailer' }, location.origin);
    }
  }
}

let inlineTourTimer = null;
let inlineTourStep = 0;
const inlineTourPresets = ['overview', 'stage', 'balcony', 'birdseye'];
function setInlineCamera(preset) {
  const frame = document.getElementById('vr-inline-frame');
  if (!frame?.contentWindow || !frame.dataset.loaded) return;
  frame.contentWindow.postMessage({ type: 'cinewave:camera-preset', preset }, window.location.origin);
  document.querySelectorAll('.inline-camera-btn').forEach(button => {
    const active = button.dataset.preset === preset;
    button.classList.toggle('active', active);
    button.classList.toggle('text-white', active);
    button.classList.toggle('text-slate-400', !active);
    button.classList.toggle('bg-cyan-500/20', active);
    button.classList.toggle('border', active);
    button.classList.toggle('border-cyan-400/40', active);
  });
}
function toggleInlineTour() {
  const button = document.getElementById('inline-tour-btn');
  if (inlineTourTimer) {
    clearInterval(inlineTourTimer);
    inlineTourTimer = null;
    button.textContent = 'Auto tour';
    button.classList.remove('bg-amber-400/20');
    return;
  }
  inlineTourStep = 0;
  setInlineCamera(inlineTourPresets[inlineTourStep]);
  button.textContent = 'Stop tour';
  button.classList.add('bg-amber-400/20');
  inlineTourTimer = setInterval(() => {
    inlineTourStep = (inlineTourStep + 1) % inlineTourPresets.length;
    setInlineCamera(inlineTourPresets[inlineTourStep]);
  }, 4500);
}

function suggestSmartSeats() {
  const pSize = parseInt(document.getElementById('smart-party-size').value || '2');
  const rows = document.querySelectorAll('#seating-grid-container .flex.items-center.justify-center');
  let bestBlock = null;
  let maxBlockScore = -1;

  rows.forEach(row => {
    const seatsInRow = [...row.querySelectorAll('.seat-avail')];
    for (let i = 0; i <= seatsInRow.length - pSize; i++) {
      const candidateBlock = seatsInRow.slice(i, i + pSize);
      let isContiguous = true;
      for (let k = 0; k < candidateBlock.length - 1; k++) {
        const num1 = parseInt(candidateBlock[k].textContent || '0');
        const num2 = parseInt(candidateBlock[k+1].textContent || '0');
        if (num2 !== num1 + 1) {
          isContiguous = false;
          break;
        }
      }

      if (isContiguous) {
        const avgScore = candidateBlock.reduce((acc, s) => acc + parseInt(s.dataset.score || '80'), 0) / pSize;
        if (avgScore > maxBlockScore) {
          maxBlockScore = avgScore;
          bestBlock = candidateBlock;
        }
      }
    }
  });

  if (bestBlock && bestBlock.length === pSize) {
    document.querySelectorAll('.seat-sel').forEach(b => {
      const id = b.dataset.seat;
      selected.delete(id);
      b.classList.remove('seat-sel');
      b.classList.add('seat-avail');
    });

    bestBlock.forEach(b => {
      const id = b.dataset.seat;
      selected.set(id, { price: parseFloat(b.dataset.price), cls: b.dataset.class });
      b.classList.remove('seat-avail');
      b.classList.add('seat-sel');
      b.classList.add('animate-bounce');
      setTimeout(() => b.classList.remove('animate-bounce'), 1000);
    });

    paint();
    updateInspector(bestBlock[0]);
    showSeatARPreview(bestBlock[0]);
    alert(`✨ Found the top ${pSize} adjacent seats (Score: ${Math.round(maxBlockScore)}/100)!`);
  } else {
    alert(`Could not find ${pSize} contiguous available seats in a single row. Try a smaller group size.`);
  }
}

function open3dArModal(showTrailer = false) {
  const layout = document.getElementById('immersive-booking-layout');
  if (layout.classList.contains('preview-fullscreen')) return;
  fullPreviewTrigger = document.activeElement;
  fullPreviewOverflow = document.body.style.overflow;
  toggleTheaterView('3d');
  pendingPreviewTrailer = showTrailer;
  activePovSeat ||= document.querySelector('.seat-btn.seat-sel[data-seat]') || document.querySelector('.seat-btn.seat-avail[data-seat]');
  layout.classList.add('preview-fullscreen');
  const exitButton = document.getElementById('close-full-preview');
  exitButton.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
  exitButton.focus({ preventScroll: true });
  syncVRPreviewFullscreen();
  syncVRPreviewActivity();
}

function close3dArModal() {
  const layout = document.getElementById('immersive-booking-layout');
  pendingPreviewTrailer = false;
  if (!layout?.classList.contains('preview-fullscreen')) return;
  document.getElementById('vr-inline-frame')?.contentWindow?.postMessage({ type: 'cinewave:pause-trailer' }, location.origin);
  layout.classList.remove('preview-fullscreen');
  document.getElementById('close-full-preview')?.classList.add('hidden');
  document.body.style.overflow = fullPreviewOverflow;
  fullPreviewTrigger?.focus({ preventScroll: true });
  fullPreviewTrigger = null;
  syncVRPreviewFullscreen();
  syncVRPreviewActivity();
}

function syncVRPreviewFullscreen() {
  const frame = document.getElementById('vr-inline-frame');
  if (!frame?.dataset.loaded || !frame.contentWindow) return;
  const active = document.getElementById('immersive-booking-layout')?.classList.contains('preview-fullscreen');
  frame.contentWindow.postMessage({ type: 'cinewave:fullscreen', active }, location.origin);
}

function syncVRPreviewActivity() {
  const frame = document.getElementById('vr-inline-frame');
  if (!frame?.dataset.loaded || !frame.contentWindow) return;
  const bounds = frame.getBoundingClientRect();
  const active = document.getElementById('btn-view-3d').getAttribute('aria-pressed') === 'true'
    && !document.hidden && bounds.height > 0 && bounds.bottom > 0 && bounds.top < window.innerHeight;
  frame.contentWindow.postMessage({ type: active ? 'cinewave:resume' : 'cinewave:pause' }, location.origin);
  if (active && frame.dataset.ready && pendingPreviewTrailer) {
    pendingPreviewTrailer = false;
    frame.contentWindow.postMessage({ type: 'cinewave:show-trailer' }, location.origin);
  }
}

function postVRPreviewState(isInitial = false, onlyFrame = null, cameraRequest = false) {
  const frames = onlyFrame ? [onlyFrame] : [document.getElementById('vr-inline-frame')];
  frames.forEach(frame => {
    if (!frame?.contentWindow || !frame.dataset.loaded) return;
    frame.contentWindow.postMessage({
      type: isInitial ? 'cinewave:init' : 'cinewave:selection-state',
      selectedSeats: [...selected.keys()],
      unavailableSeats: [...document.querySelectorAll('[data-seat].seat-booked, [data-seat].seat-held, [data-seat][data-party-owner]')].map(button => button.dataset.seat),
      bookedSeats: [...document.querySelectorAll('[data-seat].seat-booked')].map(button => button.dataset.seat),
      heldSeats: [...document.querySelectorAll('[data-seat].seat-held')].map(button => button.dataset.seat),
      // Keep the initial camera in the full-room view. Later seat changes
      // still move the camera to the seat the customer is inspecting.
      activeSeat: activePovSeat?.dataset?.seat || '',
      cameraRequest: Boolean(cameraRequest)
    }, window.location.origin);
  });
}

window.addEventListener('message', event => {
  const frames = [document.getElementById('vr-inline-frame')];
  const fromPreview = frames.some(frame => frame && event.source === frame.contentWindow);
  if (!fromPreview || event.origin !== window.location.origin) return;
  if (event.data?.type === 'cinewave:ready') {
    const frame = frames[0];
    frame.dataset.ready = 'true';
    postVRPreviewState(false, frame);
    syncVRPreviewActivity();
    return;
  }
  if (event.data?.type === 'cinewave:fallback-close') {
    toggleTheaterView('2d');
    return;
  }
  if (event.data?.type === 'cinewave:exit-fullscreen') {
    close3dArModal();
    return;
  }
  if (event.data?.type === 'cinewave:toggle-seat') {
    const seatButton = [...document.querySelectorAll('.seat-btn')].find(button => button.dataset.seat === event.data.seatId);
    if (seatButton && !seatButton.disabled) toggleSeatSelection(seatButton);
    postVRPreviewState();
  } else if (event.data?.type === 'cinewave:checkout') {
    if (!selected.size) {
      alert('Choose at least one available seat first.');
      return;
    }
    close3dArModal();
    document.getElementById('booking-form').requestSubmit();
  }
});

function renderVRCinemaSeatMap(activeSeat) {
  const root = document.getElementById('vr-seat-map');
  if (!root) return;
  root.replaceChildren();
  const activeId = activeSeat?.dataset?.seat || '';
  let rowIndex = 0;
  for (const cls of (cinemaLayout.classes || [])) {
    const classLabel = document.createElement('div');
    classLabel.className = 'flex items-center justify-between px-1 pt-2 pb-1 text-[9px] font-bold uppercase tracking-wider text-slate-400 first:pt-0';
    classLabel.innerHTML = `<span>${cls.name || cls.code || 'Seats'}</span><span class="text-amber-400/80">₹${cls.price}</span>`;
    root.appendChild(classLabel);

    for (const row of (cls.rows || [])) {
      const rowLine = document.createElement('div');
      rowLine.dataset.vrRow = 'true';
      rowLine.dataset.vrRowIndex = String(rowIndex);
      const isCurrentRow = row.label === (activeSeat?.dataset?.seatRow || activeId.replace(/\d+$/, ''));
      rowLine.className = `flex items-center gap-1 rounded-md px-1 py-0.5 transition ${isCurrentRow ? 'bg-amber-300/10 ring-1 ring-amber-300/20' : 'hover:bg-white/5'}`;

      const rowName = document.createElement('span');
      rowName.className = `w-4 shrink-0 text-[9px] font-bold text-right ${isCurrentRow ? 'text-amber-300 font-black' : 'text-slate-400'}`;
      rowName.textContent = row.label || '';
      rowLine.appendChild(rowName);

      const track = document.createElement('div');
      track.className = 'flex flex-1 items-center justify-center gap-[2px] min-w-0';
      const offset = document.createElement('span');
      offset.style.width = `${Math.max(0, Number(row.offset || 0)) * 5}px`;
      offset.className = 'shrink-0';
      track.appendChild(offset);

      const start = Number(row.start || 1);
      const seatSpan = Math.max(1, Number(row.seat_span || 1));
      const blocked = new Set(row.blocked || []);
      const aisles = new Set((row.aisles_after || []).map(Number));

      for (let number = start; number < start + Number(row.count || 0); number++) {
        const seatId = `${row.label}${number}`;
        const isBlocked = blocked.has(seatId);
        const isViewed = seatId === activeId;
        const isSelected = selected.has(seatId);
      const sourceSeat = document.querySelector(`.seat-btn[data-seat="${seatId}"]`);
      const isUnavailable = !sourceSeat || sourceSeat.disabled;

        const marker = document.createElement('button');
        marker.type = 'button';
        marker.title = `${isUnavailable ? 'Unavailable · ' : ''}Seat ${seatId} (${cls.name} · ₹${cls.price})`;
        marker.dataset.vrSeatBtn = seatId;

        if (isBlocked) {
          marker.disabled = true;
          marker.className = 'h-[7px] w-[7px] shrink-0 rounded-[2px] border border-slate-700 opacity-25 cursor-not-allowed';
        } else {
          if (isViewed) {
            marker.className = 'h-[9px] w-[9px] shrink-0 rounded-[2px] bg-amber-300 ring-2 ring-amber-300 shadow-[0_0_8px_#f59e0b] animate-pulse z-10 cursor-pointer';
          } else if (isSelected) {
            marker.className = 'h-[8px] w-[8px] shrink-0 rounded-[2px] bg-emerald-400 ring-1 ring-emerald-300 shadow-[0_0_6px_#10b981] cursor-pointer';
          } else if (isUnavailable) {
            marker.className = 'h-[7px] w-[7px] shrink-0 rounded-[2px] bg-rose-950 border border-rose-700/70 opacity-70 cursor-pointer';
          } else {
            marker.className = 'h-[7px] w-[7px] shrink-0 rounded-[2px] bg-slate-600 hover:bg-amber-200 transition-colors cursor-pointer';
          }
          marker.onclick = (e) => {
            e.stopPropagation();
            const seatEl = sourceSeat;
            if (seatEl) {
              povView.yaw = 0;
              if (!seatEl.disabled) toggleSeatSelection(seatEl);
              else {
                updateInspector(seatEl);
                showSeatARPreview(seatEl);
                draw3dArScreen();
              }
            }
          };
        }
        if (seatSpan > 1 && !isViewed) marker.style.width = `${seatSpan * 7}px`;
        track.appendChild(marker);
        if (aisles.has(number)) {
          const aisle = document.createElement('span');
          aisle.className = 'w-2.5 shrink-0';
          track.appendChild(aisle);
        }
      }
      rowLine.appendChild(track);
      root.appendChild(rowLine);
      rowIndex++;
    }
  }
}

async function enterVRView() {
  const frame = document.getElementById('vr-inline-frame');
  if (!frame) return;
  try {
    if (frame.requestFullscreen) await frame.requestFullscreen();
  } catch (_) {
    // The preview already fills the viewport when opened.
  }
}

// Global keyboard arrow navigation for 4-way seat hopping
document.addEventListener('keydown', event => {
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
  if (event.key === 'Escape' && document.getElementById('immersive-booking-layout')?.classList.contains('preview-fullscreen')) {
    close3dArModal();
    return;
  }
  if (event.key === 'ArrowLeft')  { event.preventDefault(); stepVrSeat(0, -1); }
  if (event.key === 'ArrowRight') { event.preventDefault(); stepVrSeat(0, 1); }
  if (event.key === 'ArrowUp')    { event.preventDefault(); stepVrSeat(1, 0); }
  if (event.key === 'ArrowDown')  { event.preventDefault(); stepVrSeat(-1, 0); }
  if (document.getElementById('immersive-booking-layout')?.classList.contains('preview-fullscreen') && event.key === ' ') {
    event.preventDefault();
    toggleVrSeatSelection();
  }
});

document.addEventListener('fullscreenchange', () => {
  if (document.getElementById('immersive-booking-layout')?.classList.contains('preview-fullscreen')) postVRPreviewState();
});

function draw3dArScreen() {
  postVRPreviewState();
}
function updateVrReserveButton() {
  const btn = document.getElementById('vr-reserve-btn');
  const floatBtn = document.getElementById('vr-float-reserve-btn');
  const cartSummary = document.getElementById('vr-cart-summary');
  if (!activePovSeat) return;
  const seatId = activePovSeat.dataset.seat;
  const isSelected = selected.has(seatId);
  const isUnavailable = activePovSeat.disabled;
  const price = activePovSeat.dataset.price;

  const labelSelect = `Reserve Seat ${seatId} · ₹${price}`;
  const labelRemove = `Seat ${seatId} Selected · Remove`;

  if (btn) {
    if (isUnavailable) {
      btn.disabled = true;
      btn.innerHTML = `<i class="fa-solid fa-ban text-rose-300"></i><span>Seat ${seatId} unavailable</span>`;
      btn.className = "w-full rounded-xl border border-rose-500/20 bg-rose-950/30 px-3 py-3 text-xs font-bold text-rose-200 cursor-not-allowed";
    } else if (isSelected) {
      btn.disabled = false;
      btn.innerHTML = `<i class="fa-solid fa-circle-check text-emerald-300"></i><span>${labelRemove}</span>`;
      btn.className = "w-full rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-extrabold text-xs px-3 py-3 transition flex items-center justify-center gap-2 shadow-lg shadow-emerald-950/40";
    } else {
      btn.disabled = false;
      btn.innerHTML = `<i class="fa-solid fa-plus-circle text-amber-950"></i><span>${labelSelect}</span>`;
      btn.className = "w-full rounded-xl bg-gradient-to-r from-amber-400 via-amber-300 to-amber-500 hover:brightness-110 text-slate-950 font-black text-xs px-3 py-3 transition flex items-center justify-center gap-2 shadow-lg shadow-amber-950/40";
    }
  }

  if (floatBtn) {
    if (isSelected) {
      floatBtn.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-300 animate-ping"></span><span class="font-black text-white">✓ Seat ${seatId} Selected</span>`;
      floatBtn.className = "h-8 px-3 rounded-xl bg-emerald-600/90 hover:bg-emerald-500 border border-emerald-400/50 text-white text-[10px] font-bold transition flex items-center gap-1.5 shadow-xl";
    } else {
      floatBtn.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-400"></span><span class="font-black text-slate-950">+ Select Seat ${seatId} · ₹${price}</span>`;
      floatBtn.className = "h-8 px-3 rounded-xl bg-gradient-to-r from-amber-300 to-amber-400 hover:from-amber-200 hover:to-amber-300 border border-amber-300/80 text-slate-950 text-[10px] font-bold transition flex items-center gap-1.5 shadow-xl shadow-amber-950/40";
    }
  }

  if (cartSummary) {
    const count = selected.size;
    const total = [...selected.values()].reduce((a, s) => a + s.price, 0);
    if (count > 0) {
      cartSummary.innerHTML = `<div class="flex items-center justify-between text-[11px] font-bold px-1"><span class="text-slate-300">${count} Seat${count > 1 ? 's' : ''} in cart</span><span class="text-amber-300">Total: ₹${total.toFixed(0)}</span></div>`;
      cartSummary.classList.remove('hidden');
    } else {
      cartSummary.classList.add('hidden');
    }
  }
}

try {
  const defaultSeat = document.querySelector('.seat-btn.seat-avail');
  if (defaultSeat) {
    updateInspector(defaultSeat);
    showSeatARPreview(defaultSeat);
  }
} catch (err) {
  console.warn('Initial 3D seat preview error:', err);
}
window.addEventListener('resize', () => {
  draw3dArScreen();
});

const inlineVrFrame = document.getElementById('vr-inline-frame');
if (inlineVrFrame && 'IntersectionObserver' in window) new IntersectionObserver(syncVRPreviewActivity).observe(inlineVrFrame);
document.addEventListener('visibilitychange', syncVRPreviewActivity);
window.addEventListener('pageshow', syncVRPreviewActivity);
const immersiveSection = document.createElement('section');
immersiveSection.id = 'immersive-booking-layout';
immersiveSection.className = 'immersive-booking-layout hidden';
immersiveSection.innerHTML = `
  <div class="immersive-viewer-column"></div>
  <aside id="immersive-seat-sidebar" class="immersive-seat-sidebar">
    <p class="immersive-eyebrow">SEAT CLASSES</p>
    <div data-seat-classes class="space-y-2.5"></div>
    <div class="immersive-legend"><span><i class="legend-booked"></i>Booked</span><span><i class="legend-picked"></i>Your pick</span></div>
    <p class="immersive-eyebrow mt-5">QUICK PICK</p>
    <div class="flex gap-2">
      <select id="immersive-party-size" aria-label="Number of seats" class="immersive-size-select">
        <option value="1">1 seat</option><option value="2" selected>2 seats</option><option value="3">3 seats</option><option value="4">4 seats</option><option value="6">6 seats</option>
      </select>
      <button type="button" onclick="immersiveBestSeats()" class="immersive-best-button">✦ Best seats</button>
    </div>
    <p class="immersive-eyebrow mt-5">YOUR SEATS <span data-selected-count>0</span></p>
    <div data-selected-seats class="immersive-selected-seats">Tap any available seat in the hall</div>
    <div class="immersive-checkout-row"><div><small>Tickets total</small><strong data-selected-total>₹0</strong></div><button type="button" data-immersive-checkout onclick="document.getElementById('booking-form').requestSubmit()" disabled>Continue</button></div>
  </aside>`;
const viewerColumn = immersiveSection.querySelector('.immersive-viewer-column');
const immersiveViewer = document.getElementById('ar-preview-panel');
immersiveViewer?.classList.add('hidden');
if (immersiveViewer) {
  viewerColumn.appendChild(immersiveViewer);
  const header = document.getElementById('seat-map-mode-controls');
  if (header?.parentNode) header.insertAdjacentElement('afterend', immersiveSection);
  else document.querySelector('main')?.prepend(immersiveSection);
}
updateImmersiveBookingPanel();
// The iframe has no src until an explicit 3D request. Reuse it for every mode/fullscreen switch.
function ensureInlinePreview() {
  if (!inlineVrFrame || inlineVrFrame.hasAttribute('src')) return;
  inlineVrFrame.onload = () => {
    if (!inlineVrFrame.getAttribute('src')) return;
    inlineVrFrame.dataset.loaded = 'true';
    postVRPreviewState(true, inlineVrFrame);
    syncVRPreviewFullscreen();
    syncVRPreviewActivity();
  };
  inlineVrFrame.src = inlineVrFrame.dataset.src;
}
let restored = reservedSeats;
if (!restored.length) {
  try { restored = JSON.parse(sessionStorage.getItem(draftKey)) || []; } catch {}
}
if (Array.isArray(restored) && restored.length) {
  const ids = new Set(restored.slice(0, MAX_SEATS));
  document.querySelectorAll('.seat-btn').forEach((button) => {
    if (!button.disabled && ids.has(button.dataset.seat)) {
      selected.set(button.dataset.seat, { price: Number(button.dataset.price), cls: button.dataset.class });
      button.classList.remove('seat-avail');
      button.classList.add('seat-sel');
    }
  });
  paint(false);
}
toggleTheaterView('2d');
