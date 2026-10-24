// Uses an installed Playwright package and local Edge. No package download.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
let activeBrowser;

async function main() {
  const { chromium } = require(process.env.FUSEWALL_PLAYWRIGHT || 'playwright');
  const root = path.resolve(__dirname,'..');
  const out = process.env.FUSEWALL_EVIDENCE_DIR || path.join(root,'evidence');
  const base = process.env.FUSEWALL_TEST_URL || 'http://127.0.0.1:8765';
  const dataDir = process.env.FUSEWALL_TEST_DATA_DIR || path.join(root,'.fusewall');
  assert(base.startsWith('http://127.0.0.1:') || (process.env.FUSEWALL_ALLOW_REMOTE_TESTS==='1' && /^https:\/\/[^/]+\.vercel\.app$/.test(base)),'Use loopback or an explicitly authorized Vercel deployment');
  fs.mkdirSync(out,{recursive:true});
  const browser = await chromium.launch({channel:'msedge',headless:true});
  activeBrowser = browser;
  const page = await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
  if (process.env.FUSEWALL_VERCEL_OIDC_TOKEN && base.startsWith('https://')) {
    const origin = new URL(base).origin;
    await page.route('**/*', route => route.continue(new URL(route.request().url()).origin === origin ? {
      headers: {...route.request().headers(), 'x-vercel-trusted-oidc-idp-token': process.env.FUSEWALL_VERCEL_OIDC_TOKEN}
    } : {}));
  }
  let initialSessionCheck = true;
  await page.route('**/api/state', async route => {
    if (initialSessionCheck && route.request().method() === 'GET') {
      initialSessionCheck = false;
      await new Promise(resolve => setTimeout(resolve, 800));
    }
    await route.fallback();
  });
  const keyName = 'Browser verified key '+Date.now();
  const errors=[];
  page.on('pageerror', e=>errors.push(e.message));
  page.on('console', e=>{if(e.type()==='error' && !e.text().includes('401')) errors.push(e.text());});
  await page.goto(base);
  await page.locator('#owner-token').fill(process.env.FUSEWALL_TEST_OWNER_TOKEN || fs.readFileSync(path.join(dataDir,'admin-token.txt'),'utf8').trim());
  await page.getByRole('button',{name:'Unlock workspace'}).click();
  await page.getByRole('heading',{name:'Your agents. Your limits.'}).waitFor();
  assert(await page.locator('.skip-link').evaluate(el=>el.getBoundingClientRect().bottom<0),'Skip link hidden until focused');
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'dashboard-desktop.png'),fullPage:true});
  await page.getByRole('link',{name:'API keys',exact:true}).click();
  await page.getByRole('button',{name:'Create key',exact:false}).first().click();
  await page.locator('#key-name').fill(keyName);
  await page.locator('#key-client').fill('UI verification');
  await page.locator('#key-session-budget').fill('0.01');
  await page.locator('#key-calls').fill('500');
  await page.locator('#key-form').getByRole('button',{name:'Create key',exact:true}).click();
  await page.getByRole('heading',{name:'Your key is ready.'}).waitFor();
  assert((await page.locator('#new-token').textContent()).startsWith('fw_test_'));
  await page.getByRole('button',{name:'Close dialog'}).click();
  await page.getByRole('link',{name:'Traffic lab',exact:true}).click();
  await page.locator('#lab-key').selectOption({label:keyName});
  await page.locator('#lab-calls').fill('8');
  const beforePreview = await page.evaluate(async()=> (await (await fetch('/api/state')).json()).overview.requests);
  await page.getByRole('button',{name:'Preview one request'}).click();
  await page.getByText('Would allow one request',{exact:true}).waitFor();
  const afterPreview = await page.evaluate(async()=> (await (await fetch('/api/state')).json()).overview.requests);
  assert.equal(beforePreview,afterPreview,'Preview creates no traffic');
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'budget-preview.png'),fullPage:true});
  await page.locator('#lab-output').fill('1024');
  await page.getByRole('button',{name:'Preview one request'}).click();
  await page.getByText('Would block one request',{exact:true}).waitFor();
  assert.equal(await page.evaluate(async()=> (await (await fetch('/api/state')).json()).overview.requests),beforePreview);
  await page.locator('#lab-output').fill('64');
  await page.locator('#lab-form').getByRole('button',{name:'Run workload'}).click();
  await page.getByText('Workload complete. No paid upstream was contacted.').waitFor();
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'traffic-lab.png'),fullPage:true});
  await page.getByRole('link',{name:'Request log',exact:true}).click();
  await page.locator('.receipt-button').first().focus();
  await page.keyboard.press('Enter');
  await page.getByRole('heading',{name:'Decision receipt'}).waitFor();
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'decision-receipt.png'),fullPage:true});
  await page.getByRole('button',{name:'Close dialog'}).click();
  await page.locator('#request-search').fill('No-such-request-unique');
  await page.locator('#request-search').focus();
  await page.waitForTimeout(4500);
  assert.equal(await page.locator('#request-search').inputValue(),'No-such-request-unique','Polling preserves a focused search draft');
  await page.getByRole('button',{name:'Search',exact:true}).click();
  await page.getByRole('heading',{name:'0 matching requests'}).waitFor();
  await page.locator('#request-search').fill(keyName);
  await page.getByRole('button',{name:'Search',exact:true}).click();
  await page.getByRole('heading',{name:'8 matching requests'}).waitFor();
  const seeded = await page.evaluate(async name=>{
    const state=await (await fetch('/api/state')).json();
    const key=state.keys.find(k=>k.name===name);
    for(const calls of [20,20,10]) {
      const response=await fetch('/api/lab',{method:'POST',headers:{'Content-Type':'application/json','X-Fusewall-Request':'dashboard'},body:JSON.stringify({key_id:key.id,session_id:'pagination-'+Date.now(),calls,parallel:2})});
      if(!response.ok) return false;
    }
    return true;
  },keyName);
  assert(seeded,'Seed isolated pagination traffic');
  await page.getByRole('button',{name:'Search',exact:true}).click();
  await page.getByRole('heading',{name:'58 matching requests'}).waitFor();
  assert.equal(await page.locator('tr[data-request]').count(),50);
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await page.getByText('51–58 of 58',{exact:true}).waitFor();
  assert.equal(await page.locator('tr[data-request]').count(),8);
  await page.getByRole('button',{name:'Previous',exact:true}).click();
  await page.getByText('1–50 of 58',{exact:true}).waitFor();
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'request-history.png'),fullPage:true});

  await page.getByRole('link',{name:'Usage insights',exact:true}).click();
  await page.getByRole('heading',{name:'Understand the allowance.'}).waitFor();
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'usage-insights.png'),fullPage:true});
  await page.getByRole('link',{name:'Policy replay',exact:true}).click();
  await page.getByRole('button',{name:'Evaluate policy'}).click();
  await page.getByText('Would allow',{exact:true}).waitFor();
  await page.getByRole('link',{name:'Reliability',exact:true}).click();
  await page.getByRole('button',{name:'Check integrity'}).click();
  await page.getByText('Accounting checks passed.',{exact:false}).waitFor();
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'reliability.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  for(const route of ['overview','insights','keys','sessions','requests','lab','replay','reliability','settings']) {
    await page.goto(base+'/#'+route);
    await page.locator('#shell').waitFor({state:'visible'});
    await page.getByRole('heading',{level:1}).waitFor();
    const overflow = await page.evaluate(()=>document.documentElement.scrollWidth > innerWidth);
    assert(!overflow, 'Page horizontal overflow: '+route);
  }
  await page.getByRole('button',{name:'Toggle navigation'}).click();
  assert.equal(await page.getByRole('button',{name:'Toggle navigation'}).getAttribute('aria-expanded'),'true');
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('button',{name:'Toggle navigation'}).getAttribute('aria-expanded'),'false');
  await page.goto(base+'/#overview');
  await page.locator('#shell').waitFor({state:'visible'});
  await page.locator('#toast').waitFor({state:'hidden'});
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'dashboard-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[],'Browser console/runtime errors');
  const results={version:'0.3.0',target:base,scope:'Authorized synthetic demonstration traffic; no live provider',desktop:'1440×1000',mobile:'390×844',routesChecked:9,ownerLogin:true,delayedSessionBootstrap:true,keyCreation:true,lab:true,previewWithoutTraffic:true,blockedPreview:true,pagination:true,keyboardReceipt:true,search:true,preservesFocusedDraft:true,mobileMenuEscape:true,receipt:true,replay:true,insights:true,integrity:true,horizontalOverflow:false,consoleErrors:errors};
  fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(results,null,2));
  console.log(JSON.stringify(results));
  await browser.close();
}
main().catch(async e=>{console.error(e);await activeBrowser?.close();process.exitCode=1;});
