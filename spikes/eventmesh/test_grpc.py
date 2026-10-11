#!/usr/bin/env python3
"""Spike EventMesh: puente gRPC legacy (puerto 10205). No hay SDK Python: stubs generados con grpcio-tools desde
eventmesh-sdks/eventmesh-sdk-rust/proto/*.proto. Uso: <venv>/bin/python -I test_grpc.py <dir_stubs_generados> [host:port]"""
import json, queue, sys, time, uuid
sys.path.insert(0, sys.argv[1])
import grpc
import eventmesh_cloudevents_pb2 as ce
import eventmesh_service_pb2_grpc as svc

target = sys.argv[2] if len(sys.argv) > 2 else "localhost:10205"
ch = grpc.insecure_channel(target)
topic = "voltera.grpc." + uuid.uuid4().hex[:6]

def s(v): return ce.CloudEvent.CloudEventAttributeValue(ce_string=v)
def evt(**attrs):
    e = ce.CloudEvent(id=str(uuid.uuid4()), source="/voltera/py", spec_version="1.0", type="com.voltera.test")
    for k, v in attrs.items(): e.attributes[k].CopyFrom(s(v))
    return e

common = dict(env="dev", idc="local", sys="voltera", pid="1", ip="127.0.0.1", username="u", passwd="p",
              language="PYTHON", protocoltype="eventmeshmessage", protocolversion="1.0", protocoldesc="grpc")
sub = evt(consumergroup="py-grp", **common)
sub.text_data = json.dumps([{"topic": topic, "mode": "CLUSTERING", "type": "ASYNC"}])
outq = queue.Queue(); outq.put(sub)
def gen():
    while True:
        m = outq.get()
        if m is None: return
        yield m
stream = svc.ConsumerServiceStub(ch).subscribeStream(gen())
print("subscribeStream ack:", dict((k, v.ce_string) for k, v in next(stream).attributes.items() if k in ("statuscode", "responsemessage")))

pub = evt(producergroup="py-prod", subject=topic, seqnum="1", uniqueid=str(uuid.uuid4()), ttl="4000", **common)
pub.text_data = json.dumps({"orderId": 42})
r = svc.PublisherServiceStub(ch).publish(pub)
print("publish resp:", dict((k, v.ce_string) for k, v in r.attributes.items() if k in ("statuscode", "responsemessage")))
t0 = time.time(); ok = False
for m in stream:
    print("recv:", m.type, m.text_data, "deliveryid" , m.attributes["emdeliveryid"].ce_string)
    ack = ce.CloudEvent(id=str(uuid.uuid4()), source="/voltera/py", spec_version="1.0", type="ack")
    ack.attributes["emdeliveryid"].CopyFrom(s(m.attributes["emdeliveryid"].ce_string))
    outq.put(ack); ok = True; break
outq.put(None)
print("RESULT grpc:", "OK" if ok else "FAIL")
