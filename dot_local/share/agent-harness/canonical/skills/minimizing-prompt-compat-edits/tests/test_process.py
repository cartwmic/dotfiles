import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
spec = importlib.util.spec_from_file_location("reduce", SCRIPTS / "reduce.py")
reduce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reduce)
sys.path.insert(0, str(SCRIPTS))
from pi_probe import install_model_config

FAKE_ORACLE = """
import json,pathlib,sys
r=json.load(sys.stdin); p=pathlib.Path(r['prompt']).read_text()
mode=sys.argv[1]
upper={x for x in 'ABCD' if x in p}
v='accept' if upper==set('ABCD') or upper==set('AD') or upper==set('BCD') else 'reject'
if mode=='inconclusive' and upper==set('A'): v='inconclusive'
if mode=='drift': pathlib.Path(sys.argv[2]).write_text('changed')
print(json.dumps({'verdict':v,'messages':1,'promptSha256':r['promptSha256'],'contextDigest':r['contextDigest']}))
"""


class ReducerProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.source = self.root / "source.txt"
        self.source.write_text("a b c d")
        self.oracle = self.root / "oracle.py"
        self.oracle.write_text(FAKE_ORACLE)
        self.frozen = self.root / "frozen.txt"
        self.frozen.write_text("stable")
        self.manifest = {
            "sourceSha256": reduce.digest(self.source.read_bytes()),
            "editableRange": [0, 7], "protectedRanges": [],
            "edits": [{"id": c, "start": i*2, "old": c, "new": c.upper()}
                      for i, c in enumerate("abcd")],
            "context": {"mode": "fixture", "budgetCeiling": 64}, "contextFiles": [str(self.oracle), str(self.frozen)],
        }

    def tearDown(self):
        self.temp.cleanup()

    def run_process(self, mode="normal", budget=64):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.manifest))
        output = self.root / "search"
        run = subprocess.run([sys.executable, str(SCRIPTS / "reduce.py"),
                              str(self.source), str(manifest), str(output),
                              "--budget", str(budget), "--controls-every", "16", "--oracle",
                              sys.executable, str(self.oracle), mode, str(self.frozen)],
                             capture_output=True, text=True, timeout=30)
        return run, json.loads((output / "result.json").read_text()), output

    def test_completed_nonmonotonic_search_and_fresh_confirmations(self):
        run, result, output = self.run_process()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(result["editCount"], 2)
        self.assertEqual([e["id"] for e in result["edits"]], ["a", "d"])
        self.assertEqual((output / "minimal-prompt.txt").read_text(), "A b c D")
        trials = [json.loads(x) for x in (output / "trials.jsonl").read_text().splitlines()]
        self.assertEqual(sum(t["label"] == "winner-confirmation" for t in trials), 2)
        self.assertEqual(sum(t["label"] == "remove-a" for t in trials), 2)
        self.assertEqual(sum(t["label"] == "remove-d" for t in trials), 2)
        self.assertEqual(result["requestsUsed"], len(trials))
        self.assertEqual(result["functionalValidation"], "pending")
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)

    def test_inconclusive_cheaper_candidate_blocks_minimum(self):
        run, result, output = self.run_process("inconclusive")
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse((output / "minimal-prompt.txt").exists())

    def test_context_drift_blocks_result(self):
        run, result, _ = self.run_process("drift")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("context file changed", result["reason"])

    def test_budget_stops_before_next_oracle_call(self):
        run, result, output = self.run_process(budget=4)
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(result["requestsUsed"], 4)
        self.assertEqual(len(list(output.glob("trial-*"))), 4)

    def test_budget_cannot_exceed_approved_ceiling(self):
        run, result, output = self.run_process(budget=65)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("approved manifest ceiling", result["reason"])
        self.assertFalse(list(output.glob("trial-*")))

    def test_protected_text_and_changed_source_rejected(self):
        self.manifest["protectedRanges"] = [[0, 1]]
        with self.assertRaisesRegex(ValueError, "protected"):
            reduce.load_palette(self.source.read_bytes(), self.manifest)
        with self.assertRaisesRegex(ValueError, "digest"):
            reduce.load_palette(b"different", self.manifest)

    def test_unicode_byte_offsets(self):
        source = "é pi".encode()
        manifest = {**self.manifest, "sourceSha256": reduce.digest(source),
                    "editableRange": [0, len(source)],
                    "edits": [{"id": "pi", "start": 3, "old": "pi", "new": "agent"}]}
        edits = reduce.load_palette(source, manifest)
        self.assertEqual(reduce.patch(source, edits).decode(), "é agent")


class ModelConfigTests(unittest.TestCase):
    def test_explicit_approval_and_no_routing_auth_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            source = root / "model.json"
            document = {"providers": {"claude-compat": {"models": [{
                "id": "claude-sonnet-5-5", "api": "claude-compat-messages",
                "baseUrl": "https://api.anthropic.com", "contextWindow": 1000000,
                "maxTokens": 128000, "reasoning": True,
            }]}}}
            source.write_text(json.dumps(document))
            config = {"model": "claude-sonnet-5-5", "modelConfigFile": str(source)}
            with self.assertRaisesRegex(ValueError, "approval"):
                install_model_config(config, root)
            config["modelConfigApproved"] = True
            install_model_config(config, root)
            self.assertEqual(json.loads((root / "models.json").read_text()), document)
            document["providers"]["claude-compat"]["apiKey"] = "fixture-paid-key"
            source.write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                install_model_config(config, root)


class WireGuardTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_exact_envelope_rejects_append_duplicate_and_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            source = root / "prompt.txt"
            source.write_text("Owner instructions.")
            script = root / "check.mjs"
            script.write_text("""
import guard from """ + json.dumps(str(SCRIPTS / "wire_guard.mjs")) + """;
let sent=0;
globalThis.fetch=async()=>{sent++;return new Response('OK');};
guard();
const system=[
 {type:'text',text:'x-anthropic-billing-header: cc_version=2.1.282.abc; cc_entrypoint=cli; cch=abcde;'},
 {type:'text',text:"You are Claude Code, Anthropic's official CLI for Claude."},
 {type:'text',text:'Owner instructions.\\n\\n<cwd>\\n/work\\n</cwd>'}
];
const call=(blocks)=>fetch('https://api.anthropic.com/v1/messages',{
 headers:{authorization:'Bearer sk-ant-oat-fixture'},body:JSON.stringify({model:'fixture',system:blocks,max_tokens:100,metadata:{user_id:JSON.stringify({session_id:'fixture',device_id:'device',account_uuid:'account'})}})
});
for(const blocks of [
 [...system.slice(0,2),{type:'text',text:system[2].text+' injected'}],
 [...system,system[2]]
]){
 try{await call(blocks);throw new Error('unexpected acceptance');}
 catch(e){if(e.message!=='Complete system layout or permitted cwd suffix changed')throw e;}
}
process.env.PROMPT_COMPAT_EXPECTED_MODEL='different-requested-model';
try{await call(system);throw new Error('unexpected model accepted');}
catch(e){if(e.message!=='Probe blocked unexpected model before inference')throw e;}
if(sent!==0)throw new Error('invalid prompt/model reached transport');
console.log('blocked');
""")
            env = {**os.environ, "PROMPT_COMPAT_SOURCE": str(source),
                   "PROMPT_COMPAT_WIRE": str(root / "wire"),
                   "PROMPT_COMPAT_CWD": "/work", "PROMPT_COMPAT_MAX_MESSAGES": "8",
                   "PROMPT_COMPAT_EXPECTED_MODEL": "fixture",
                   "PROMPT_COMPAT_AUTHORIZATION_SHA": reduce.digest(b"Bearer sk-ant-oat-fixture")}
            run = subprocess.run(["node", str(script)], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("blocked", run.stdout)
            # A fresh process allows only one actual transport; a retry is blocked.
            script.write_text(script.read_text().split("for(const blocks")[0] + """
await call(system);
try{await call(system);throw new Error('retry accepted');}
catch(e){if(e.message==='retry accepted')throw e;}
if(sent!==1)throw new Error('retry reached transport');
console.log('one-send');
""")
            env["PROMPT_COMPAT_MAX_MESSAGES"] = "1"
            env["PROMPT_COMPAT_EXPECTED_MODEL"] = "fixture"
            run = subprocess.run(["node", str(script)], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("one-send", run.stdout)


    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_complete_context_digest_catches_drift_and_only_excludes_nuisance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            source = root / "prompt.txt"
            source.write_text("Owner instructions.")
            script = root / "check.mjs"
            script.write_text("""
import {readFileSync} from 'node:fs';
import guard from """ + json.dumps(str(SCRIPTS / "wire_guard.mjs")) + """;
globalThis.fetch=async()=>new Response('OK');
guard();
const base={
 model:'fixture',stream:true,max_tokens:100,temperature:0.1,
 metadata:{user_id:JSON.stringify({session_id:'session1',device_id:'device',account_uuid:'account'})},
 messages:[{role:'user',content:'fixed question'}],
 system:[
  {type:'text',text:'x-anthropic-billing-header: cc_version=2.1.282.abc; cc_entrypoint=cli; cch=abcde;'},
  {type:'text',text:"You are Claude Code, Anthropic's official CLI for Claude."},
  {type:'text',text:'Owner instructions.\\n\\n<cwd>\\n/work\\n</cwd>'}
 ]
};
const headers={'authorization':'Bearer sk-ant-oat-fixture','anthropic-version':'2023-06-01','x-client-request-id':'one','x-claude-code-session-id':'session1'};
async function send(change=()=>{},headerChange=()=>{}){
 const b=structuredClone(base),h={...headers};change(b);headerChange(h);
 await fetch('https://api.anthropic.com/v1/messages',{headers:h,body:JSON.stringify(b)});
}
await send();
await send(b=>b.messages[0].content='changed');
await send(b=>{const u=JSON.parse(b.metadata.user_id);u.account_uuid='other';b.metadata.user_id=JSON.stringify(u);});
await send(b=>{const u=JSON.parse(b.metadata.user_id);u.device_id='other';b.metadata.user_id=JSON.stringify(u);});
await send(b=>b.temperature=0.2);
await send(()=>{},h=>h['anthropic-version']='2099-01-01');
await send(b=>{const u=JSON.parse(b.metadata.user_id);u.session_id='session2';b.metadata.user_id=JSON.stringify(u);},h=>{h['x-client-request-id']='two';h['x-claude-code-session-id']='session2';});
await send(b=>b.system[0].text=b.system[0].text.replace('abcde','12345'));
try{await send(()=>{},h=>h.authorization='Bearer sk-ant-oat-other');throw new Error('wire auth drift accepted');}
catch(e){if(e.message==='wire auth drift accepted')throw e;}
const rows=readFileSync(process.env.PROMPT_COMPAT_WIRE,'utf8').trim().split('\\n').map(JSON.parse).filter(x=>x.kind==='messages');
if(rows.length!==8)throw new Error('changed wire auth reached transport');
const key=rows[0].wireContextSha256;
if(rows.slice(1,6).some(x=>x.wireContextSha256===key))throw new Error('meaningful drift missed');
if(rows.slice(6).some(x=>x.wireContextSha256!==key))throw new Error('permitted nuisance not normalized');
console.log('complete-context');
""")
            env = {**os.environ, "PROMPT_COMPAT_SOURCE": str(source),
                   "PROMPT_COMPAT_WIRE": str(root / "wire"),
                   "PROMPT_COMPAT_CWD": "/work", "PROMPT_COMPAT_MAX_MESSAGES": "9",
                   "PROMPT_COMPAT_AUTHORIZATION_SHA": reduce.digest(b"Bearer sk-ant-oat-fixture")}
            run = subprocess.run(["node", str(script)], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("complete-context", run.stdout)


class PiOracleTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("PROMPT_COMPAT_TEST_EXTENSION") and shutil.which("pi"),
                         "Set PROMPT_COMPAT_TEST_EXTENSION for real CLI fixture proof")
    def test_real_cli_accept_reject_and_wrong_answer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            auth = root / "auth.json"
            auth.write_text(json.dumps({"anthropic": {
                "type": "oauth", "access": "sk-ant-oat-synthetic-only",
                "refresh": "unused", "expires": time.time()*1000+3600000}}))
            hook = root / "transport.mjs"
            extension = pathlib.Path(os.environ["PROMPT_COMPAT_TEST_EXTENSION"])
            hook.write_text("""
import {sseResponse} from """ + json.dumps(str(extension.parent.parent / "compat/scenarios.js")) + """;
export default function(){
 globalThis.fetch=async(input,init)=>{
  const url=new URL(String(input));
  if(url.pathname==='/api/claude_cli/bootstrap')return Response.json({oauth_account:{account_uuid:'fixture'}});
  if(url.pathname!=='/v1/messages')throw new Error('fixture blocked unexpected network');
  const p=JSON.parse(Buffer.from(init.body).toString());
  const text=JSON.stringify(p.system);
  if(text.includes('BAD'))return Response.json({error:{type:'invalid_request_error',message:"You're out of extra usage."}},{status:400});
  const result=sseResponse(p.model).replace('"text":"OK"',text.includes('WRONG')?'"text":"incorrect"':'"text":"3973"');
  return new Response(result,{headers:{'content-type':'text/event-stream'}});
 };
}
""")
            config = root / "config.json"
            config.write_text(json.dumps({
                "mode": "fixture", "pi": shutil.which("pi"), "expectedPiVersion": "0.99.2",
                "extension": str(extension), "model": "claude-haiku-4-5", "cwd": str(root),
                "authPath": str(auth), "authProvider": "anthropic", "installId": "fixture-install",
                "wireContext": str(root / "wire-context.json"), "transportExtension": str(hook),
            }))
            for word, verdict in [("GOOD", "accept"), ("BAD", "reject"), ("WRONG", "inconclusive")]:
                trial = root / word
                trial.mkdir()
                prompt = trial / "prompt.txt"
                prompt.write_text(word)
                request = {"prompt": str(prompt), "promptSha256": reduce.digest(prompt.read_bytes()),
                           "outputDir": str(trial), "contextDigest": "fixture-context", "maxMessages": 1}
                run = subprocess.run([sys.executable, str(SCRIPTS / "pi_probe.py"), str(config)],
                                     input=json.dumps(request), capture_output=True, text=True, timeout=30)
                self.assertEqual(run.returncode, 0, run.stderr)
                result = json.loads(run.stdout)
                self.assertEqual(result["verdict"], verdict, result)
                self.assertEqual(result["messages"], 1)
                self.assertFalse(list(trial.glob("pi-probe-*")), "Temporary credential directory not removed")
            # Missing exact model is blocked by offline inventory, before inference.
            settings = json.loads(config.read_text())
            settings["model"] = "claude-no-such-model"
            config.write_text(json.dumps(settings))
            trial = root / "unavailable"
            trial.mkdir()
            prompt = trial / "prompt.txt"
            prompt.write_text("GOOD")
            request = {"prompt": str(prompt), "promptSha256": reduce.digest(prompt.read_bytes()),
                       "outputDir": str(trial), "contextDigest": "unavailable", "maxMessages": 1}
            run = subprocess.run([sys.executable, str(SCRIPTS / "pi_probe.py"), str(config)],
                                 input=json.dumps(request), capture_output=True, text=True, timeout=30)
            result = json.loads(run.stdout)
            self.assertEqual(result["verdict"], "inconclusive")
            self.assertEqual(result["messages"], 0)


if __name__ == "__main__":
    unittest.main()
