#!/usr/bin/env python3
"""Spike: enrutado A(topic in) -> B(topic out). EventMesh NO trae reglas de routing declarativas en develop;
el relay se hace en la app (aqui un Python que suscribe en A y republica en B). Solo stdlib."""
import json, time, uuid, urllib.request
def call(m, u, b=None, h=None):
    r = urllib.request.Request(u, method=m, data=json.dumps(b).encode() if b is not None else None,
                               headers={"Content-Type": "application/json", **(h or {})})
    with urllib.request.urlopen(r, timeout=40) as x: return x.status, x.read().decode()
A, B = "http://localhost:10105", "http://localhost:20105"
tin, tout = "route.in." + uuid.uuid4().hex[:5], "route.out." + uuid.uuid4().hex[:5]
call("POST", f"{A}/events/subscribe", {"clientId": "relay", "topic": tin, "mode": "LOAD_BALANCE"})
call("POST", f"{B}/events/subscribe", {"clientId": "sink", "topic": tout, "mode": "LOAD_BALANCE"})
time.sleep(1)
ev = {"specversion": "1.0", "id": str(uuid.uuid4()), "source": "/src", "type": "t.v1", "datacontenttype": "application/json", "data": {"k": 1}}
call("POST", f"{A}/events/publish?topic={tin}", ev, {"Content-Type": "application/cloudevents+json"})
_, b = call("GET", f"{A}/events/poll?clientId=relay&max=5&timeoutMs=8000")
d = json.loads(b)[0]; e = d["event"]; e["source"] = "/relay"; e["id"] = str(uuid.uuid4())
call("POST", f"{B}/events/publish?topic={tout}", e, {"Content-Type": "application/cloudevents+json"}); call("POST", f"{A}/events/ack", {"deliveryId": d["deliveryId"]})
_, b = call("GET", f"{B}/events/poll?clientId=sink&max=5&timeoutMs=8000"); r = json.loads(b)
print("RESULT route:", "OK" if r and r[0]["event"]["source"] == "/relay" else "FAIL", r[:1])
