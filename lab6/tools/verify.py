"""Проверки реального HTTP API и WebSocket, сохранение запросов и ответов."""
import argparse, asyncio, json, subprocess, time
from pathlib import Path
import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
Q = ROOT / 'queries'
RESULTS = ROOT / 'results'
RESULTS.mkdir(exist_ok=True)
BASE = 'http://localhost:8000'

def query(name): return (Q/f'{name}.graphql').read_text(encoding='utf-8')
def save(name, obj):
    (RESULTS/f'{name}.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
async def request(client, name, variables=None, label=None, error=None, raw=None):
    payload = {'query':raw or query(name),'variables':variables or {}}
    response = await client.post(BASE+'/graphql',json=payload)
    response.raise_for_status()
    result = response.json()
    record = {'request':payload,'response':result,'http_status':response.status_code,'sql_count':int(response.headers.get('X-SQL-Count','-1'))}
    save(label or name,record)
    if error: assert result['errors'][0]['extensions']['code'] == error, record
    else: assert not result.get('errors'), record
    print(label or name, 'OK', 'SQL:',record['sql_count'])
    return result.get('data'),record['sql_count']

def compose(*args, env=None):
    import os
    subprocess.run(['docker','compose',*args],cwd=ROOT,check=True,env={**os.environ,**(env or {})})

def configure(mode):
    compose('up','-d','--wait','--force-recreate','api',env={'USE_DATALOADER':str(mode)})

async def compare():
    results = {}
    for mode in (0,1):
        await asyncio.to_thread(configure,mode)
        async with httpx.AsyncClient(timeout=60) as c:
            for status in ('CANCELLED','READY',None):
                key = status or 'ALL'
                data,count = await request(c,'A',{'status':status} if status else {},f'A_{key}_{mode}')
                orders = data['orders']; expected_n = 20 if status else 100
                assert len(orders)==expected_n
                expected = 4 if mode else 1+2*len(orders)+sum(len(o['items']) for o in orders)
                assert count == expected, (key, mode, count, expected)
                if mode: assert results[key]['data'] == orders
                else: results[key]={'orders':len(orders),'without':count,'data':orders}
                if mode: results[key]['with']=count
    for value in results.values(): value.pop('data')
    save('sql_comparison',results)
    print(json.dumps(results,indent=2))

async def checks():
    variables = json.loads((Q/'variables.json').read_text(encoding='utf-8'))
    async with httpx.AsyncClient(timeout=60) as c:
        data,_ = await request(c,'restaurants'); assert len(data['restaurants'])==5 and all(len(r['dishes'])==10 for r in data['restaurants'])
        data,_ = await request(c,'order',{'id':'1'}); assert data['order']['total']=='850.00' and len(data['order']['restaurant']['dishes'])==10
        data,_ = await request(c,'accepted'); assert len(data['orders'])==20
        data,_ = await request(c,'create',variables,'create_main'); oid=data['createOrder']['id']; assert data['createOrder']['status']=='CREATED' and data['createOrder']['total']=='800.00'
        for name,field,status in [('accept','acceptOrder','ACCEPTED'),('ready','markOrderReady','READY'),('deliver','markOrderDelivered','DELIVERED')]:
            data,_ = await request(c,name,{'id':oid},name+'_main'); assert data[field]['status']==status
        bad=json.loads(json.dumps(variables)); bad['input']['items'][0]['dishId']='11'
        await request(c,'create',bad,'foreign_dish',error='VALIDATION_ERROR')
        await request(c,'accept',{'id':'5'},'invalid_transition',error='TRANSITION_NOT_ALLOWED')
        data,_=await request(c,'',{'id':'5'},'unchanged',raw='query ($id: ID!) { order(id:$id) { id status cancelReason } }'); assert data['order']['status']=='CANCELLED'
        await request(c,'accept',{'id':'999999'},'missing',error='NOT_FOUND')
        data,_=await request(c,'',{'id':'999999'},'missing_query',raw='query ($id: ID!) { order(id:$id) { id } }'); assert data['order'] is None
        data,_=await request(c,'create',variables,'create_cancel'); cid=data['createOrder']['id']
        data,_=await request(c,'cancel',{'id':cid,'reason':'Изменились планы'},'cancel_valid'); assert data['cancelOrder']['status']=='CANCELLED'
        data,_=await request(c,'create',variables,'create_subscription'); sid=data['createOrder']['id']
        messages=[]
        async with websockets.connect(BASE.replace('http','ws',1)+'/graphql',subprotocols=['graphql-transport-ws']) as ws:
            async def receive(): return json.loads(await asyncio.wait_for(ws.recv(),timeout=10))
            await ws.send(json.dumps({'type':'connection_init'})); assert (await receive())['type']=='connection_ack'
            await ws.send(json.dumps({'id':'1','type':'subscribe','payload':{'query':query('subscribe'),'variables':{'id':sid}}}))
            async def next_status(status):
                msg=await receive(); messages.append(msg); assert msg['type']=='next' and msg['payload']['data']['orderStatusChanged']['status']==status,msg
            await next_status('CREATED')
            for name,status in [('accept','ACCEPTED'),('ready','READY'),('deliver','DELIVERED')]:
                await request(c,name,{'id':sid},name+'_subscription'); await next_status(status)
            msg=await receive(); messages.append(msg); assert msg['type']=='complete'
        save('subscription',{'query':query('subscribe'),'variables':{'id':sid},'messages':messages})
        print('WebSocket: CREATED → ACCEPTED → READY → DELIVERED → complete: OK')

async def main():
    global BASE
    parser=argparse.ArgumentParser(); parser.add_argument('--url',default=BASE); parser.add_argument('--compare',action='store_true'); parser.add_argument('--reset',action='store_true'); args=parser.parse_args(); BASE=args.url.rstrip('/')
    if args.reset or args.compare:
        await asyncio.to_thread(compose,'up','-d','--build','--wait')
        await asyncio.to_thread(compose,'run','--rm','api','python','-m','app.seed')
    if args.compare: await compare()
    await checks()
    print('Все интеграционные проверки завершены. JSON: results/')
if __name__=='__main__': asyncio.run(main())
