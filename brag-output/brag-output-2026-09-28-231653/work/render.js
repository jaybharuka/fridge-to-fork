const { chromium } = require('C:/Projects/fridge-to-fork/brag-output/work/node_modules/playwright');
const path=require('path'),fs=require('fs');
const {appT,DUR,FPS}=require('./timing');
const cap=require('./cap.json');const rel=cap.frames.map(x=>x-cap.T0);
const idxAt=a=>{let lo=0,hi=rel.length-1;while(lo<hi){const m=(lo+hi+1)>>1;rel[m]<=a?lo=m:hi=m-1}return lo};
(async()=>{
  const times=process.argv[2]?process.argv[2].split(',').map(Number):null;
  const browser=await chromium.launch();
  const page=await browser.newPage({viewport:{width:1920,height:1080}});
  await page.goto('file://'+path.join(__dirname,'scene.html'));
  await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(800);
  fs.mkdirSync(path.join(__dirname,'frames'),{recursive:true});
  const list=times?times.map(t=>[t,path.join(__dirname,`still_${t}.png`)]):Array.from({length:Math.round(DUR*FPS)},(_,i)=>[i/FPS,path.join(__dirname,'frames',`f${String(i).padStart(5,'0')}.png`)]);
  for(const [t,f] of list){
    const ci=idxAt(appT(t));
    await page.evaluate(([t,s])=>window.__setTime(t,s),[t,'file:///'+path.join(__dirname,'cap',`c${String(ci).padStart(5,'0')}.jpg`).split(path.sep).join('/')]);
    await page.screenshot({path:f});
  }
  await browser.close();
})();
