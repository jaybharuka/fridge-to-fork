const fs=require('fs');const SR=44100,DUR=20,N=SR*DUR;
const L=new Float32Array(N),R=new Float32Array(N),WL=new Float32Array(N),WR=new Float32Array(N); // dry, wet(send)
const mtof=m=>440*Math.pow(2,(m-69)/12);
const NOTE={C:0,D:2,E:4,G:7,A:9,F:5,B:11};
const m=(n,o)=>12*(o+1)+NOTE[n];
function add(t,dur,fn,gain,pan=0,send=.25){const s=Math.floor(t*SR),e=Math.min(N,Math.floor((t+dur)*SR));
  const gl=gain*(1-Math.max(0,pan)),gr=gain*(1+Math.min(0,pan));
  for(let i=s;i<e;i++){const x=fn((i-s)/SR,(i-s)/(e-s));L[i]+=x*gl;R[i]+=x*gr;WL[i]+=x*gl*send;WR[i]+=x*gr*send}}
const sine=(f,t)=>Math.sin(2*Math.PI*f*t);
function tone(f,att,dec){return (t,p)=>{const env=Math.min(1,t/att)*Math.exp(-t/dec);return env*(sine(f,t)+.25*sine(2*f,t)*Math.exp(-t*6)+.1*sine(3*f,t)*Math.exp(-t*10))}}
function padTone(f,dur){return (t,p)=>{const env=Math.min(1,t/.6)*Math.min(1,(dur-t)/.5);return env*(sine(f,t)+sine(f*1.004,t)*.7+.3*sine(f*2,t)*.5)*.5}}
const chords=[['C',[m('C',3),m('E',3),m('G',3),m('C',4)],m('C',2)],['G',[m('B',2),m('D',3),m('G',3),m('D',4)],m('G',1)],['A',[m('A',2),m('C',3)+0,m('E',3),m('A',3)],m('A',1)],['F',[m('A',2),m('C',3),m('F',3),m('A',3)],m('F',1)]];
const prog=[0,1,2,3,0,1,2,3,0,0];
const beat=.5;
prog.forEach((ci,bar)=>{const t0=bar*4*beat,c=chords[ci],dur=4*beat+.4;
  c[1].forEach((n,k)=>add(t0,dur,padTone(mtof(n),dur),.06,(k-1.5)*.25,.35));
  [0,2].forEach(b=>add(t0+b*beat,beat*1.8,tone(mtof(c[2]+12),.01,.35),.28,0,.05));
  // arp from 3.0
  if(t0>=3-1e-6){const arp=[c[1][0]+12,c[1][1]+12,c[1][2]+12,c[1][3]+12,c[1][2]+12,c[1][1]+12,c[1][3]+12,c[1][2]+12];
    const g=t0>=12.5-1e-6?.085:.06;
    arp.forEach((n,i)=>add(t0+i*beat/2,.5,tone(mtof(n),.004,.16),g,(i%2?.35:-.35),.4))}
  // kick from 7.5 (quarters), hats from 12.5
  if(t0>=7.5-1e-6&&bar<9)for(let b=0;b<4;b++)add(t0+b*beat,.3,(t)=>Math.sin(2*Math.PI*(45*t+ (75/18)*(1-Math.exp(-18*t)) *1))*Math.exp(-t*14)*Math.min(1,t/.002),.28,0,0);
  if(t0>=12.5-1e-6&&bar<9)for(let b=0;b<8;b++){let z=0,y=0;add(t0+b*beat/2+ (b%2?0:0),.05,(t)=>{const w=Math.random()*2-1;const o=w-z;z=w;return o*Math.exp(-t*90)},b%2?.035:.02,b%2?.3:-.3,.15)}
});
// SFX
function whoosh(t){let lp=0;add(t-.1,.6,(x,p)=>{const w=Math.random()*2-1;const a=.04+.5*Math.sin(Math.PI*Math.min(1,x/.6))*.6;lp+=a*(w-lp);return lp*Math.sin(Math.PI*Math.min(1,x/.6))},.55,0,.3)}
[3.0,7.5,12.5,17.5].forEach(whoosh);
const pent=['C5','D5','E5','G5','A5','C6'].map(s=>mtof(m(s[0],+s[1])));
const blip=(t,f,g=.11,pan=0)=>add(t,.4,tone(f,.003,.09),g,pan,.45);
[4.6,4.85,5.1,5.35].forEach((t,i)=>blip(t,pent[i+1],.08,i%2?.4:-.4)); // chips
add(3.9,1.7,(t,p)=>sine(300+700*p*p,t)*Math.sin(Math.PI*p)*.5,.05,0,.3); // scan glide
for(let i=0;i<6;i++)blip(8.3+i*.32,pent[[0,2,3,1,4,5][i]],.1,(i-2.5)*.15);
[10.4,10.5,10.6].forEach((t,i)=>blip(t,mtof(m('C',6)+[0,4,7][i]),.07)); // missing highlight
[14.0,14.5,15.0].forEach((t,i)=>{blip(t,pent[[2,3,5][i]],.13);add(t,.2,(x)=>Math.sin(2*Math.PI*(180-400*x)*x)*Math.exp(-x*30),.15,0,0)}); // cart adds
[0,1,2,3].forEach(i=>add(17.6+i*.09,1.6,tone(mtof(m('C',5))*[1,1.25,1.5,2][i],.004,.5),.11,0,.5)); // outro chime
// wet: 2-tap feedback delay w/ lowpass, mixed back
function delay(W,out,dSec,fb,mix){const d=Math.floor(dSec*SR);const buf=new Float32Array(N);let lp=0;
  for(let i=0;i<N;i++){const x=W[i]+(i>=d?buf[i-d]*fb:0);lp+=.35*(x-lp);buf[i]=lp;out[i]+=buf[i]*mix}}
delay(WL,L,.375,.45,.9);delay(WR,R,.5,.45,.9);
// master
let pk=0;for(let i=0;i<N;i++){L[i]=Math.tanh(L[i]*1.1);R[i]=Math.tanh(R[i]*1.1);pk=Math.max(pk,Math.abs(L[i]),Math.abs(R[i]))}
const sc=.7/pk;
const buf=Buffer.alloc(44+N*4);buf.write('RIFF',0);buf.writeUInt32LE(36+N*4,4);buf.write('WAVEfmt ',8);buf.writeUInt32LE(16,16);buf.writeUInt16LE(1,20);buf.writeUInt16LE(2,22);buf.writeUInt32LE(SR,24);buf.writeUInt32LE(SR*4,28);buf.writeUInt16LE(4,32);buf.writeUInt16LE(16,34);buf.write('data',36);buf.writeUInt32LE(N*4,40);
for(let i=0;i<N;i++){const t=i/SR;const f=Math.min(1,t/.05)*Math.min(1,(DUR-t)/1.2);buf.writeInt16LE(Math.round(L[i]*sc*f*32767),44+i*4);buf.writeInt16LE(Math.round(R[i]*sc*f*32767),46+i*4)}
fs.writeFileSync('audio.wav',buf);console.log('peak',pk);
