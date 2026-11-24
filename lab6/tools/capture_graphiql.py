"""Необязательная автоматизация снимков настоящего GraphiQL.
Запускать после seed, на работающем API с USE_DATALOADER=1.
Требует playwright и установленный Chromium (см. README).
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results'/'screenshots'; OUT.mkdir(parents=True,exist_ok=True)
URL='http://localhost:8000/graphql'

CREATE='''mutation {
  createOrder(input: {restaurantId:"1", customerName:"Анна",
    deliveryAddress:"Новосибирск, ул. Ленина, 10",
    items:[{dishId:"1",quantity:2},{dishId:"2",quantity:1}]}) {
    id status total items { quantity price amount dish { name } }
  }
}'''

def fill(page,text):
    # GraphiQL builds may use either CodeMirror 5 or 6.
    page.locator('.CodeMirror, .cm-content').first.wait_for(timeout=30000)
    cm=page.locator('.CodeMirror').first
    if cm.count():
        cm.evaluate('(el, value) => { el.CodeMirror.setValue(value); el.CodeMirror.focus(); }',text)
    else:
        page.locator('.cm-content').first.click()
        page.keyboard.press('Control+a')
        page.keyboard.insert_text(text)

def start(page,text):
    fill(page,text)
    page.keyboard.press('Control+Enter')

def capture(page,name,text):
    with page.expect_response(lambda r:r.request.method=='POST' and '/graphql' in r.url,timeout=30000) as info:
        start(page,text)
    data=info.value.json()
    page.wait_for_timeout(1000)
    page.screenshot(path=str(OUT/f'{name}.png'))
    (OUT/f'{name}.json').write_text(json.dumps({'query':text,'response':data},ensure_ascii=False,indent=2),encoding='utf-8')
    return data

def mutation(field,oid): return f'mutation {{ {field}(id:"{oid}") {{ id status }} }}'

def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1500,'height':950},device_scale_factor=1)
        page=context.new_page(); page.goto(URL,wait_until='domcontentloaded')
        capture(page,'01_order',(ROOT/'queries/order.graphql').read_text().replace('query FullOrder($id: ID!)','query FullOrder').replace('id: $id','id: "1"'))
        capture(page,'02_accepted',(ROOT/'queries/accepted.graphql').read_text())
        oid=capture(page,'03_create',CREATE)['data']['createOrder']['id']
        for n,field in [('04_accept','acceptOrder'),('05_ready','markOrderReady'),('06_deliver','markOrderDelivered')]:
            capture(page,n,mutation(field,oid))
        capture(page,'07_validation',CREATE.replace('dishId:"1"','dishId:"11"',1))
        capture(page,'08_transition',mutation('acceptOrder','5'))
        capture(page,'09_unchanged','query { order(id:"5") { id status cancelReason } }')
        capture(page,'10_missing',mutation('acceptOrder','999999'))
        sid=capture(page,'11_create_subscription',CREATE)['data']['createOrder']['id']
        watch=context.new_page(); watch.goto(URL,wait_until='domcontentloaded')
        start(watch,f'subscription {{ orderStatusChanged(orderId:"{sid}") {{ id status }} }}')
        watch.wait_for_timeout(2000)
        watch.screenshot(path=str(OUT/'12_subscription_CREATED.png'))
        for n,field,status in [('13','acceptOrder','ACCEPTED'),('14','markOrderReady','READY'),('15','markOrderDelivered','DELIVERED')]:
            capture(page,n+'_mutation',mutation(field,sid))
            watch.wait_for_timeout(1200)
            watch.screenshot(path=str(OUT/f'{n}_subscription_{status}.png'))
        browser.close()
    print('Снимки и JSON сохранены в',OUT)
if __name__=='__main__': main()
