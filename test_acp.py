import json
import subprocess
import time

payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocol_version": 1,
        "client_capabilities": {},
        "client_info": {"name": "test-client", "version": "1.0"}
    }
}

proc = subprocess.Popen(
    ["uv", "run", "python", "-m", "products.agent.acp_server"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

proc.stdin.write(json.dumps(payload) + "\n")
proc.stdin.flush()

time.sleep(1)

out = proc.stdout.readline()
print("Response:", out)
proc.terminate()
