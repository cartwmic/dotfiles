#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { piCodingAgentRoot } from '../pi-root.mjs';
const args=process.argv.slice(2);if(args.some(a=>!['--check','--rollback'].includes(a)))throw Error('Usage: patch.mjs [--check|--rollback]');
const check=args.includes('--check'),rollback=args.includes('--rollback')||!['personal','axon-work-computer'].includes(process.env.PI_CHEZMOI_PROFILE);
const root=piCodingAgentRoot();if(!root)throw Error('Pi1.2.0 package root unavailable');
if(JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8')).version!=='1.2.0')throw Error('btw-native-session payload supports exact Pi1.2.0 only');
const edits=JSON.parse(fs.readFileSync(new URL('./edits.pi-1.2.json',import.meta.url),'utf8'));const staged=new Map();
const targetFile=edit=>edit.package==='pi-coding-agent'?path.join(root,edit.path):path.join(root,'..',edit.package,edit.path);
if(rollback&&!edits.some(edit=>fs.readFileSync(targetFile(edit),'utf8').includes(edit.new))){
 console.log(JSON.stringify({patch:'btw-native-session',rollback:true,alreadyUnpatched:true}));process.exit(0);
}
// Reverse own checked blocks first, then reapply when requested. This handles
// overlapping context anchors without restoring entire files or losing siblings.
for(const edit of [...edits].reverse()){
 const file=edit.package==='pi-coding-agent'?path.join(root,edit.path):path.join(root,'..',edit.package,edit.path);
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
 staged.set(file,text.replace(from,to));
}
if(!rollback)for(const edit of edits){
 const file=edit.package==='pi-coding-agent'?path.join(root,edit.path):path.join(root,'..',edit.package,edit.path);
 const text=staged.get(file)??fs.readFileSync(file,'utf8');
 if(text.split(edit.old).length-1!==1)throw Error('Checked apply anchor drift: '+edit.package+'/'+edit.path);
 staged.set(file,text.replace(edit.old,edit.new));
}
for(const[file,text]of staged)if(text===fs.readFileSync(file,'utf8'))staged.delete(file);
if(!check)for(const[file,text]of staged)fs.writeFileSync(file,text);
console.log(JSON.stringify({patch:'btw-native-session',version:'1.2.0',check,rollback,pendingFiles:staged.size}));
