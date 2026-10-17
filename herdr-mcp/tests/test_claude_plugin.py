#!/usr/bin/env python3
"""Claude plugin build test in a temp HOME. Installs the package, builds the zip,
then starts the server exactly as .mcp.json says and lists its tools over stdio.
Never touches Claude Desktop, a real Herdr server or the network.
"""
import json
import pathlib
import subprocess
import tempfile
import unittest
import zipfile

SRC = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ['herdr_cli', 'herdr_get', 'herdr_list', 'herdr_read', 'herdr_request', 'herdr_snapshot', 'herdr_status']


class ClaudePluginBuild(unittest.TestCase):
    def test_build_and_start_from_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp) / 'home'
            home.mkdir()
            env = {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'TMPDIR': tmp}
            out = pathlib.Path(tmp) / 'plugin.zip'
            build = SRC / 'build-claude-plugin.sh'
            missing = subprocess.run(['/bin/sh', str(build), str(out)], env=env, capture_output=True, text=True)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn('run install.sh first', missing.stderr + missing.stdout)
            subprocess.run(['/bin/sh', str(SRC / 'install.sh')], env=env, check=True, capture_output=True)
            subprocess.run(['/bin/sh', str(build), str(out)], env=env, check=True, capture_output=True)
            with zipfile.ZipFile(out) as z:
                self.assertEqual(sorted(z.namelist()), ['.claude-plugin/', '.claude-plugin/plugin.json', '.mcp.json'])
                self.assertEqual(json.loads(z.read('.claude-plugin/plugin.json'))['name'], 'herdr-control')
                server = json.loads(z.read('.mcp.json'))['mcpServers']['herdr']
            wrapper = home / '.local/share/herdr-mcp/herdr_control_mcp_child.sh'
            self.assertEqual(server, {'command': '/bin/sh', 'args': [str(wrapper)]})
            msgs = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}]
            run = subprocess.run([server['command'], *server['args']], env=env, capture_output=True, text=True, timeout=30,
                                 input=''.join(json.dumps(m) + '\n' for m in msgs))
            replies = [json.loads(line) for line in run.stdout.splitlines()]
            self.assertEqual(replies[0]['result']['serverInfo']['name'], 'herdr-control')
            self.assertEqual(sorted(t['name'] for t in replies[1]['result']['tools']), TOOLS)


if __name__ == '__main__':
    unittest.main()
