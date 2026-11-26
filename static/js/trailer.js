(() => {
  const dialog = document.getElementById('trailer-modal');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const viewport = dialog.querySelector('[data-trailer-player]');
  const error = dialog.querySelector('[data-trailer-error]');
  const external = dialog.querySelector('[data-trailer-external]');
  let trigger;
  let player;
  let youtubeApi;

  function showError() {
    error.textContent = 'The trailer could not play here. Try opening the original video.';
    error.hidden = false;
  }

  function getYouTubeAPI() {
    if (window.YT?.Player) return Promise.resolve(window.YT);
    if (!youtubeApi) {
      youtubeApi = new Promise((resolve, reject) => {
        const previous = window.onYouTubeIframeAPIReady;
        window.onYouTubeIframeAPIReady = () => {
          previous?.();
          resolve(window.YT);
        };
        const script = document.createElement('script');
        script.src = 'https://www.youtube.com/iframe_api';
        script.onerror = reject;
        document.head.append(script);
      });
    }
    return youtubeApi;
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-trailer-url]');
    if (!button || event.ctrlKey || event.metaKey || event.shiftKey) return;
    event.preventDefault();
    trigger = button;
    error.hidden = true;
    external.href = button.href;
    const youtube = button.dataset.trailerProvider === 'youtube';
    external.textContent = youtube ? 'Watch on YouTube' : 'Open original video';
    const media = document.createElement(youtube ? 'iframe' : 'video');
    media.addEventListener('error', showError);
    if (youtube) {
      const url = new URL(button.dataset.trailerUrl);
      url.searchParams.set('enablejsapi', '1');
      url.searchParams.set('origin', location.origin);
      media.src = url.href;
      media.title = 'YouTube trailer';
      media.allow = 'encrypted-media; fullscreen; picture-in-picture';
      media.allowFullscreen = true;
      media.referrerPolicy = 'strict-origin-when-cross-origin';
      getYouTubeAPI().then((api) => {
        if (dialog.open && viewport.contains(media)) {
          player = new api.Player(media, { events: { onError: showError } });
        }
      }).catch(() => {});
    } else {
      media.src = button.dataset.trailerUrl;
      media.controls = true;
      media.playsInline = true;
      media.preload = 'metadata';
    }
    viewport.replaceChildren(media);
    dialog.showModal();
  });

  dialog.addEventListener('close', () => {
    player?.destroy();
    player = null;
    viewport.querySelector('video')?.pause();
    viewport.replaceChildren();
    trigger?.focus();
  });
})();
