/* No npm dependencies: Chrome DevTools Protocol via Node's built-in WebSocket.
 * Connects only to the dedicated localhost QA Chrome, never a user's profile.
 */
const fs = require('node:fs/promises');
const path = require('node:path');
class ChromeQA {
    constructor(ws) {
        this.ws = ws; this.next = 0; this.pending = new Map(); this.errors = [];
        ws.addEventListener('message', event => {
            const data = JSON.parse(event.data);
            if (data.id) {
                const pending = this.pending.get(data.id);
                if (!pending) return;
                this.pending.delete(data.id);
                data.error ? pending.reject(new Error(JSON.stringify(data.error))) : pending.resolve(data.result);
            }
            if (data.method === 'Runtime.exceptionThrown') this.errors.push(data.params.exceptionDetails);
        });
    }
    call(method, params = {}) {
        const id = ++this.next;
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('CDP timeout: ' + method)); }, 20000);
            this.pending.set(id, {resolve:value=>{clearTimeout(timer);resolve(value);}, reject:error=>{clearTimeout(timer);reject(error);}});
            this.ws.send(JSON.stringify({id, method, params}));
        });
    }
    async evaluate(expression) {
        const result = await this.call('Runtime.evaluate', {expression, awaitPromise:true, returnByValue:true});
        if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
        return result.result.value;
    }
    async screenshot(name) {
        const result = await this.call('Page.captureScreenshot', {format:'png', fromSurface:true});
        await fs.writeFile(path.join(__dirname, '../docs/screenshots/phase-2.1.3-seat-materials', name + '.png'), Buffer.from(result.data, 'base64'));
    }
    static async connect() {
        const tabs = await (await fetch('http://127.0.0.1:9214/json/list')).json();
        for (const tab of tabs.filter(t=>t.type==='page' && t.url.startsWith('http://127.0.0.1:5014/')))
            await fetch('http://127.0.0.1:9214/json/close/' + tab.id);
        const target = await (await fetch('http://127.0.0.1:9214/json/new?http://127.0.0.1:5014/__qa__/', {method:'PUT'})).json();
        const ws = new WebSocket(target.webSocketDebuggerUrl);
        await new Promise((resolve, reject) => { ws.addEventListener('open', resolve, {once:true}); ws.addEventListener('error', reject, {once:true}); });
        const client = new ChromeQA(ws);
        await client.call('Runtime.enable'); await client.call('Page.enable');
        await client.call('Emulation.setDeviceMetricsOverride', {width:1600,height:900,deviceScaleFactor:1,mobile:false});
        await client.call('Page.bringToFront');
        return client;
    }
}
module.exports = ChromeQA;
