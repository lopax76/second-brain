// Headless screenshots of the Second Brain viewer + the Graphify graph, using the installed
// Chrome (puppeteer-core, no Chromium download). Serve the folders on localhost:8099 first.
// Run: NODE_PATH=<tmp>/node_modules node docs/assets/_shoot.js
const puppeteer = require('puppeteer-core');
const path = require('path');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const OUT = __dirname;
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: false,  // real GPU: headless software-WebGL renders the canvas black
    args: ['--no-sandbox', '--ignore-gpu-blocklist', '--window-size=1520,880'],
    defaultViewport: { width: 1500, height: 860, deviceScaleFactor: 2 },
  });
  const page = await browser.newPage();

  await page.goto('http://localhost:8099/.secondbrain/view.html', { waitUntil: 'load', timeout: 60000 });
  await sleep(1500);
  await page.evaluate(() => {
    const gb = document.getElementById('groupby');
    if (gb) { gb.value = 'type'; gb.dispatchEvent(new Event('change')); }
    const t = document.getElementById('title'); if (t) t.textContent = 'example suite (backbone)';
  });
  await sleep(10000);
  await page.screenshot({ path: path.join(OUT, 'ui-suite.png') });
  console.log('wrote ui-suite.png');

  await page.goto('http://localhost:8099/MasterAI/graphify-out/graph.html', { waitUntil: 'load', timeout: 60000 });
  await sleep(8000);
  await page.screenshot({ path: path.join(OUT, 'graphify-suite.png') });
  console.log('wrote graphify-suite.png');

  await browser.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
