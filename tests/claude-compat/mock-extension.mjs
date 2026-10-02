import { appendFileSync, readFileSync } from 'node:fs';
const log = (event) => appendFileSync(process.env.VALIDATION_EVENTS, JSON.stringify(event)+'\n');
function sse(blocks,reason='end_turn') {
  const events=[{type:'message_start',message:{id:'msg_validation',type:'message',role:'assistant',model:'claude-haiku-4-5',content:[],stop_reason:null,stop_sequence:null,usage:{input_tokens:100,output_tokens:0}}}];
  blocks.forEach((b,index)=>{
    const start=b.type==='tool_use'?{...b,input:{}}:{type:'text',text:''};
    events.push({type:'content_block_start',index,content_block:start});
    events.push({type:'content_block_delta',index,delta:b.type==='tool_use'?{type:'input_json_delta',partial_json:JSON.stringify(b.input)}:{type:'text_delta',text:b.text}});
    events.push({type:'content_block_stop',index});
  });
  events.push({type:'message_delta',delta:{stop_reason:reason,stop_sequence:null},usage:{output_tokens:10}});
  events.push({type:'message_stop'});
  return events.map(e=>'event: '+e.type+'\ndata: '+JSON.stringify(e)+'\n\n').join('');
}
export default function(pi) {
  for(const name of ['Probe_MixedCase','Aux_Check']) pi.registerTool({
    name,label:name,description:'Return a private validation value; call both tools when asked to verify tools.',
    parameters:{type:'object',properties:{},additionalProperties:false},
    execute:async()=>{
      const value=readFileSync(process.env.VALIDATION_FIXTURE,'utf8').trim();
      log({type:'executed',name});
      return {content:[{type:'text',text:name==='Probe_MixedCase'?value:'auxiliary-ok'}],details:{}};
    }
  });
  pi.on('session_start',()=>log({type:'ready'}));
  pi.on('before_agent_start', event => {
    if (!event.systemPrompt.includes('about pi itself, its SDK') || !event.systemPrompt.includes(', pi packages (docs/packages.md),')) throw Error('Original Pi prompt was changed');
    log({type:'original-prompt-preserved'});
  });
  pi.on('agent_settled',()=>log({type:'settled'}));
  pi.on('message_end',e=>{if(e.message.role==='assistant')log({type:'assistant',message:e.message});});
  globalThis.fetch=async(input,init)=>{
    const url=new URL(input instanceof Request?input.url:String(input));
    if(url.origin!=='https://api.anthropic.com')throw new Error('Unexpected synthetic-test network origin');
    if(url.pathname==='/api/claude_cli/bootstrap')return Response.json({oauth_account:{account_uuid:'mock-account'}});
    if(url.pathname!=='/v1/messages')throw new Error('Unexpected synthetic-test path');
    const p=JSON.parse(Buffer.from(init.body).toString());
    if(!p.system[0].text.startsWith('x-anthropic-billing-header:'))throw new Error('Compat middleware did not execute');
    const system=p.system.filter(b=>b.type==='text').map(b=>b.text).join('\n');
    if (!system.includes('about Pi itself, its SDK') || !system.includes(', Pi packages (docs/packages.md),')) throw Error('Guard did not reach outgoing wire');
    if (system.includes('about pi itself, its SDK') || system.includes(', pi packages (docs/packages.md),')) throw Error('Unpatched built-in docs reached outgoing wire');
    if (!system.includes('When reading pi docs or examples')) throw Error('Guard changed unrelated instructions');
    log({type:'wire-guard-passed',model:p.model});
    const texts=p.messages.filter(m=>m.role==='user').flatMap(m=>typeof m.content==='string'?[m.content]:m.content.filter(b=>b.type==='text').map(b=>b.text));
    const last=texts.at(-1)||'';
    log({type:'request',last,toolNames:p.tools?.map(t=>t.name),thinking:p.thinking});
    if(last.includes('SLOW-PROBE')) {
      await new Promise((resolve,reject)=>{
        const timer=setTimeout(resolve,60000);
        const abort=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};
        if(init.signal?.aborted)abort();else init.signal?.addEventListener('abort',abort,{once:true});
      });
    }
    if(last.includes('REJECT-PROBE'))return Response.json({type:'error',error:{type:'invalid_request_error',message:'Synthetic request rejection'}},{status:400});
    const tail=p.messages.at(-1)?.content;
    const results=Array.isArray(tail)?tail.filter(b=>b.type==='tool_result'):[];
    if(last.includes('TOOLS-PROBE')&&!results.length) {
      const names=['_Probe_MixedCase','_Aux_Check'];
      for(const name of names)if(!p.tools?.some(t=>t.name===name))throw new Error('Missing mixed-case wire declaration '+name);
      return new Response(sse(names.map((name,i)=>({type:'tool_use',id:'tool_'+i,name,input:{}})),'tool_use'),{headers:{'content-type':'text/event-stream'}});
    }
    let answer;
    if(results.length) {
      const content=JSON.stringify(results);
      const value=readFileSync(process.env.VALIDATION_FIXTURE,'utf8').trim();
      if(!content.includes(value)||!content.includes('auxiliary-ok'))throw new Error('Tool results missing from second request');
      answer='TOOLS-COMPLETE '+value;
    }else if(last.includes('RECALL-PROBE')) {
      const corpus=JSON.stringify(p.messages);
      const value=readFileSync(process.env.VALIDATION_FIXTURE,'utf8').trim();
      answer=corpus.includes('TOOLS-COMPLETE '+value)?'RECALL-COMPLETE '+value:'MISSING-HISTORY';
    }else if(last.includes('RECOVER-PROBE')) {
      answer=JSON.stringify(p.messages).includes('SLOW-PROBE')?'RECOVER-COMPLETE prior request preserved':'MISSING-HISTORY';
    }else answer='ARITHMETIC-COMPLETE '+(137*29);
    return new Response(sse([{type:'text',text:answer}]),{headers:{'content-type':'text/event-stream'}});
  };
}
