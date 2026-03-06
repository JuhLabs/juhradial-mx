#!/usr/bin/env python3
"""Probe Logi Options+ agent to find correct change_host payload format."""
import glob, json, socket, struct, time

DEVICE_ID = "dev00000000"

def find_socket():
    for s in glob.glob("/tmp/logitech_kiros_agent-*"):
        if "updater" not in s:
            return s
    return None

def connect(sock_path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(sock_path)
    s.recv(4)  # start marker
    read_frame(s)  # protobuf subprotocol
    read_frame(s)  # OPTIONS message
    return s

def read_frame(s):
    header = b""
    while len(header) < 4:
        chunk = s.recv(4 - len(header))
        if not chunk: return None
        header += chunk
    frame_len = struct.unpack('>I', header)[0]
    body = b""
    while len(body) < frame_len:
        chunk = s.recv(frame_len - len(body))
        if not chunk: return None
        body += chunk
    return body

def send_json(s, msg):
    json_bytes = json.dumps(msg).encode('utf-8')
    proto_name = b"json"
    total_size = len(proto_name) + len(json_bytes) + 8
    frame = (struct.pack('<I', total_size) +
             struct.pack('>I', len(proto_name)) + proto_name +
             struct.pack('>I', len(json_bytes)) + json_bytes)
    s.sendall(frame)

def recv_json(s, timeout=5):
    s.settimeout(timeout)
    s.recv(4)  # start marker
    proto_len = struct.unpack('>I', s.recv(4))[0]
    proto_name = s.recv(proto_len).decode('ascii')
    msg_len = struct.unpack('>I', s.recv(4))[0]
    msg_data = b""
    while len(msg_data) < msg_len:
        msg_data += s.recv(msg_len - len(msg_data))
    if proto_name == "json":
        return json.loads(msg_data)
    return {"_proto": proto_name, "_raw": msg_data[:200].hex()}

def query(verb, path, payload=None):
    sock_path = find_socket()
    if not sock_path:
        print("ERROR: No Logi agent socket found")
        return None
    s = connect(sock_path)
    msg = {"msgId": f"probe-{time.time()}", "verb": verb, "path": path}
    if payload:
        msg["payload"] = payload
    print(f"\n>>> {verb.upper()} {path}")
    if payload:
        print(f"    payload: {json.dumps(payload, indent=2)}")
    send_json(s, msg)
    resp = recv_json(s)
    print(f"<<< {json.dumps(resp, indent=2)}")
    s.close()
    return resp

# 1. GET current easy_switch hosts
print("=" * 60)
print("1. GET easy_switch hosts")
query("get", f"/devices/{DEVICE_ID}/easy_switch")

# 2. GET change_host status (see the @type and field names)
print("\n" + "=" * 60)
print("2. GET change_host status")
query("get", f"/change_host/{DEVICE_ID}/host")

# 3. Look for change_host routes in /routes
print("\n" + "=" * 60)
print("3. Routes containing 'change_host'")
resp = query("get", "/routes")
if resp and "payload" in resp:
    routes = resp["payload"].get("route", [])
    for r in routes:
        if "change_host" in r.get("path", ""):
            print(f"  ROUTE: {r.get('verb')} {r.get('path')}")
            if r.get("payload"):
                print(f"    payload: {json.dumps(r['payload'], indent=2)}")
            if r.get("exampleJson"):
                print(f"    example: {r['exampleJson']}")

# 4. Try SET with hostIndex (0-based, channel 1 = index 0)
print("\n" + "=" * 60)
print("4. SET change_host with hostIndex=0")
query("set", f"/change_host/{DEVICE_ID}/host", {"hostIndex": 0})

# 5. Try SET with @type annotation
print("\n" + "=" * 60)
print("5. SET change_host with @type")
query("set", f"/change_host/{DEVICE_ID}/host", {
    "@type": "type.googleapis.com/logi.protocol.change_host.ChangeHost",
    "hostIndex": 0
})
