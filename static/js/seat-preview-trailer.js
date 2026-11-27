/* Decode a native video into the auditorium's existing screen texture. */
window.createSeatPreviewTrailer = function (video, toolbar, isActive) {
  const controls = toolbar.querySelector('[data-projection-controls]');
  const playButton = toolbar.querySelector('[data-projection-play]');
  const soundButton = toolbar.querySelector('[data-projection-sound]');
  const message = toolbar.querySelector('[data-projection-status]');
  const external = toolbar.querySelector('[data-projection-external]');
  const original = video.dataset.src;
  const optimized = video.dataset.optimizedSrc;
  const sample = document.createElement('canvas');
  sample.width = 12;
  sample.height = 4;
  const sampleContext = sample.getContext('2d', { willReadFrequently: true });
  let started = false;
  let failed = false;
  let lastFrame;
  let nextLightSample = 0;

  function updateControls() {
    playButton.textContent = video.paused ? 'Play' : 'Pause';
    soundButton.textContent = video.muted ? 'Unmute' : 'Mute';
  }

  function play() {
    if (!isActive()) return;
    started = true;
    failed = false;
    external.hidden = true;
    if (!video.hasAttribute('src')) video.src = optimized || original;
    else if (video.error) video.load();
    if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) message.textContent = 'Loading trailer…';
    const source = video.src;
    video.play().catch(error => {
      if (!started || !isActive() || source !== video.src) return;
      if (error.name === 'NotAllowedError') {
        message.textContent = 'Press Play to start the trailer.';
      } else if (error.name !== 'AbortError' && !video.error) {
        fail();
      }
    });
    updateControls();
  }

  function fail() {
    failed = true;
    video.pause();
    message.textContent = 'The trailer couldn’t play on the cinema screen.';
    external.hidden = false;
    updateControls();
  }

  video.addEventListener('error', () => {
    if (!started || !video.hasAttribute('src')) return;
    if (optimized && video.src === optimized) {
      video.src = original;
      play();
    } else {
      fail();
    }
  });
  video.addEventListener('playing', () => {
    if (!started || !isActive()) {
      video.pause();
      return;
    }
    message.textContent = '';
    updateControls();
  });
  video.addEventListener('pause', updateControls);
  video.addEventListener('volumechange', updateControls);
  video.addEventListener('waiting', () => {
    if (started && !video.paused) message.textContent = 'Buffering trailer…';
  });
  playButton.addEventListener('click', () => video.paused ? play() : video.pause());
  toolbar.querySelector('[data-projection-restart]').addEventListener('click', () => {
    if (video.readyState > 0) video.currentTime = 0;
    play();
  });
  soundButton.addEventListener('click', () => { video.muted = !video.muted; });

  function start() {
    if (!started) play();
  }

  function hasFrame() {
    return started && !failed && video.hasAttribute('src') &&
      video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.videoWidth > 0;
  }

  function draw(context, width, height, screenAspect, now, setLight) {
    const frame = video.currentTime;
    if (frame === lastFrame) return false;
    lastFrame = frame;
    context.fillStyle = '#000';
    context.fillRect(0, 0, width, height);

    // Sample a small canvas before drawing to the texture, so a blocked CORS
    // resource cannot taint the canvas used by WebGL or the other screen modes.
    if (now >= nextLightSample) {
      try {
        sampleContext.drawImage(video, 0, 0, sample.width, sample.height);
        const colors = sampleContext.getImageData(0, 0, sample.width, sample.height).data;
        const zones = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
        for (let pixel = 0; pixel < colors.length; pixel += 4) {
          const zone = Math.floor((pixel / 4 % sample.width) / 4);
          for (let channel = 0; channel < 3; channel++) zones[zone][channel] += colors[pixel + channel];
        }
        zones.forEach((color, zone) => setLight(zone, ...color.map(value => value / (16 * 255))));
      } catch (error) {
        if (error.name !== 'SecurityError') throw error;
        sample.width = 12;
        video.removeAttribute('src');
        video.load();
        fail();
        return true;
      }
      nextLightSample = now + 200;
    }
    const aspect = video.videoWidth / video.videoHeight / screenAspect;
    const fittedWidth = width * Math.min(1, aspect);
    const fittedHeight = height * Math.min(1, 1 / aspect);
    context.drawImage(video, (width - fittedWidth) / 2, (height - fittedHeight) / 2, fittedWidth, fittedHeight);
    return true;
  }

  function release() {
    started = false;
    failed = false;
    lastFrame = undefined;
    nextLightSample = 0;
    video.pause();
    if (video.hasAttribute('src')) {
      video.removeAttribute('src');
      video.load();
    }
    video.muted = true;
    updateControls();
    message.textContent = '';
    external.hidden = true;
  }

  controls.hidden = false;
  return { start, play, hasFrame, draw, pause: () => video.pause(), release };
};
