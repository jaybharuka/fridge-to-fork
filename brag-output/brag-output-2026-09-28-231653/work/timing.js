// video-time -> app-recording-time keyframes (piecewise linear)
module.exports.KF=[[0,1.4],[2.0,1.4],[2.5,1.81],[2.9,2.5],[3.1,4.05],[3.5,4.4],[7.0,13.0],[10.5,14.6],[11.5,15.6],[12.0,17.7],[13.5,19.4],[15.0,20.6],[15.5,21.4],[16.5,22.6],[17.0,24.0],[17.4,24.5],[19.0,26.7],[19.5,27.4],[20.6,30.2],[21.0,30.9],[21.7,32.2],[22.0,32.6],[30,32.6]];
module.exports.appT=v=>{const K=module.exports.KF;for(let i=1;i<K.length;i++)if(v<=K[i][0]){const[a,b]=[K[i-1],K[i]];return a[1]+(b[1]-a[1])*(v-a[0])/(b[0]-a[0])}return K[K.length-1][1]};
module.exports.DUR=25;module.exports.FPS=30;
