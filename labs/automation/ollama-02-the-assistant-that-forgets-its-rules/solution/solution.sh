#!/bin/sh
# Reference solution: a context window the rules fit in and a low temperature, in the Modelfile, the
# model rebuilt from it; the chat backend no longer overrides the context.
set -eu
sed -i 's/^PARAMETER num_ctx .*/PARAMETER num_ctx 4096/; s/^PARAMETER temperature .*/PARAMETER temperature 0.2/' /srv/support-bot/Modelfile
ollama create support-bot -f /srv/support-bot/Modelfile
sed -i 's/"options": {"num_ctx": 512, "num_predict": 120}/"options": {"num_predict": 120}/' /opt/support-chat/ask
