const fs=require('fs'),path=require('path'),assert=require('assert'),{chromium}=require('playwright'),{execFileSync}=require('child_process');
(async()=>{
 const root=process.argv[2],dir=path.join(root,'capture'),meta=JSON.parse(fs.readFileSync(path.join(dir,'metadata.json'))),actions=JSON.parse(fs.readFileSync(path.join(dir,'actions.json')));
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM,headless:true}),context=await browser.newContext({viewport:{width:800,height:800},permissions:['clipboard-read','clipboard-write']}),page=await context.newPage(),errors=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));await page.route(/^https?:/,r=>r.abort());
 const url='file://'+dir+'/phone.html';await page.goto(url);await page.evaluate(()=>player.play());await page.evaluate(()=>player.pause());
 async function seek(t){await page.evaluate(t=>player.seek(t),t);await page.waitForTimeout(200);await page.evaluate(()=>snapshot());return page.locator('#input-keys').textContent();}
 const typed=await seek(actions[0].time+.1);assert(typed.includes('Typed: '+actions[0].value));assert(!typed.includes('Key: Enter'));
 const key=await seek(actions[1].time+.1);assert(key.includes('Typed: '+actions[0].value)&&key.includes('Key: Enter'));
 assert.equal(await seek(actions[0].time+.1),typed,'backward seek restores exact input annotation');
 const expired=await seek(meta.cast_duration-.001);assert(expired.includes('No recent input'));
 await seek(actions[1].time+.1);await page.screenshot({path:path.join(root,'overlay-browser.png')});
 await page.locator('button').filter({hasText:'Copy text'}).click();await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),await page.locator('#frame').textContent());assert((await page.locator('#frame').textContent()).includes('RESPONSE STAYS VISIBLE'));
 assert.equal(errors.length,0);assert(requests.every(r=>r===url));
 await browser.close();
 // Decode actual movie pixels: the dedicated action band changes, while it stays below the terminal.
 const ff=process.env.FFMPEG,video=path.join(dir,'phone.mp4'),gif=fs.readFileSync(path.join(dir,'render.gif')),width=gif.readUInt16LE(6),height=gif.readUInt16LE(8),band=meta.actions.overlay_height;
 function rgb(t){return execFileSync(ff,['-v','error','-ss',String(t),'-i',video,'-frames:v','1','-vf','crop='+width+':'+band+':0:'+height,'-pix_fmt','rgb24','-f','rawvideo','-'],{maxBuffer:20*1024*1024});}
 const on=rgb(actions[1].time+.1),off=rgb(meta.cast_duration-.05);assert.equal(on.length,off.length);let changed=0,bright=0;
 for(let i=0;i<on.length;i+=3){if(Math.abs(on[i]-off[i])+Math.abs(on[i+1]-off[i+1])+Math.abs(on[i+2]-off[i+2])>90)changed++;if(on[i]>170&&on[i+1]>170&&on[i+2]>170)bright++;}
 assert(changed>100&&bright>100,'decoded movie contains visible changing key/text annotation pixels');
 execFileSync(ff,['-v','error','-y','-ss',String(actions[1].time+.1),'-i',video,'-frames:v','1',path.join(root,'overlay-movie.png')]);
 fs.writeFileSync(path.join(root,'browser-movie-receipt.json'),JSON.stringify({status:'passed',typed,key,expired,offline_requests:requests,errors,backward_seek:true,clipboard:true,decoded_movie_band:{width,height,band,changed_pixels:changed,bright_pixels:bright}},null,2));
 console.log('PASS: actual movie annotation pixels below terminal; offline typed/key overlays, backwards seek, expiry and clipboard; literals never executed.');
})().catch(e=>{console.error(e);process.exit(1)});
