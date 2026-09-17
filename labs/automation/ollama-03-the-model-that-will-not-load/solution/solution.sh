#!/bin/sh
# Reference solution: a 4096-token context for two parallel requests, under a 1.5 GiB limit; then load
# the model once so the server is ready.
set -eu
cat > /etc/systemd/system/ollama.service.d/tuning.conf <<'CONF'
[Service]
Environment="OLLAMA_CONTEXT_LENGTH=4096"
Environment="OLLAMA_NUM_PARALLEL=2"
MemoryMax=1536M
CONF
systemctl daemon-reload
systemctl restart ollama
for i in $(seq 1 30); do curl -fs http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 1; done
curl -fs http://127.0.0.1:11434/api/generate -d '{"model": "qwen2.5:0.5b", "prompt": "hi", "stream": false, "options": {"num_predict": 1}}' >/dev/null
