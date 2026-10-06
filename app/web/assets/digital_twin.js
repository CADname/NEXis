(()=>{
'use strict';
const VSH=`attribute vec3 aPos;attribute vec3 aNormal;uniform mat4 uMVP;uniform mat4 uModel;varying float vLight;void main(){vec3 n=normalize(mat3(uModel)*aNormal);vec3 l=normalize(vec3(-0.55,0.9,0.65));vLight=.42+.58*max(dot(n,l),0.0);gl_Position=uMVP*vec4(aPos,1.0);}`;
const FSH=`precision mediump float;uniform vec4 uColor;varying float vLight;void main(){gl_FragColor=vec4(uColor.rgb*vLight,uColor.a);}`;
const LINE_VSH=`attribute vec3 aPos;uniform mat4 uMVP;void main(){gl_Position=uMVP*vec4(aPos,1.0);}`;
const LINE_FSH=`precision mediump float;uniform vec4 uColor;void main(){gl_FragColor=uColor;}`;
function shader(gl,type,src){const s=gl.createShader(type);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s}
function program(gl,vs,fs){const p=gl.createProgram();gl.attachShader(p,shader(gl,gl.VERTEX_SHADER,vs));gl.attachShader(p,shader(gl,gl.FRAGMENT_SHADER,fs));gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(p));return p}
function I(){return new Float32Array([1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])}
function mul(a,b){const o=new Float32Array(16);for(let c=0;c<4;c++)for(let r=0;r<4;r++)o[c*4+r]=a[0*4+r]*b[c*4+0]+a[1*4+r]*b[c*4+1]+a[2*4+r]*b[c*4+2]+a[3*4+r]*b[c*4+3];return o}
function T(x,y,z){const m=I();m[12]=x;m[13]=y;m[14]=z;return m}
function S(x,y,z){const m=I();m[0]=x;m[5]=y;m[10]=z;return m}
function RX(a){const c=Math.cos(a),s=Math.sin(a),m=I();m[5]=c;m[6]=s;m[9]=-s;m[10]=c;return m}
function RY(a){const c=Math.cos(a),s=Math.sin(a),m=I();m[0]=c;m[2]=-s;m[8]=s;m[10]=c;return m}
function RZ(a){const c=Math.cos(a),s=Math.sin(a),m=I();m[0]=c;m[1]=s;m[4]=-s;m[5]=c;return m}
function perspective(fov,aspect,near,far){const f=1/Math.tan(fov/2),nf=1/(near-far),m=new Float32Array(16);m[0]=f/aspect;m[5]=f;m[10]=(far+near)*nf;m[11]=-1;m[14]=2*far*near*nf;return m}
function norm(v){const l=Math.hypot(v[0],v[1],v[2])||1;return[v[0]/l,v[1]/l,v[2]/l]}
function cross(a,b){return[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]}
function sub(a,b){return[a[0]-b[0],a[1]-b[1],a[2]-b[2]]}
function lookAt(e,c,u){const z=norm(sub(e,c)),x=norm(cross(u,z)),y=cross(z,x),m=I();m[0]=x[0];m[1]=y[0];m[2]=z[0];m[4]=x[1];m[5]=y[1];m[6]=z[1];m[8]=x[2];m[9]=y[2];m[10]=z[2];m[12]=-(x[0]*e[0]+x[1]*e[1]+x[2]*e[2]);m[13]=-(y[0]*e[0]+y[1]*e[1]+y[2]*e[2]);m[14]=-(z[0]*e[0]+z[1]*e[1]+z[2]*e[2]);return m}
function compose(pos,rot,scale){let m=T(pos[0],pos[1],pos[2]);m=mul(m,RX(rot[0]||0));m=mul(m,RY(rot[1]||0));m=mul(m,RZ(rot[2]||0));return mul(m,S(scale[0],scale[1],scale[2]))}
function cube(){const p=[],n=[];const faces=[[[1,0,0],[[1,-1,-1],[1,1,-1],[1,1,1],[1,-1,1]]],[[-1,0,0],[[-1,-1,1],[-1,1,1],[-1,1,-1],[-1,-1,-1]]],[[0,1,0],[[-1,1,-1],[-1,1,1],[1,1,1],[1,1,-1]]],[[0,-1,0],[[-1,-1,1],[-1,-1,-1],[1,-1,-1],[1,-1,1]]],[[0,0,1],[[1,-1,1],[1,1,1],[-1,1,1],[-1,-1,1]]],[[0,0,-1],[[-1,-1,-1],[-1,1,-1],[1,1,-1],[1,-1,-1]]]];for(const [nn,v] of faces){for(const q of [v[0],v[1],v[2],v[0],v[2],v[3]]){p.push(...q);n.push(...nn)}}return{p:new Float32Array(p),n:new Float32Array(n)}}
function cylinder(seg=40){const p=[],n=[];for(let i=0;i<seg;i++){const a=i*2*Math.PI/seg,b=(i+1)*2*Math.PI/seg,ca=Math.cos(a),sa=Math.sin(a),cb=Math.cos(b),sb=Math.sin(b);const v1=[ca,-1,sa],v2=[ca,1,sa],v3=[cb,1,sb],v4=[cb,-1,sb];for(const q of [v1,v2,v3,v1,v3,v4]){p.push(...q);const d=q===v3||q===v4?[cb,0,sb]:[ca,0,sa];n.push(...d)}for(const q of [[0,1,0],[ca,1,sa],[cb,1,sb]]){p.push(...q);n.push(0,1,0)}for(const q of [[0,-1,0],[cb,-1,sb],[ca,-1,sa]]){p.push(...q);n.push(0,-1,0)}}return{p:new Float32Array(p),n:new Float32Array(n)}}
function mesh(gl,data){const vao={count:data.p.length/3,p:gl.createBuffer(),n:gl.createBuffer()};gl.bindBuffer(gl.ARRAY_BUFFER,vao.p);gl.bufferData(gl.ARRAY_BUFFER,data.p,gl.STATIC_DRAW);gl.bindBuffer(gl.ARRAY_BUFFER,vao.n);gl.bufferData(gl.ARRAY_BUFFER,data.n,gl.STATIC_DRAW);return vao}
const COLORS={wood:[.53,.33,.17,1],woodLight:[.68,.48,.27,1],woodTop:[.73,.54,.32,1],steel:[.68,.73,.78,1],steel2:[.38,.45,.52,1],dark:[.08,.11,.14,1],black:[.035,.045,.055,1],pcb:[.05,.38,.23,1],pcb2:[.08,.62,.35,1],yellow:[.98,.78,.12,1],red:[.96,.15,.18,1],blue:[.12,.42,.90,1],orange:[1.0,.43,.08,1],greenOn:[.15,1.0,.28,1],greenOff:[.025,.16,.05,1],white:[.90,.94,.97,1]};
class Twin{
 constructor(canvas,opt={}){this.c=canvas;this.locked=!!opt.locked;this.gl=canvas.getContext('webgl',{antialias:true,alpha:false});if(!this.gl){canvas.parentElement.classList.add('no-webgl');return}this.p=program(this.gl,VSH,FSH);this.lp=program(this.gl,LINE_VSH,LINE_FSH);this.cube=mesh(this.gl,cube());this.cyl=mesh(this.gl,cylinder());this.state='normal';this.active=false;this.rpm=0;this.angle=0;this.yaw=-.66;this.pitch=.34;this.radius=12.6;this.target=[0,1.45,0];this.drag=null;this.last=performance.now();if(!this.locked)this.bind();requestAnimationFrame(t=>this.frame(t))}
 bind(){const c=this.c;c.addEventListener('pointerdown',e=>{this.drag=[e.clientX,e.clientY,this.yaw,this.pitch];c.setPointerCapture(e.pointerId)});c.addEventListener('pointermove',e=>{if(!this.drag)return;this.yaw=this.drag[2]-(e.clientX-this.drag[0])*.006;this.pitch=Math.max(.08,Math.min(1.05,this.drag[3]+(e.clientY-this.drag[1])*.005))});c.addEventListener('pointerup',()=>this.drag=null);c.addEventListener('pointercancel',()=>this.drag=null);c.addEventListener('wheel',e=>{e.preventDefault();this.radius=Math.max(7.7,Math.min(18,this.radius+e.deltaY*.009))},{passive:false})}
 reset(){this.yaw=-.66;this.pitch=.34;this.radius=12.6;this.target=[0,1.45,0]}
 setScenario(state,active=true){this.state=state||'normal';this.active=!!active;if(this.active&&this.rpm<5)this.rpm=1000}
 setDiagnosis(state){if(['normal','unbalance','misalignment','looseness'].includes(state))this.state=state}
 setTelemetry(r){if(!r)return;const rpm=Number(r.rpm);if(Number.isFinite(rpm))this.rpm=Math.max(0,rpm);if(r.source==='esp32'||r.source==='replay')this.active=this.rpm>5}
 resize(){const d=Math.min(devicePixelRatio||1,2),w=Math.max(1,Math.floor(this.c.clientWidth*d)),h=Math.max(1,Math.floor(this.c.clientHeight*d));if(this.c.width!==w||this.c.height!==h){this.c.width=w;this.c.height=h;this.gl.viewport(0,0,w,h)}}
 camera(){const cp=Math.cos(this.pitch),sp=Math.sin(this.pitch);const e=[this.target[0]+this.radius*cp*Math.sin(this.yaw),this.target[1]+this.radius*sp,this.target[2]+this.radius*cp*Math.cos(this.yaw)];return mul(perspective(Math.PI/4,this.c.width/this.c.height,.1,100),lookAt(e,this.target,[0,1,0]))}
 bindMesh(m){const gl=this.gl,ap=gl.getAttribLocation(this.p,'aPos'),an=gl.getAttribLocation(this.p,'aNormal');gl.bindBuffer(gl.ARRAY_BUFFER,m.p);gl.enableVertexAttribArray(ap);gl.vertexAttribPointer(ap,3,gl.FLOAT,false,0,0);gl.bindBuffer(gl.ARRAY_BUFFER,m.n);gl.enableVertexAttribArray(an);gl.vertexAttribPointer(an,3,gl.FLOAT,false,0,0)}
 draw(m,model,color,vp){const gl=this.gl;gl.useProgram(this.p);this.bindMesh(m);gl.uniformMatrix4fv(gl.getUniformLocation(this.p,'uModel'),false,model);gl.uniformMatrix4fv(gl.getUniformLocation(this.p,'uMVP'),false,mul(vp,model));gl.uniform4fv(gl.getUniformLocation(this.p,'uColor'),color);gl.drawArrays(gl.TRIANGLES,0,m.count)}
 box(pos,size,color=COLORS.wood,rot=[0,0,0],vp){this.draw(this.cube,compose(pos,rot,[size[0]/2,size[1]/2,size[2]/2]),color,vp)}
 cylx(pos,len,rad,color=COLORS.steel,rotX=0,vp){const m=compose(pos,[rotX,0,-Math.PI/2],[rad,len/2,rad]);this.draw(this.cyl,m,color,vp)}
 cyly(pos,len,rad,color=COLORS.steel,vp){this.draw(this.cyl,compose(pos,[0,0,0],[rad,len/2,rad]),color,vp)}
 line(points,color,vp,closed=false){const gl=this.gl,arr=[];for(const q of points)arr.push(...q);if(closed)arr.push(...points[0]);const b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(arr),gl.STREAM_DRAW);gl.useProgram(this.lp);const ap=gl.getAttribLocation(this.lp,'aPos');gl.enableVertexAttribArray(ap);gl.vertexAttribPointer(ap,3,gl.FLOAT,false,0,0);gl.uniformMatrix4fv(gl.getUniformLocation(this.lp,'uMVP'),false,vp);gl.uniform4fv(gl.getUniformLocation(this.lp,'uColor'),color);gl.drawArrays(closed?gl.LINE_STRIP:gl.LINE_STRIP,0,arr.length/3);gl.deleteBuffer(b)}
 grid(vp){for(let x=-7;x<=7;x+=.5)this.line([[x,-.28,-4.5],[x,-.28,4.5]],[.12,.22,.29,.22],vp);for(let z=-4.5;z<=4.5;z+=.5)this.line([[-7,-.28,z],[7,-.28,z]],[.12,.22,.29,.22],vp)}
 scene(vp,t){const state=this.state;let vibY=0,vibZ=0,wob=0,jitter=0,misalign=0,looseLift=0;if(this.active){if(state==='normal'){vibY=.006*Math.sin(t*13);vibZ=.005*Math.cos(t*12)}else if(state==='unbalance'){vibY=.082*Math.sin(t*19);vibZ=.070*Math.cos(t*19);wob=.095*Math.sin(t*12)}else if(state==='misalignment'){vibY=.040*Math.sin(t*15);vibZ=.058*Math.sin(t*9);wob=.035*Math.sin(t*8);misalign=.075*Math.sin(t*8)}else if(state==='looseness'){vibY=.050*Math.sin(t*24);vibZ=.030*Math.sin(t*17);jitter=.075*Math.sin(t*28);looseLift=.055*(.5+.5*Math.sin(t*18))}}const spin=this.active&&this.rpm>5;const hallHz=Math.min(7,Math.max(2,this.rpm/180));const hallOn=spin&&((t*hallHz)%1)<.32;
 this.grid(vp);this.box([0,-.02,0],[10.6,.52,3.75],COLORS.woodLight,[0,0,0],vp);this.box([0,.27,0],[10.15,.09,3.4],COLORS.woodTop,[0,0,0],vp);
 this.box([-3.85,.93+jitter,0],[1.42,1.42,2.0],COLORS.wood,[0,0,0],vp);this.box([-3.85,1.67+jitter,0],[1.48,.08,2.05],COLORS.woodTop,[0,0,0],vp);
 this.box([1.35,.82,0],[1.7,1.2,2.05],COLORS.wood,[0,0,0],vp);this.box([1.35,1.48,0],[1.76,.11,2.10],COLORS.woodTop,[0,0,0],vp);this.box([1.35,.48,.12],[2.7,.28,1.6],COLORS.woodLight,[0,0,0],vp);
 this.box([4.15,.92,0],[1.65,1.42,2.0],COLORS.wood,[0,0,0],vp);this.box([4.15,1.67,0],[1.7,.08,2.05],COLORS.woodTop,[0,0,0],vp);
 const sy=2.18+vibY,sz=vibZ;
 this.cylx([0,sy,sz],8.45,.085,COLORS.steel2,0,vp);this.cylx([-3.55,sy,sz],.52,.32,COLORS.steel2,0,vp);this.cylx([-2.95,sy,sz],.40,.25,COLORS.steel,0,vp);this.cylx([-2.53,sy,sz],.38,.28,COLORS.steel2,this.angle,vp);
 this.cylx([2.65,sy,sz],.42,.24,COLORS.steel,0,vp);
 const diskX=-.62;this.cylx([diskX,sy,sz],.26,1.13,COLORS.steel,this.angle+wob,vp);this.cylx([diskX-.16,sy,sz],.12,.29,COLORS.steel2,0,vp);
 const ca=Math.cos(this.angle),sa=Math.sin(this.angle);this.box([diskX+.145,sy+ca*.68,sz+sa*.68],[.05,.82,.095],COLORS.yellow,[this.angle,0,0],vp);this.box([diskX+.155,sy-ca*.68,sz-sa*.68],[.045,.58,.085],COLORS.white,[this.angle+Math.PI,0,0],vp);
 if(state==='unbalance'&&spin){this.box([diskX+.19,sy+ca*.92,sz+sa*.92],[.16,.26,.20],COLORS.red,[this.angle,0,0],vp)}
 this.box([-3.25,1.98+jitter,.02],[.55,.57,.72],COLORS.dark,[0,0,0],vp);this.cylx([-3.25,sy+jitter,sz],.62,.36,COLORS.steel2,0,vp);this.cylx([-3.25,sy+jitter,sz],.66,.20,COLORS.black,0,vp);
 this.box([-3.12,1.70+jitter,.74],[.78,.055,.48],COLORS.pcb,[0,0,.04],vp);this.box([-3.02,1.75+jitter,.77],[.18,.07,.12],COLORS.pcb2,[0,0,0],vp);this.box([-3.34,1.75+jitter,.76],[.09,.09,.09],COLORS.black,[0,0,0],vp);
 this.box([-3.47,1.82+jitter,.80],[.11,.11,.11],hallOn?COLORS.greenOn:COLORS.greenOff,[0,0,0],vp);if(hallOn)this.box([-3.47,1.82+jitter,.84],[.17,.17,.025],[.22,1,.34,.42],[0,0,0],vp);
 if(state==='misalignment'&&spin){this.cylx([2.65,sy+misalign,sz-misalign*.7],.46,.27,COLORS.orange,this.angle,vp);this.box([2.86,sy+misalign,sz-misalign*.7],[.12,.42,.12],COLORS.orange,[this.angle,0,0],vp)}
 if(state==='looseness'&&spin){this.box([-4.18,1.72+jitter+looseLift,.74],[.13,.13,.13],COLORS.red,[0,0,0],vp);this.box([-3.63,1.72+jitter+looseLift*.65,.74],[.13,.13,.13],COLORS.red,[0,0,0],vp)}
 this.box([1.28,2.05,.0],[.22,1.05,1.22],COLORS.dark,[0,0,0],vp);this.box([1.10,2.14,.18],[.12,.78,.72],COLORS.pcb,[0,0,0],vp);this.box([1.04,2.36,.30],[.16,.18,.18],COLORS.pcb2,[0,0,0],vp);
 this.box([4.10,2.02,0],[1.35,.86,1.18],COLORS.dark,[0,0,0],vp);this.box([4.38,2.04,0],[.84,.78,1.05],[.16,.19,.21,1],[0,0,0],vp);this.cylx([3.49,2.15,0],.45,.39,COLORS.black,0,vp);this.cylx([3.24,2.15,0],.28,.23,COLORS.steel,0,vp);
 this.box([3.86,1.66,.55],[.52,.12,.18],COLORS.black,[0,0,0],vp);this.box([4.45,1.66,.55],[.52,.12,.18],COLORS.black,[0,0,0],vp);
 const wireSets=[
  [[-3.25,1.68,.84],[-3.55,1.25,1.05],[-3.15,.55,1.55],[-1.4,.22,1.76]],[[-3.08,1.68,.86],[-2.78,1.1,1.16],[-1.75,.37,1.64],[.4,.16,1.82]],
  [[1.15,2.0,.58],[1.28,1.55,.85],[1.36,.62,1.45],[2.1,.2,1.8]],[[1.28,2.15,.62],[1.52,1.35,1.0],[1.75,.38,1.6],[3.0,.16,1.95]],
  [[4.62,2.18,.48],[4.86,1.60,.76],[4.72,.55,1.52],[5.1,.15,1.88]]];
 const wc=[[.15,.46,.95,1],[.95,.47,.15,1],[.1,.75,.42,1],[.92,.78,.12,1],[.85,.12,.18,1]];wireSets.forEach((w,i)=>this.line(w,wc[i],vp));
 const low=[[-5.15,.04,-2.15],[5.3,.04,-2.15],[5.3,.04,2.25],[-5.15,.04,2.25]],high=[[-5.15,3.55,-2.15],[5.3,3.55,-2.15],[5.3,3.55,2.25],[-5.15,3.55,2.25]];this.line(low,[1,.12,.18,.72],vp,true);this.line(high,[1,.12,.18,.52],vp,true);for(let i=0;i<4;i++)this.line([low[i],high[i]],[1,.12,.18,.4],vp);
 }
 frame(now){if(!this.gl)return;this.resize();const dt=Math.min(.05,(now-this.last)/1000);this.last=now;if(this.active){const speed=Math.max(0,this.rpm)*2*Math.PI/60;this.angle=(this.angle+dt*speed)%(Math.PI*2)}const gl=this.gl;gl.enable(gl.DEPTH_TEST);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);gl.clearColor(.018,.045,.07,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);this.scene(this.camera(),now/1000);requestAnimationFrame(t=>this.frame(t))}
}
const twins=[];window.createNEXisTwin=(canvas,opt={})=>{if(typeof canvas==='string')canvas=document.querySelector(canvas);if(!canvas)return null;const t=new Twin(canvas,opt);twins.push(t);return t};window.NEXisTwin={instances:twins,resetAll:()=>twins.forEach(t=>t.reset())};
})();
