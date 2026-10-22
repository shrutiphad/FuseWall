"""Exercises the running loopback server. Never calls any external provider."""
import asyncio
import json
import os
import time
import re
import sys
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fusewall import __version__


async def main():
    data_dir = Path(os.environ.get('FUSEWALL_TEST_DATA_DIR', ROOT / '.fusewall'))
    base_url = os.environ.get('FUSEWALL_TEST_URL', 'http://127.0.0.1:8765')
    remote = not base_url.startswith('http://127.0.0.1:')
    assert not remote or (os.environ.get('FUSEWALL_ALLOW_REMOTE_TESTS')=='1' and re.fullmatch(r'https://[^/]+\.vercel\.app',base_url)), 'Use loopback or an explicitly authorized Vercel deployment'
    token = os.environ.get('FUSEWALL_TEST_OWNER_TOKEN') or (data_dir / 'admin-token.txt').read_text().strip()
    checks = {}
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        h = {'X-Fusewall-Request':'dashboard'}
        r = await client.post('/api/login',json={'token':token},headers=h)
        r.raise_for_status()
        checks.update(owner_login=True, version=__version__, target=base_url, scope='Authorized synthetic test traffic; no live provider')
        health=(await client.get('/health/live')).json()
        assert health['version']==__version__, health
        checks['storage']=health.get('storage','sqlite')
        state = (await client.get('/api/state')).json()
        keys = state['keys']
        for name, group, ceiling, calls in [('Demo · Support triage','Customer support',18000,10),('Demo · Research assistant','Research',26000,8),('Demo · Content checks','Operations',10000,6)]:
            key = next((k for k in keys if k['name']==name and k['active']),None)
            if key is None:
                key = (await client.post('/api/keys',json={'name':name,'client':group,'budget_micro':1_000_000,'session_budget_micro':ceiling},headers=h)).json()
            r = await client.post('/api/lab',headers=h,json={'key_id':key['id'],'session_id':'demo-'+str(time.time_ns()),'calls':calls,'parallel':2})
            r.raise_for_status()
            checks[name] = r.json()['summary']
        key = (await client.post('/api/keys',json={'name':'Live HTTP verification','client':'Verification','session_budget_micro':100_000},headers=h)).json()
        wh = {'Authorization':'Bearer '+key['token'],'X-Fusewall-Session':'live-sse'}
        payload={'model':'fusewall/mini','messages':[{'role':'user','content':'Synthetic live stream'}],'max_tokens':20,'stream':True}
        response = await client.post('/v1/chat/completions',json=payload,headers=wh)
        response.raise_for_status()
        assert response.text.endswith('data: [DONE]\n\n')
        checks['live_sse'] = True
        wh['X-Fusewall-Session']='live-disconnect'
        async with client.stream('POST','/v1/chat/completions',json=payload,headers=wh) as stream:
            stream.raise_for_status()
            async for line in stream.aiter_lines():
                if line.startswith('data: '): break
        deadline=time.monotonic()+10
        while True:
            await asyncio.sleep(.1)
            state=(await client.get('/api/state')).json()
            disconnected=next(r for r in state['requests'] if r['external_id']=='live-disconnect')
            if disconnected['status'] in ('settled','canceled') or time.monotonic()>=deadline:break
        assert disconnected['status'] in (('settled','canceled') if remote else ('canceled',)), disconnected
        checks['disconnect_final_status']=disconnected['status']
        assert state['overview']['held_micro']==0, state['overview']
        checks['real_socket_disconnect_accounted'] = True
        integrity = (await client.post('/api/integrity',headers=h)).json()
        assert integrity['ok'], integrity
        checks['accounting_integrity'] = integrity
        before = state['overview']['requests']
        (await client.post('/api/replay',headers=h,json={'budget_micro':10000})).raise_for_status()
        after = (await client.get('/api/state')).json()['overview']['requests']
        assert before==after
        checks['replay_no_new_traffic'] = True
        await client.patch('/api/keys/'+key['id'],headers=h,json={'active':False})
        assert (await client.post('/v1/chat/completions',headers=wh,json={**payload,'stream':False})).status_code==401
        checks['live_revocation'] = True
    out = ROOT/'evidence'
    out.mkdir(exist_ok=True)
    (out/'live-http-results.json').write_text(json.dumps(checks,indent=2),encoding='utf8')
    print(json.dumps(checks,indent=2))


if __name__=='__main__': asyncio.run(main())
