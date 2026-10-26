#!/usr/bin/env node
// Pi 1.4.0 and later. Anchor-gated, not version-gated: every edit must match exactly once or nothing is written.
// Bundle chunk names change on every Pi build, so each chunk path in edits.pi-1.4.json is only a 1.4.0 hint;
// the real chunk is the single bundle file that contains the group's first old or new block.
import fs from 'node:fs';
import path from 'node:path';
import { piCodingAgentRoot } from '../pi-root.mjs';
const args=process.argv.slice(2);if(args.some(a=>!['--check','--rollback'].includes(a)))throw Error('Usage: patch.mjs [--check|--rollback]');
const check=args.includes('--check'),rollback=args.includes('--rollback')||!['personal','axon-work-computer'].includes(process.env.PI_CHEZMOI_PROFILE);
const root=piCodingAgentRoot();if(!root)throw Error('Pi package root unavailable');
const version=JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8')).version;
const edits=JSON.parse(fs.readFileSync(new URL('./edits.pi-1.4.json',import.meta.url),'utf8'));const staged=new Map();
const chunkDir=path.join(root,'dist/bundle/chunks');const chunkNames=fs.existsSync(chunkDir)?fs.readdirSync(chunkDir).filter(n=>n.endsWith('.js')):[];
const chunkFor=new Map();
for(const edit of edits){
 if(edit.package!=='pi-coding-agent'||!edit.path.startsWith('dist/bundle/chunks/')||chunkFor.has(edit.path))continue;
 const hits=chunkNames.filter(n=>{const t=fs.readFileSync(path.join(chunkDir,n),'utf8');return t.includes(edit.old)||t.includes(edit.new)});
 if(hits.length!==1)throw Error('Expected one bundle chunk for '+edit.path+', found '+hits.length+'; no files were changed');
 chunkFor.set(edit.path,path.join(chunkDir,hits[0]));
}
const targetFile=edit=>edit.package==='pi-coding-agent'?(chunkFor.get(edit.path)??path.join(root,edit.path)):path.join(root,'..',edit.package,edit.path);
// A removal edit's new text is part of stock code, so it does not prove the patch is present.
if(rollback&&!edits.some(edit=>!edit.old.includes(edit.new)&&fs.readFileSync(targetFile(edit),'utf8').includes(edit.new))){
 console.log(JSON.stringify({patch:'btw-native-session',rollback:true,alreadyUnpatched:true}));process.exit(0);
}
// Reverse own checked blocks first, then reapply when requested. This handles
// overlapping context anchors without restoring entire files or losing siblings.
for(const edit of [...edits].reverse()){
 const file=targetFile(edit);
 let text=staged.get(file)??fs.readFileSync(file,'utf8');const from=edit.new,to=edit.old;
 const count=s=>text.split(s).length-1;
 // A removal's new context may occur inside the original block: do not
 // reverse it until the complete original block is absent.
 if(edit.old.includes(edit.new)&&count(edit.old)===1)continue;
 if(count(edit.new)===0){
  if(rollback&&count(edit.old)!==1)throw Error('Owned rollback block drift: '+edit.package+'/'+edit.path);
  continue;
 }
 if(!from||count(from)!==1)throw Error('Checked native-session anchor drift: '+edit.package+'/'+edit.path);
 staged.set(file,text.replace(from,()=>to));
}
if(!rollback)for(const edit of edits){
 const file=targetFile(edit);
 const text=staged.get(file)??fs.readFileSync(file,'utf8');
 if(text.split(edit.old).length-1!==1)throw Error('Checked apply anchor drift: '+edit.package+'/'+edit.path);
 staged.set(file,text.replace(edit.old,()=>edit.new));
}
for(const[file,text]of staged)if(text===fs.readFileSync(file,'utf8'))staged.delete(file);
if(!check)for(const[file,text]of staged)fs.writeFileSync(file,text);
console.log(JSON.stringify({patch:'btw-native-session',version,check,rollback,pendingFiles:staged.size}));
