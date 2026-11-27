/* Real-browser QA with Chrome, Node and the repository's virtual environment. */
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const ChromeQA = require('./phase_2_1_3_chrome.cjs');

const root = path.resolve(__dirname, '..');
const output = path.join(root, 'instance', 'cinewave-visual-qa');
const projectionOnly = process.argv.includes('--projection-only');
const selectedPages = process.argv.slice(2).filter(arg => arg !== '--projection-only');
const chrome = process.env.CINEWAVE_QA_CHROME || (process.platform === 'win32'
    ? 'C:/Program Files/Google/Chrome/Application/chrome.exe' : 'google-chrome');
const python = process.env.CINEWAVE_QA_PYTHON || path.join(root, '.venv',
    process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function until(check, message, timeout = 15000) {
    const deadline = Date.now() + timeout;
    do {
        const value = await check();
        if (value) return value;
        await pause(90);
    } while (Date.now() < deadline);
    throw new Error(message);
}

async function startupLine(child) {
    const lines = readline.createInterface({ input: child.stdout });
    let startup;
    lines.on('line', (line) => { if (line.startsWith('{')) startup = JSON.parse(line); });
    return until(() => {
        if (child.exitCode !== null) throw new Error('The fixture server exited during startup.');
        return startup;
    }, 'The fixture server did not start.', 60000);
}

// This function runs inside Chrome. Walk through transparent ancestors to find
// the backing color behind text or a control.
function readability() {
    const rgb = (value) => value.match(/[\d.]+/g).map(Number);
    const composite = (front, back) => {
        const alpha = front[3] ?? 1;
        return back.slice(0, 3).map((channel, i) => front[i] * alpha + channel * (1 - alpha));
    };
    const luminance = (color) => color.slice(0, 3).map((c) => c / 255)
        .map((c) => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4)
        .reduce((sum, c, i) => sum + c * [.2126, .7152, .0722][i], 0);
    const contrast = (text, background) => {
        const a = luminance(composite(text, background));
        const b = luminance(background);
        return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
    };
    const inspect = (selector, pseudo) => {
        const element = document.querySelector(selector);
        const style = getComputedStyle(element, pseudo);
        const text = element.matches('input,textarea') ? style.webkitTextFillColor : style.color;
        const colors = [];
        for (let child = element; child; child = child.parentElement) {
            const childStyle = getComputedStyle(child);
            if (childStyle.backgroundImage.startsWith('linear-gradient')) {
                // The shared gradient's endpoint has the smaller contrast for
                // dark text in Light and light text in Dark, respectively.
                const colorsInGradient = childStyle.backgroundImage.match(/rgba?\([^)]+\)/g);
                if (colorsInGradient) {
                    const values = colorsInGradient.map(rgb);
                    values.sort((a, b) => contrast(rgb(text), a) - contrast(rgb(text), b));
                    colors.push(values[0]);
                    break;
                }
            }
            const color = rgb(childStyle.backgroundColor);
            colors.push(color);
            if ((color[3] ?? 1) === 1) break;
        }
        const background = colors.reverse().reduce((back, front) => composite(front, back), [255, 255, 255]);
        return contrast(rgb(text), background);
    };
    const targets = [
        ['.cw-auth-heading h1'], ['.cw-auth-field label'], ['#login-username'],
        ['#login-password'], ['#register-username'], ['#register-email'],
        ['#register-phone', '::placeholder'], ['.cw-password-toggle'],
        ['.cw-auth-submit'], ['.cine-notice'], ['.cw-review-summary strong'],
        ['.cw-review-metrics dt'], ['.cw-review-metrics dd'], ['.cw-review-copy'],
        ['.cw-hype-choice'], ['.cw-hype-count'], ['.cw-stars input:checked+span'],
        ['.cw-review-comment textarea', '::placeholder'], ['.cw-review-error'],
        ['.cw-review-badge'], ['.cw-review-link'], ['.cm-mood-option input:checked+span'],
    ];
    return Object.fromEntries(targets.filter(([selector]) => document.querySelector(selector))
        .map(([selector, pseudo]) => [selector + (pseudo || ''), inspect(selector, pseudo)]));
}

async function verify(browser, info) {
    const base = 'http://127.0.0.1:' + info.port;
    const evaluate = (expression) => browser.evaluate(expression);
    const fixture = {
        login: '/login', register: '/register', recovery: '/forgot-password', reset: '/reset-password',
        home: '/?category=upcoming', 'home-hype': '/?category=upcoming#movies',
        movie: '/movie/' + info.movie, theatres: '/theatres', 'cine-match': '/cine-match',
        theatre: '/theatres/' + info.theater,
        reviews: '/theatres/' + info.theater + '/screens/' + info.screen + '/reviews',
        empty: '/theatres/' + info.theater + '/screens/' + info.screenWithoutReviews + '/reviews',
        form: '/booking/' + info.references[1] + '/screen-review', admin: '/admin/screen-reviews',
        ticket: '/ticket/' + info.references[1], seats: '/book/' + info.show,
        checkout: '/checkout/QA-CHECKOUT',
        'movie-reviews': '/movies/' + info.reviewMovie + '/reviews',
        'imported-movie': '/movie/' + info.importedMovie,
        'trailer-movie': '/movie/' + info.trailerMovie,
        'admin-movies': '/admin?source=tmdb&schedule=unscheduled#movies',
        dashboard: '/dashboard#pending-reviews',
    };
    const cast = (reference) => '/booking/' + reference + '/screen-review';
    const go = async (url, ready) => {
        try {
            await browser.call('Page.navigate', { url: base + url });
        } catch (error) {
            if (!error.message.includes('CDP timeout')) throw error;
            await browser.call('Page.navigate', { url: base + url });
        }
        await until(() => evaluate(`location.pathname === ${JSON.stringify(url.split(/[?#]/)[0])} &&
            document.readyState === 'complete' && !!document.querySelector(${JSON.stringify(ready)})`),
        'Page did not render: ' + url, 50000);
    };
    const setTheme = async (mode) => {
        await evaluate(`document.querySelector('[data-theme-choice="${mode}"]').click()`);
        assert.equal(await evaluate('document.documentElement.dataset.theme'), mode);
        await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
    };
    const heights = { 360: 800, 390: 844, 768: 1024, 1366: 768, 1920: 1080 };
    const setViewport = (width) => browser.call('Emulation.setDeviceMetricsOverride', {
        width, height: heights[width] || (width < 768 ? 900 : 1000), deviceScaleFactor: 1, mobile: width < 768,
    });
    const checkContrast = async () => {
        const ratios = await evaluate(`(${readability})()`);
        for (const [selector, ratio] of Object.entries(ratios)) {
            if (ratio >= 4.5) continue;
            const context = await evaluate(`[location.pathname, innerWidth, document.documentElement.dataset.theme]`);
            assert.fail(`${selector} contrast is ${ratio.toFixed(2)}:1 at ${context.join(' ')}`);
        }
        return ratios;
    };
    const signIn = () => evaluate(`document.querySelector('#login-username').value = 'qa-viewer';
        document.querySelector('#login-password').value = 'ScreenQaPassword!';
        document.querySelector('.cw-auth-form').requestSubmit()`);

    async function verifyScreenProjection() {
        const uploadEdit = '/admin/movie/' + info.uploadMovie + '/edit';
        const uploadBook = '/book/' + info.uploadShow;
        await go(uploadEdit, '#trailer input[type=file]');
        await browser.call('DOM.enable');
        const document = await browser.call('DOM.getDocument');
        const { nodeId } = await browser.call('DOM.querySelector', {
            nodeId: document.root.nodeId, selector: '#trailer input[type=file]',
        });
        await browser.call('DOM.setFileInputFiles', { nodeId, files: [path.join(root, 'artifacts', 'MD-CineWave-Intro.mp4')] });
        await evaluate("document.querySelector('#trailer form').requestSubmit()");
        await until(() => evaluate("!!document.querySelector('#trailer [data-trailer-provider=upload]')"),
            'The admin form did not save the uploaded trailer.');
        const savedTrailer = await evaluate("document.querySelector('#trailer [data-trailer-provider=upload]').href");
        assert(savedTrailer.includes('/movies/' + info.uploadMovie + '/trailer-file/'));
        assert(!await evaluate("[...document.querySelectorAll('#trailer option')].some(option => /cloudflare/i.test(option.textContent))"));

        const frame = (expression) => evaluate(`document.querySelector('#vr-inline-frame').contentWindow.eval(${JSON.stringify(expression)})`);
        const video = `document.querySelector('#projection-video')`;
        const button = (selector) => frame(`document.querySelector('[data-projection-${selector}]').click()`);
        const videoFrame = () => frame(`(() => {
            const video = ${video};
            const pixels = sCtx.getImageData(300, 150, 140, 110).data;
            let digest = 0;
            for (let p = 0; p < pixels.length; p += 12) digest = (digest * 31 + pixels[p]) | 0;
            return { time: video.currentTime, digest, playing: !video.paused, light: screenLightCenter.color.getHex() };
        })()`);

        for (const width of [1366, 390]) {
            await setViewport(width);
            await browser.call('Emulation.setTouchEmulationEnabled', { enabled: width < 768 });
            await go(uploadBook, '#open-seat-trailer');
            assert.equal(await evaluate("document.querySelector('#vr-inline-frame').getAttribute('src')"), null);
            if (width === 1366) {
                await evaluate("document.querySelector('#open-seat-trailer').click()");
            } else {
                await evaluate("document.querySelector('#btn-view-3d').click(); document.querySelector('#vr-inline-frame').scrollIntoView({block:'center'})");
            }
            await until(() => evaluate(`(() => {
                const doc = document.querySelector('#vr-inline-frame').contentDocument;
                return doc?.body?.classList.contains('preview-ready') && !!doc.querySelector('#projection-video');
            })()`), 'The booking preview did not render.', 45000);
            assert.deepEqual(await frame("[...document.querySelector('#screen-content-select').options].map(option => option.textContent)"), ['Now Playing']);
            assert(await frame("document.querySelector('#screen-content-select').getBoundingClientRect().height > 0"));
            assert.equal(await frame("document.querySelector('#active-movie-title').textContent"), 'Harbour Lights');
            await until(() => frame(`${video}.currentTime > 0.3 && projectionTrailer.hasFrame()`),
                'The uploaded trailer never started on the cinema screen.', 45000);
            assert.equal(await frame(`${video}.currentSrc`), savedTrailer);
            assert(await frame(`${video}.muted && ${video}.loop && ${video}.playsInline &&
                ${video}.crossOrigin === 'anonymous' && getComputedStyle(${video}).display === 'none'`));
            assert.equal(await frame("document.querySelector('#trailer-modal')"), null);
            const first = await videoFrame();
            await until(async () => {
                const next = await videoFrame();
                return next.playing && next.time > first.time + .25 && next.digest !== first.digest && next.light !== first.light;
            }, 'The texture pixels and screen lighting did not change with the video.');
            assert(await frame(`(() => {
                window.qaProjectionMesh = auditoriumGroup.children.find(object => object.material?.map === screenTexture);
                return !!window.qaProjectionMesh && screenTexture.isCanvasTexture &&
                    !!renderer.properties.get(screenTexture).__webglTexture;
            })()`));
            assert(await frame(`(() => {
                const draw = sCtx.drawImage.bind(sCtx);
                return new Promise(resolve => {
                    sCtx.drawImage = (source, x, y, width, height) => {
                        sCtx.drawImage = draw;
                        resolve(Math.abs(width / screenCanvas.width / (height / screenCanvas.height) * screenSurfaceAspect -
                            source.videoWidth / source.videoHeight) < .001);
                        draw(source, x, y, width, height);
                    };
                });
            })()`));
            await frame("setCameraPreset('left'); zoomCamera(1.1)");
            await evaluate("document.querySelector('.seat-btn.seat-avail[data-seat]').click()");
            const activeSeat = await evaluate("document.querySelector('.seat-btn.seat-sel[data-seat]').dataset.seat");
            await until(() => frame(`selectedSeats.has(${JSON.stringify(activeSeat)}) &&
                qaProjectionMesh.parent === auditoriumGroup && qaProjectionMesh.material.map === screenTexture && !${video}.paused`),
            'Changing seats did not preserve the same screen and playback.');
            await frame("setCameraPreset('screen')");
            await pause(400);
            const { data } = await browser.call('Page.captureScreenshot', { format: 'png', fromSurface: true });
            await fs.writeFile(path.join(output, `${width}-cinema-trailer.png`), Buffer.from(data, 'base64'));

            await button('play');
            assert(await frame(`${video}.paused`));
            await button('sound');
            assert.equal(await frame(`${video}.muted`), false);
            await button('sound');
            await button('restart');
            assert(await frame(`${video}.currentTime < 0.5`));
            await until(() => frame(`!${video}.paused && ${video}.currentTime > 0.1`), 'Restart did not resume playback.');
            if (width === 390) {
                await evaluate(`(() => {
                    const spacer = document.createElement('div');
                    spacer.style.height = innerHeight + 'px';
                    document.body.append(spacer);
                    scrollTo(0, document.scrollingElement.scrollHeight);
                })()`);
                await until(() => frame(`${video}.paused`), 'Scrolling the preview out of view did not pause the trailer.');
                await evaluate("document.querySelector('#vr-inline-frame').scrollIntoView({block:'center'})");
                await until(() => frame('!previewPausedByParent'), 'The preview did not become active again.');
                await button('play');
            }
            await evaluate("document.querySelector('#btn-view-2d').click()");
            await until(() => frame(`${video}.paused && previewPausedByParent && !${video}.hasAttribute('src')`),
                'Switching to 2D did not release the trailer.');
            assert(await evaluate(`document.querySelector('.seat-btn[data-seat="${activeSeat}"]').classList.contains('seat-sel')`));
            await frame("dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }))");
            assert.equal(await frame(`${video}.hasAttribute('src')`), false);
            console.log(`Uploaded video, mesh texture, lighting, camera, seat selection and cleanup verified at ${width}px.`);
        }

        const { identifier } = await browser.call('Page.addScriptToEvaluateOnNewDocument', {
            source: `window.qaOriginalPlay = HTMLMediaElement.prototype.play;
                HTMLMediaElement.prototype.play = () => Promise.reject(new DOMException('Test autoplay restriction', 'NotAllowedError'));`,
        });
        await go(`${uploadBook}/vr-preview`, '#projection-video');
        await browser.call('Page.removeScriptToEvaluateOnNewDocument', { identifier });
        await until(() => evaluate("document.querySelector('[data-projection-status]').textContent.includes('Press Play')"),
            'An autoplay restriction did not expose a Play prompt.');
        await evaluate(`HTMLMediaElement.prototype.play = window.qaOriginalPlay;
            document.querySelector('[data-projection-play]').click()`);
        await until(() => evaluate(`${video}.currentTime > 0.3`), 'The Play control did not recover from autoplay rejection.');
        await evaluate(`${video}.src = '/cinewave-qa-missing-trailer.mp4';
            ${video}.play().catch(() => {})`);
        await until(() => evaluate("!document.querySelector('[data-projection-external]').hidden"),
            'A failed media load did not show the external fallback.');
        console.log('Blocked autoplay and a failed network load showed actionable controls.');

        await go(`${fixture.seats}/vr-preview`, '#projection-video');
        assert.equal(await evaluate("document.querySelector('#active-movie-title').textContent"), 'A Night by the Coast');
        assert.notEqual(await evaluate(`${video}.dataset.src`), savedTrailer);
        await until(() => evaluate(`${video}.currentTime > 0.3 && projectionTrailer.hasFrame()`),
            'The existing hosted trailer did not project after switching venues.', 45000);
        await go(`/book/${info.demoShow}/vr-preview`, '#projection-toolbar');
        assert.equal(await evaluate(video), null);
        assert(await evaluate("document.querySelector('#projection-toolbar').textContent.includes('No trailer is available')"));
        await go(`/book/0/vr-preview?admin_screen=${info.screen}&embed=1`, '#projection-toolbar');
        assert(await evaluate("document.querySelector('#projection-toolbar').textContent.includes('No screening selected')"));
        console.log('Changing the theatre and screen updated the movie, hosted trailer and missing-media states.');

        await go(`/book/${info.youtubeShow}/vr-preview`, '#projection-toolbar');
        assert.equal(await evaluate("document.querySelector('#projection-video')"), null);
        await evaluate("document.querySelector('#projection-toolbar [data-trailer-provider=youtube]').click()");
        assert(await evaluate("document.querySelector('#trailer-modal iframe').src.startsWith('https://www.youtube-nocookie.com/embed/')"));
        await evaluate("document.querySelector('#trailer-modal').close()");
        await until(() => evaluate("!document.querySelector('#trailer-modal iframe')"), 'The YouTube fallback did not unload.');
        assert.deepEqual(browser.errors.map(error => error.exception?.description || error.text), [],
            'The upload and preview flow raised an uncaught JavaScript error.');
        console.log('The 3D preview opens the standard YouTube fallback for YouTube-only movies.');
    }

    if (projectionOnly) {
        await setViewport(1366);
        await go(fixture.login, '#login-username');
        await signIn();
        await until(() => evaluate("!!document.querySelector('.cw-movie-grid')"), 'The browser login failed.');
        await until(() => evaluate("!!document.querySelector('[data-post-show-dialog][open]')"), 'Review prompt did not open.');
        await evaluate("document.querySelector('[data-close-review]').click()");
        await verifyScreenProjection();
        return;
    }

    await setViewport(390);
    await go(fixture.login, '#login-username');
    const clickLink = (url) => evaluate(`document.querySelector(${JSON.stringify('a[href=' + JSON.stringify(url) + ']')}).click()`);
    await clickLink(fixture.theatres);
    await until(() => evaluate("!!document.querySelector('.td-venue-card')"), 'Guest theatre listing did not open.');
    assert(await evaluate("document.querySelector('.td-explore-link').textContent.includes('Be the first to review')"));
    await clickLink(fixture.theatre + '#theatre-reviews');
    await until(() => evaluate("!!document.querySelector('#theatre-screens')"), 'Guest theatre detail did not open.');
    await clickLink(fixture.reviews);
    await until(() => evaluate("!!document.querySelector('.cw-review-overview')"), 'Guest screen reviews did not open.');
    assert(await evaluate("document.body.textContent.includes('Watched a movie here?')"));
    console.log('Guest navigation verified from sign-in through theatres, screens, and reviews.');
    await go(fixture.login, '#login-username');
    await browser.call('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'dark' }] });
    await setTheme('system');
    await until(() => evaluate("document.body.classList.contains('dark-mode')"), 'System Default did not respond to Dark.');
    await checkContrast();
    await browser.call('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'light' }] });
    await until(() => evaluate("document.body.classList.contains('light-mode')"), 'System Default did not respond to Light.');
    await setTheme('dark');
    await go(fixture.register, '#register-email');
    assert.equal(await evaluate('document.documentElement.dataset.theme'), 'dark');
    await evaluate(`document.querySelector('#register-username').value = 'qa-viewer';
                  document.querySelector('#register-email').value = 'qa@example.invalid';
                  document.querySelector('#register-password').value = 'VisibleTestPassword';
                  document.querySelector('[data-password-toggle]').click()`);
    assert.equal(await evaluate("document.querySelector('#register-password').type"), 'text');
    assert.equal(await evaluate("document.querySelector('#register-password').value"), 'VisibleTestPassword');
    assert.equal(await evaluate("document.querySelector('#register-username').validity.patternMismatch"), false);
    await checkContrast();
    await evaluate("document.querySelector('#register-email').disabled = true");
    assert.equal(await evaluate("getComputedStyle(document.querySelector('#register-email')).opacity"), '1');
    await checkContrast();
    assert(await evaluate(`[...document.styleSheets].filter(sheet => sheet.href?.endsWith('/coastal.css'))
        .some(sheet => [...sheet.cssRules].some(rule => rule.selectorText?.includes(':-webkit-autofill') &&
            rule.style.getPropertyValue('-webkit-text-fill-color') && rule.style.boxShadow.includes('inset')))`));
    await go(fixture.recovery, '#recovery-email');
    await go(fixture.reset, '#new-password');
    assert.equal(await evaluate("document.querySelector('#new-password').type"), 'password');
    await evaluate("document.querySelector('[aria-controls=new-password]').click()");
    assert.equal(await evaluate("document.querySelector('#new-password').type"), 'text');
    await go(fixture.login, '#login-username');
    await evaluate("document.querySelector('#login-username').focus()");
    assert.equal(await evaluate("getComputedStyle(document.activeElement).outlineWidth"), '3px');
    await evaluate(`document.querySelector('#login-username').value = 'qa-viewer';
                  document.querySelector('#login-password').value = 'incorrect-password';
                  document.querySelector('[data-password-toggle]').click()`);
    assert.equal(await evaluate("document.querySelector('#login-password').type"), 'text');
    assert.equal(await evaluate("document.querySelector('[data-password-toggle]').getAttribute('aria-pressed')"), 'true');
    await checkContrast();
    await evaluate("document.querySelector('[data-password-toggle]').click()");
    assert.equal(await evaluate("document.querySelector('#login-password').type"), 'password');
    await evaluate("document.querySelector('.cw-auth-form').requestSubmit()");
    await until(() => evaluate("document.querySelector('.cine-notice')?.textContent.includes('Invalid username or password')"),
        'The login form did not display its error.');
    await checkContrast();
    await signIn();
    await until(() => evaluate("!!document.querySelector('.cw-movie-grid')"), 'The browser login failed.');
    await until(() => evaluate("!!document.querySelector('[data-post-show-dialog][open]')"), 'Review prompt did not open.');
    await evaluate("document.querySelector('[data-close-review]').click()");
    await go(fixture.dashboard, '#pending-reviews');
    assert(await evaluate("document.querySelector('#pending-reviews').textContent.includes('Rate Theatre')"));
    assert.equal(await evaluate("document.querySelector('[data-post-show-dialog][open]')"), null);
    console.log('Auth fields, theme preference, password toggles and login feedback verified.');

    await go(fixture.movie, '[data-hype-form]');
    const clickHype = (level) => evaluate(`document.querySelector('[value="${level}"]').click()`);
    await clickHype('HYPED');
    await until(() => evaluate(`document.querySelector('[value="HYPED"]').getAttribute('aria-pressed') === 'true'`),
        'Hype vote did not update in the browser.');
    await clickHype('EXTREME_HYPED');
    await until(() => evaluate(`document.querySelector('[value="EXTREME_HYPED"]').getAttribute('aria-pressed') === 'true'`),
        'Hype vote did not switch.');
    assert.deepEqual(await evaluate("[...document.querySelectorAll('[data-vote-count]')].map(node => node.textContent)"),
        ['0', '0', '1']);
    await evaluate(`document.querySelector('[data-hype-form] input[name="csrf_token"]').value = 'invalid'`);
    await clickHype('SUPER_HYPED');
    await until(() => evaluate("document.querySelector('[data-hype-status]').textContent.includes('Could not update')"),
        'Failed vote did not show feedback.');
    assert.equal(await evaluate(`document.querySelector('[value="EXTREME_HYPED"]').getAttribute('aria-pressed')`), 'true');
    console.log('Hype votes and failure feedback verified.');

    assert.equal(await evaluate("document.querySelector('#trailer-modal iframe')"), null);
    await evaluate("document.querySelector('[data-trailer-provider=youtube]').click()");
    assert.match(await evaluate("document.querySelector('#trailer-modal iframe').src"), /youtube-nocookie\.com\/embed/);
    assert.equal(await evaluate("document.querySelector('#trailer-modal [data-trailer-external]').textContent"), 'Watch on YouTube');
    await evaluate("document.querySelector('#trailer-modal').close()");
    await until(() => evaluate("!document.querySelector('#trailer-modal iframe')"), 'YouTube player did not unload.');
    await go(fixture['trailer-movie'], '[data-trailer-provider=cloudinary]');
    await evaluate("document.querySelector('[data-trailer-provider=cloudinary]').click()");
    await until(() => evaluate("document.querySelector('#trailer-modal video')?.readyState >= 1"),
        'Cloudinary video metadata did not load.', 20000);
    await evaluate("(() => { const video = document.querySelector('#trailer-modal video'); video.muted = true; return video.play().then(() => true) })()");
    await until(() => evaluate("document.querySelector('#trailer-modal video').currentTime > 0"),
        'Cloudinary video did not start playback.', 10000);
    await evaluate("document.querySelector('#trailer-modal video').dispatchEvent(new Event('error'))");
    assert(await evaluate("!document.querySelector('[data-trailer-error]').hidden"));
    await evaluate("document.querySelector('#trailer-modal').close()");
    await until(() => evaluate("!document.querySelector('#trailer-modal video')"), 'Cloudinary player did not unload.');
    console.log('Trailer lazy loading, Cloudinary metadata, player cleanup and error fallback verified.');

    await go(fixture['imported-movie'], '.cw-detail-poster');
    assert(await evaluate("document.body.textContent.includes('No screenings scheduled yet.')"));
    assert.equal(await evaluate("document.querySelector('a[href^=\"/book/\"]')"), null);
    assert.equal(await evaluate("document.querySelector('#reviewModal')"), null);
    await go(fixture['admin-movies'], '#movie-sync');
    assert(await evaluate(`document.querySelector('#movies-table').textContent.includes(${JSON.stringify(info.importedTitle)})`));
    assert(await evaluate("document.querySelector('#movie-sync').textContent.includes('Last successful')"));
    await evaluate("document.querySelector('#movie-sync form').requestSubmit()");
    await until(() => evaluate("document.querySelector('#movie-sync')?.textContent.includes('Manual sync queued')"),
        'The admin sync request was not queued.');
    console.log('Imported movie availability, review gating, and the admin sync action verified.');

    await go(fixture.ticket, '.cw-ticket-invitation');
    await go(cast(info.references[0]), '.cw-review-form');
    await evaluate(`document.querySelector('[name="overall_rating"][value="5"]').click();
                  document.querySelector('[name="sound_rating"][value="5"]').click();
                  document.querySelector('[name="ac_rating"][value="3"]').click();
                  document.querySelector('[name="comfort_rating"][value="4"]').click();
                  document.querySelector('[name=review_text]').value = 'Dialogue was clear. Seats had good legroom.';
                  document.querySelector('.cw-review-form').requestSubmit()`);
    await until(() => evaluate("[...document.querySelectorAll('.cine-notice')].some(node => node.textContent.includes('screen review was saved'))"),
        'The browser review submission failed.');
    await go(fixture.reviews, '.cw-review-card');
    assert(await evaluate("document.querySelector('.cw-review-card').textContent.includes('Verified Booking')"));
    await go(fixture.theatre, '#theatre-reviews');
    assert(await evaluate("document.querySelector('#theatre-reviews').textContent.includes('Dialogue was clear')"));
    await go(fixture.empty, '.cw-review-overview');
    assert(await evaluate("document.querySelector('.cw-review-overview').textContent.includes('Not rated yet')"));
    await go(fixture.form, '.cw-review-form');
    await evaluate(`document.querySelector('[name="overall_rating"][value="4"]').focus()`);
    const rightArrow = { key: 'ArrowRight', code: 'ArrowRight', windowsVirtualKeyCode: 39 };
    await browser.call('Input.dispatchKeyEvent', { type: 'keyDown', ...rightArrow });
    await browser.call('Input.dispatchKeyEvent', { type: 'keyUp', ...rightArrow });
    assert.equal(await evaluate('document.querySelector(\'[name="overall_rating"]:checked\').value'), '5');
    await setViewport(1024);
    await go(fixture.admin, '.cw-review-card');
    assert(await evaluate("document.querySelector('.cw-review-card').textContent.includes('Verified Booking')"));
    assert.match(await evaluate("getComputedStyle(document.querySelector('#cw-menu-toggle')).display"), /flex$/);
    await evaluate("document.querySelector('#cw-menu-toggle').click()");
    assert.equal(await evaluate("getComputedStyle(document.querySelector('.cw-admin-nav')).display"), 'flex');
    assert((await evaluate('document.documentElement.scrollWidth')) <= 1025);
    await go(fixture.seats, '#seating-viewport');
    console.log('Review submission, keyboard control, empty screens and admin view verified.');

    await go(fixture['movie-reviews'], '#movie-reviews-title');
    assert(await evaluate("document.body.textContent.includes('Movie reviews become available after you complete your booked screening.')"));
    await go(fixture.theatre, '#theatre-screens');
    await clickLink(fixture.theatre + '/shows/' + info.demoShow + '/book');
    await until(() => evaluate("!!document.querySelector('#booking-form') && document.readyState === 'complete' && typeof toggleSeatSelection === 'function'"),
        'Demo screening seat map did not initialize.');
    await evaluate("document.querySelector('.seat-btn[data-seat=A1]').click()");
    await until(() => evaluate("!document.querySelector('#confirm-btn').disabled"), 'Seat selection did not enable checkout.');
    await evaluate("document.querySelector('#confirm-btn').click()");
    await until(() => evaluate("!!document.querySelector('#confirm-payment')"), 'Demo checkout did not open.');
    const checkoutPath = await evaluate('location.pathname');
    await evaluate("document.querySelector('a[href*=reservation]').click()");
    await until(() => evaluate("document.querySelector('#selected_seats_input')?.value === 'A1'"), 'Held seat was not restored.');
    await evaluate("document.querySelector('#confirm-btn').click()");
    await until(() => evaluate(`location.pathname === ${JSON.stringify(checkoutPath)} && !!document.querySelector('#confirm-payment')`),
        'Seat edit did not return to the existing checkout.');
    await evaluate("document.querySelector('#confirm-payment').click()");
    await until(() => evaluate("!!document.querySelector('[name=outcome][value=success]')"), 'Demo payment did not open.');
    await evaluate("document.querySelector('[name=outcome][value=success]').click()");
    await until(() => evaluate("location.pathname.startsWith('/ticket/') && document.body?.textContent.includes('DEMO TICKET')"),
        'Confirmed demo ticket did not open.');
    const demoTicket = await evaluate('location.pathname');
    assert.equal(await evaluate("document.querySelector('.cw-ticket-invitation')"), null);
    assert.equal(await evaluate(`fetch(${JSON.stringify(fixture['movie-reviews'])}).then(response => response.status)`), 403);
    assert.equal(await evaluate("fetch('/__qa__/end-demo-screening', {method:'POST'}).then(response => response.status)"), 204);
    await go(demoTicket, '#ticket-movie-review');
    const demoReference = demoTicket.split('/').pop();
    fixture['movie-form'] = '/booking/' + demoReference + '/movie-review';
    assert(await evaluate("document.body.textContent.includes('How was your movie experience?')"));
    await clickLink(cast(demoReference));
    await until(() => evaluate("!!document.querySelector('.cw-review-form')"), 'Screen review form did not open.');
    await evaluate(`document.querySelector('[name="overall_rating"][value="3"]').click();
                  document.querySelector('[name="sound_rating"][value="4"]').click();
                  document.querySelector('[name=review_text]').value = 'Demo screening: balanced sound.';
                  document.querySelector('.cw-review-form').requestSubmit()`);
    await until(() => evaluate("document.body?.textContent.includes('Edit Screen Review')"), 'Demo screen review did not publish.');
    await clickLink(fixture.reviews);
    await until(() => evaluate("document.body?.textContent.includes('Demo screening: balanced sound.')"),
        'The screen review was not visible after publication.');
    await go(demoTicket, '#ticket-movie-review');
    await clickLink(fixture['movie-form']);
    await until(() => evaluate("!!document.querySelector('.cw-review-form [name=review]')"), 'Movie review form did not open.');
    await evaluate(`document.querySelector('[name="rating"][value="5"]').click();
                  document.querySelector('[name=title]').value = 'A twist at the bay';
                  document.querySelector('[name=review]').value = 'The boat returned at dawn.';
                  document.querySelector('[name=has_spoiler]').click();
                  document.querySelector('.cw-review-form').requestSubmit()`);
    await until(() => evaluate("!!document.querySelector('.cw-review-card')"), 'Demo movie review did not publish.');
    assert(await evaluate("document.querySelector('.cw-review-card').textContent.includes('Demo Booking Review')"));
    assert.equal(await evaluate("document.querySelector('.cw-review-card').textContent.includes('The boat returned at dawn.')"), false);
    await evaluate("document.querySelector('.cw-review-card a[href*=reveal]').click()");
    await until(() => evaluate("document.querySelector('.cw-review-card')?.textContent.includes('The boat returned at dawn.')"),
        'Spoiler reveal did not display the review body.');
    await go(demoTicket, '#ticket-movie-review');
    assert(await evaluate("document.body.textContent.includes('Edit Movie Review')"));
    await clickLink(fixture['movie-reviews']);
    await until(() => evaluate("!!document.querySelector('.cw-review-movie-heading')"), 'Read Movie Reviews did not open.');
    await clickLink(fixture.theatres);
    await until(() => evaluate("!!document.querySelector('.td-venue-card')"), 'Return to theatres failed.');
    assert(await evaluate("document.querySelector('.td-explore-link').textContent.includes('Read Reviews')"));
    await clickLink(fixture.theatre + '#theatre-reviews');
    await until(() => evaluate("!!document.querySelector('#theatre-screens')"), 'Return to theatre detail failed.');
    await clickLink(fixture.reviews);
    await until(() => evaluate("document.body?.textContent.includes('Demo screening: balanced sound.')"),
        'Published demo screen review was not visible from the theatre directory.');
    console.log('Real browser verified seat selection, demo payment, post-show eligibility, both review forms, spoiler reveal and theatre rediscovery.');

    // Use fixed seeds and freshly rendered pages for all screenshot captures.
    const pages = {
        login: '#login-username', register: '#register-email', home: '.cw-featured-hero',
        'home-hype': '.cw-movie-card[data-category="upcoming"]:not([hidden])', movie: '#movie-hype',
        'imported-movie': '.cw-detail-poster', 'admin-movies': '#movie-sync',
        'cine-match': '.cm-form',
        theatres: '.td-venue-card', theatre: '#theatre-screens', reviews: '.cw-review-card',
        form: '.cw-review-form', admin: '.cw-review-card', ticket: '.cw-ticket-invitation',
        'movie-form': '.cw-review-form', 'movie-reviews': '.cw-review-card',
        seats: '#seating-viewport', checkout: '.cw-order',
    };
    const widths = [360, 390, 430, 768, 1024, 1366, 1920];
    const results = [];
    assert(selectedPages.every((name) => Object.hasOwn(pages, name)), 'Unknown screenshot page.');
    const requested = selectedPages.length ? selectedPages : Object.keys(pages);
    for (const name of requested) {
        const selector = pages[name];
        await go(fixture[name], selector);
        if (name === 'login') {
            await evaluate(`document.querySelector('#login-username').value = 'qa-viewer';
                document.querySelector('#login-password').value = 'Demo only';
                document.querySelector('[data-password-toggle]').click()`);
        }
        for (const width of widths) {
            await setViewport(width);
            for (const mode of ['light', 'dark']) {
                await setTheme(mode);
                if (['home-hype', 'movie', 'checkout'].includes(name)) {
                    await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'start'})`);
                } else {
                    await evaluate('scrollTo(0, 0)');
                }
                const overflow = (await evaluate('document.documentElement.scrollWidth')) - width;
                if (overflow > 1) {
                    const elements = await evaluate(`[...document.body.querySelectorAll('*')]
                        .filter(node => node.getBoundingClientRect().right > ${width} + 1 &&
                            !node.closest('#seating-viewport'))
                        .slice(0, 8).map(node => [node.tagName, node.id, String(node.className)])`);
                    assert.fail(`${name} overflows ${width}px in ${mode} by ${overflow}px. ${JSON.stringify(elements)}`);
                }
                const ratios = await checkContrast();
                const key = `${width}-${mode}-${name}`;
                const options = { format: 'png', fromSurface: true };
                if (name === 'form') {
                    const height = await evaluate("Math.ceil(document.querySelector('.cw-review-form-page').getBoundingClientRect().bottom + 24)");
                    options.captureBeyondViewport = true;
                    options.clip = { x: 0, y: 0, width, height, scale: 1 };
                }
                const { data } = await browser.call('Page.captureScreenshot', options);
                await fs.writeFile(path.join(output, key + '.png'), Buffer.from(data, 'base64'));
                results.push({ width, theme: mode, page: name, contrast: ratios });
            }
        }
        console.log(`${name} verified in Light and Dark at all seven widths.`);
    }
    const assetStatus = await evaluate(`({
      tailwind: typeof window.tailwind === 'object',
      fontAwesome: getComputedStyle(document.querySelector('.cw-logo i'), '::before').content
    })`);
    assert(assetStatus.tailwind, 'Tailwind did not load.');
    assert.notEqual(assetStatus.fontAwesome, 'none', 'Font Awesome did not load.');
    const resultsFile = selectedPages.length ? 'results-' + requested.join('-') + '.json' : 'results.json';
    await fs.writeFile(path.join(output, resultsFile), JSON.stringify({ results, assetStatus }, null, 2));
    console.log(`Captured ${results.length} screenshots in ${output}`);
    console.log('External asset check:', assetStatus);

    await setViewport(1366);
    await go(fixture.seats + '/vr-preview', '#canvas-container');
    await until(() => evaluate("!!document.querySelector('body.preview-ready #canvas-container canvas')"),
        'The 3D auditorium did not render its first frame.', 45000);
    const preview = await browser.call('Page.captureScreenshot', { format: 'png', fromSurface: true });
    await fs.writeFile(path.join(output, '1366-3d-preview.png'), Buffer.from(preview.data, 'base64'));
    console.log('3D auditorium first frame verified.');
    await verifyScreenProjection();
}

async function main() {
    await fs.mkdir(output, { recursive: true });
    const scratchRoot = await fs.realpath(os.tmpdir());
    const scratch = await fs.realpath(await fs.mkdtemp(path.join(scratchRoot, 'cinewave-browser-')));
    assert.equal(path.dirname(scratch), scratchRoot);
    const profile = path.join(scratch, 'chrome');
    const server = spawn(python, ['-m', 'tools.cinewave_experience_qa', scratch],
        { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let log = '';
    server.stderr.on('data', (chunk) => { log = (log + chunk).slice(-8000); });
    let chromeProcess;
    let chromeLog = '';
    let socket;
    try {
        const info = await startupLine(server);
        chromeProcess = spawn(chrome, ['--headless=new', '--no-first-run', '--disable-extensions', '--disable-breakpad',
            '--disable-background-networking', '--disable-sync', '--remote-debugging-port=0',
            '--user-data-dir=' + profile, 'about:blank'],
        { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
        chromeProcess.stderr.on('data', (chunk) => { chromeLog = (chromeLog + chunk).slice(-8000); });
        const portFile = await until(() => {
            if (chromeProcess.exitCode !== null) throw new Error('Chrome exited with code ' + chromeProcess.exitCode);
            return fs.readFile(path.join(profile, 'DevToolsActivePort'), 'utf8').catch(() => null);
        }, 'Chrome DevTools did not start.', 45000);
        const port = portFile.split(/\r?\n/)[0];
        const base = 'http://127.0.0.1:' + port;
        const target = (await (await fetch(base + '/json/list')).json()).find((tab) => tab.type === 'page');
        socket = new WebSocket(target.webSocketDebuggerUrl);
        await new Promise((resolve, reject) => {
            socket.addEventListener('open', resolve, { once: true });
            socket.addEventListener('error', reject, { once: true });
        });
        const browser = new ChromeQA(socket);
        await browser.call('Page.enable');
        await browser.call('Runtime.enable');
        await verify(browser, info);
    } catch (error) {
        console.error(log);
        console.error(chromeLog);
        throw error;
    } finally {
        socket?.close();
        chromeProcess?.kill();
        server.kill();
        await fs.rm(scratch, { recursive: true, force: true, maxRetries: 8, retryDelay: 200 });
    }
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
