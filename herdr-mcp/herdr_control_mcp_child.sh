#!/bin/sh
# Stdio child for tunnel-client: removes tunnel/OpenAI/cloud credential variables
# from the environment (defense in depth), then runs the sibling bridge.
for v in $(env | sed -n 's/=.*$//p' | grep -E '^(CONTROL_PLANE_|OPENAI_|ANTHROPIC_|AWS_|CLOUDFLARED|TUNNEL_CLIENT_|MCP_|HEALTH_|ALLOW_REMOTE_UI|ADMIN_UI)'); do
  unset "$v"
done
here=$(dirname -- "$0")
exec /usr/bin/python3 -I -B "$here/herdr_control_mcp.py"
