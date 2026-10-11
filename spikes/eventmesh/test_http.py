#!/usr/bin/env python3
"""Spike EventMesh: publish/subscribe CloudEvents por HTTP (solo stdlib). Uso: python3 -I test_http.py [pub_base] [sub_base]
Publica en instancia A (10105) y consume en instancia B (20105) para probar el 'mesh' sobre Kafka compartido."""
import json, sys, time, uuid, urllib.request

PUB = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:10105"
SUB = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:20105"
ADMIN = "http://localhost:20106"

def call(method, url, body=None, headers=None):
    h = {"Content-Type": "application/json"}; h.update(headers or {})
    req = urllib.request.Request(url, method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

topic = "voltera.orders." + uuid.uuid4().hex[:6]
print("subscribe:", call("POST", f"{SUB}/events/subscribe", {"clientId": "py-consumer", "topic": topic, "mode": "LOAD_BALANCE"}))
time.sleep(1)
ids = []
for i in range(3):
    ev = {"specversion": "1.0", "id": str(uuid.uuid4()), "source": "/voltera/py-producer",
          "type": "com.voltera.order.created", "datacontenttype": "application/json",
          "data": {"orderId": i, "amount": 10.5 * i}}
    ids.append(ev["id"])
    print("publish:", call("POST", f"{PUB}/events/publish?topic={topic}", ev, {"Content-Type": "application/cloudevents+json"}))
got = []
deadline = time.time() + 30
while len(got) < 3 and time.time() < deadline:
    s, b = call("GET", f"{SUB}/events/poll?clientId=py-consumer&max=10&timeoutMs=5000")
    for d in json.loads(b) if s == 200 and b.strip().startswith("[") else []:
        got.append(d["event"]["id"]); print("recv:", d["event"]["type"], d["event"]["data"])
        print("ack:", call("POST", f"{SUB}/events/ack", {"deliveryId": d["deliveryId"]}))
print("RESULT http:", "OK" if set(got) == set(ids) else f"FAIL got={got}")
print("admin subs:", call("GET", f"{ADMIN}/admin/subscriptions?topic={topic}", headers={"Authorization": "Bearer spike-token"}))
print("topic:", topic)
