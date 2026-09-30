const fs=require('fs');const SR=44100,DUR=25,N=SR*DUR;
const L=new Float32Array(N),R=new Float32Array(N),WL=new Float32Array(N),WR=new Float32Array(N);
const mtof=m=>440*Math.pow(2,(m-69)/12);const NOTE={C:0,D:2,E:4,F:5,G:7,A:9,B:11};const m=(n,o)=>12*(o+1)+NOTE[n];
function add(t,dur,fn,gain,pan=0,send=.25){const s=Math.floor(t*SR),e=Math.min(N,Math.floor((t+dur)*SR));const gl=gain*(1-Math.max(0,pan)),gr=gain*(1+Math.min(0,pan));
  for(let i=Math.max(0,s);i<e;i++){const x=fn((i-s)/SR,(i-s)/(e-s));L[i]+=x*gl;R[i]+=x*gr;WL[i]+=x*gl*send;WR[i]+=x*gr*send}}
const sine=(f,t)=>Math.sin(2*Math.PI*f*t);
const tone=(f,att,dec)=>t=>Math.min(1,t/att)*Math.exp(-t/dec)*(sine(f,t)+.25*sine(2*f,t)*Math.exp(-t*6)+.1*sine(3*f,t)*Math.exp(-t*10));
const padTone=(f,dur)=>t=>Math.min(1,t/.7)*Math.min(1,(dur-t)/.6)*(sine(f,t)+.7*sine(f*1.004,t)+.15*sine(f*2,t));
const chords=[[[m('C',3),m('E',3),m('G',3),m('C',4)],m('C',2)],[[m('B',2),m('D',3),m('G',3),m('D',4)],m('G',1)],[[m('A',2),m('C',3),m('E',3),m('A',3)],m('A',1)],[[m('A',2),m('C',3),m('F',3),m('A',3)],m('F',1)]];
const beat=.5,bars=Math.ceil(DUR/2);
for(let bar=0;bar<bars;bar++){const t0=bar*2,c=chords[bar%4],dur=2.4;
  if(t0>=DUR-1)break;const outro=t0>=22;
  c[0].forEach((n,k)=>add(t0,dur,padTone(mtof(n),dur),outro?.075:.055,(k-1.5)*.25,.35));
  if(t0>=2)[0,2].forEach(b=>add(t0+b*beat,.9,tone(mtof(c[1]+12),.01,.35),.26,0,.05));
  if(t0>=2&&t0<22){const arp=[c[0][0]+12,c[0][1]+12,c[0][2]+12,c[0][3]+12,c[0][2]+12,c[0][1]+12,c[0][3]+12,c[0][2]+12];
    arp.forEach((n,i)=>{const tt=t0+i*beat/2;if(tt<2)return;add(tt,.5,tone(mtof(n),.004,.16),tt>=15?.085:.06,i%2?.35:-.35,.4)})}
}
// kick 7.0-22.0 quarters, hats 10.5-22, claps 15-22 on 2&4 (bar grid = 2s)
const kick=t=>add(t,.3,x=>Math.sin(2*Math.PI*(45*x+4*(1-Math.exp(-18*x))))*Math.exp(-x*14)*Math.min(1,x/.002),.27,0,0);
for(let t=7;t<22;t+=beat)kick(t);
for(let t=10.5;t<22;t+=beat/2){let z=0;add(t,.06,x=>{const w=Math.random()*2-1;const o=w-z;z=w;return o*Math.exp(-x*90)},(Math.round((t-10.5)/(beat/2))%2)?.035:.02,.3,.15)}
for(let t=15.5;t<22;t+=1){let lp=0;add(t,.18,x=>{const w=Math.random()*2-1;lp+=.5*(w-lp);return lp*Math.exp(-x*28)},.08,0,.3)}
// hook: sub pulse + riser, impact at 2.0
[0,.5,1.0,1.5].forEach(t=>add(t,.4,x=>sine(55,x)*Math.exp(-x*8),.22*(0.5+t/2),0,0));
let lp0=0;add(0,2.0,(x,p)=>{const w=Math.random()*2-1;const a=.02+.5*p*p;lp0+=a*(w-lp0);return lp0*p*p},.5,0,.3);
const impact=(t,g=1)=>{add(t,.9,x=>sine(52,x)*Math.exp(-x*5)*(1+.5*Math.exp(-x*30)),.34*g,0,.1);let lp=0;add(t-.12,.6,(x,p)=>{const w=Math.random()*2-1;lp+=(.04+.5*Math.sin(Math.PI*p))*(w-lp);return lp*Math.sin(Math.PI*p)},.4*g,0,.3)};
impact(2.0);impact(7.0,.9);impact(10.5,.9);impact(15.0,1);impact(22.0,1.1);
const pent=['C5','D5','E5','G5','A5','C6'].map(s=>mtof(m(s[0],+s[1])));
const blip=(t,f,g=.11,pan=0)=>add(t,.4,tone(f,.003,.09),g,pan,.45);
// taps (UI clicks): tick + soft pluck
[2.5,3.5,17.0,19.5].forEach((t,i)=>{blip(t,pent[[2,3,4,5][i]],.16);add(t,.06,x=>(Math.random()*2-1)*Math.exp(-x*120),.06,0,0)});
// scan riser during scan, detection ticks
add(3.6,1.6,(x,p)=>sine(280+800*p*p,x)*Math.sin(Math.PI*p)*.5,.045,0,.3);
for(let i=0;i<8;i++)blip(5.2+i*.18,pent[[0,2,3,1,4,5,3,2][i]],.085,(i%2?.4:-.4));
// checklist scroll swooshes
[[11.5,.6],[12.0,1.3]].forEach(([t,d])=>{let lp=0;add(t,d,(x,p)=>{const w=Math.random()*2-1;lp+=(.03+.2*Math.sin(Math.PI*p))*(w-lp);return lp*Math.sin(Math.PI*p)},.22,0,.3)});
// sheet whoosh up
{let lp=0;add(17.3,.6,(x,p)=>{const w=Math.random()*2-1;lp+=(.03+.35*p)*(w-lp);return lp*Math.sin(Math.PI*Math.min(1,p*1.2))},.25,0,.3)}
// success chime at order confirmed (21.0) and outro sparkle
[0,1,2,3].forEach(i=>add(21.0+i*.09,1.6,tone(mtof(m('C',5))*[1,1.25,1.5,2][i],.004,.5),.13,0,.5));
[0,1,2,3,4].forEach(i=>add(22.4+i*.14,1.4,tone(mtof(m('C',6))*[1,1.25,1.5,2,1.5][i],.004,.4),.05,(i%2?.3:-.3),.5));
function delay(W,out,d,fb,mix){const dd=Math.floor(d*SR);const buf=new Float32Array(N);let lp=0;for(let i=0;i<N;i++){const x=W[i]+(i>=dd?buf[i-dd]*fb:0);lp+=.35*(x-lp);buf[i]=lp;out[i]+=buf[i]*mix}}
delay(WL,L,.375,.45,.9);delay(WR,R,.5,.45,.9);
let pk=0;for(let i=0;i<N;i++){L[i]=Math.tanh(L[i]*1.1);R[i]=Math.tanh(R[i]*1.1);pk=Math.max(pk,Math.abs(L[i]),Math.abs(R[i]))}
const sc=.7/pk;const buf=Buffer.alloc(44+N*4);buf.write('RIFF',0);buf.writeUInt32LE(36+N*4,4);buf.write('WAVEfmt ',8);buf.writeUInt32LE(16,16);buf.writeUInt16LE(1,20);buf.writeUInt16LE(2,22);buf.writeUInt32LE(SR,24);buf.writeUInt32LE(SR*4,28);buf.writeUInt16LE(4,32);buf.writeUInt16LE(16,34);buf.write('data',36);buf.writeUInt32LE(N*4,40);
for(let i=0;i<N;i++){const t=i/SR;const f=Math.min(1,t/.02)*Math.min(1,(DUR-t)/1.5);buf.writeInt16LE(Math.round(L[i]*sc*f*32767),44+i*4);buf.writeInt16LE(Math.round(R[i]*sc*f*32767),46+i*4)}
fs.writeFileSync('audio.wav',buf);console.log('peak',pk);
