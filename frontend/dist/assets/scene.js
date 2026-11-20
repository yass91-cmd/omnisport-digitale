// Small perspective renderer: all geometry is original and requires no CDN/assets.
const TAU = Math.PI * 2;
const length = vector => Math.hypot(...vector);
const normalize = vector => vector.map(value => value / length(vector));
const dot = (a, b) => a.reduce((sum, value, i) => sum + value * b[i], 0);
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

function footballGeometry() {
  const p = (1 + Math.sqrt(5)) / 2;
  const vertices = [];
  for (const a of [-1, 1]) for (const b of [-p, p]) {
    vertices.push([0, a, b], [a, b, 0], [b, 0, a]);
  }
  const neighbours = vertices.map((v, i) => vertices.flatMap((w, j) =>
    i !== j && Math.abs(Math.hypot(...v.map((x, k) => x - w[k])) - 2) < .01 ? [j] : []));
  const points = new Map();
  neighbours.forEach((list, i) => list.forEach(j => points.set(`${i}:${j}`, vertices[i].map((v, k) => (2 * v + vertices[j][k]) / 3))));
  const radius = length(points.values().next().value);
  for (const [key, point] of points) points.set(key, point.map(v => v / radius));
  const faces = [];
  vertices.forEach((v, i) => {
    const normal = normalize(v);
    const u = normalize(cross(normal, Math.abs(normal[1]) < .9 ? [0, 1, 0] : [1, 0, 0]));
    const w = cross(normal, u);
    const ring = neighbours[i].map(j => points.get(`${i}:${j}`));
    ring.sort((a, b) => Math.atan2(dot(a, w), dot(a, u)) - Math.atan2(dot(b, w), dot(b, u)));
    faces.push({ points: ring, dark: true });
  });
  for (let i = 0; i < vertices.length; i++) for (const j of neighbours[i]) for (const k of neighbours[i]) {
    if (i < j && j < k && neighbours[j].includes(k)) {
      faces.push({ points: [[i,j],[j,i],[j,k],[k,j],[k,i],[i,k]].map(([a,b]) => points.get(`${a}:${b}`)), dark: false });
    }
  }
  return faces;
}

const footballFaces = footballGeometry();

function rotate([x, y, z], rx, ry, rz = 0) {
  const a = y * Math.cos(rx) - z * Math.sin(rx);
  const b = y * Math.sin(rx) + z * Math.cos(rx);
  const c = x * Math.cos(ry) + b * Math.sin(ry);
  const d = -x * Math.sin(ry) + b * Math.cos(ry);
  return [c * Math.cos(rz) - a * Math.sin(rz), c * Math.sin(rz) + a * Math.cos(rz), d];
}

export function createSportsScene(canvas, initiallyPaused = false) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return { setSport() {}, setPaused() {} };
  let width = 0, height = 0, frame = 0, last = 0, time = .7;
  let sport = "football", paused = initiallyPaused;
  const pointer = { x: 0, y: 0, smoothX: 0, smoothY: 0 };
  const accent = () => sport === "basketball" ? "255,186,128" : sport === "tennis" ? "225,237,130" : "196,243,107";
  const request = () => { if (!frame && !document.hidden) frame = requestAnimationFrame(render); };
  const resize = () => {
    const rect = canvas.getBoundingClientRect();
    width = rect.width; height = rect.height;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    request();
  };
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);

  function path(points, close = false) {
    ctx.beginPath();
    points.forEach(([x,y], i) => i ? ctx.lineTo(x,y) : ctx.moveTo(x,y));
    if (close) ctx.closePath();
  }

  function court(cx, cy, size) {
    const project = (x,z) => [cx + x * size * (.52 + z * .47), cy + (z - .5) * size * .56];
    const line = (points, opacity = .25, lw = 1) => {
      path(points.map(([x,z]) => project(x,z)));
      ctx.strokeStyle = `rgba(${accent()},${opacity})`; ctx.lineWidth = lw; ctx.stroke();
    };
    const rect = (x1,z1,x2,z2,a) => line([[x1,z1],[x2,z1],[x2,z2],[x1,z2],[x1,z1]],a);
    rect(-1.5,0,1.5,1,.32);
    rect(-1.65,-.08,1.65,1.08,.06);
    if (sport === "football") {
      line([[0,0],[0,1]],.25);
      rect(-1.5,.25,-1.06,.75,.22); rect(1.06,.25,1.5,.75,.22);
      const ring = Array.from({length:65}, (_,i) => [Math.cos(i/64*TAU)*.32, .5+Math.sin(i/64*TAU)*.19]);
      line(ring,.24);
    } else if (sport === "basketball") {
      line([[0,0],[0,1]],.22);
      rect(-1.5,.33,-.98,.67,.3); rect(.98,.33,1.5,.67,.3);
      line(Array.from({length:65}, (_,i) => [Math.cos(i/64*TAU)*.3, .5+Math.sin(i/64*TAU)*.21]),.28);
      for (const side of [-1,1]) line(Array.from({length:33}, (_,i) => [side*(1.5-Math.sin(i/32*Math.PI)*.8), .13+i/32*.74]),.2);
    } else {
      line([[-1.5,.13],[1.5,.13]],.24); line([[-1.5,.87],[1.5,.87]],.24);
      line([[0,.13],[0,.87]],.27); line([[-.7,.13],[-.7,.87]],.23); line([[.7,.13],[.7,.87]],.23);
      const left=project(0,0),right=project(0,1);
      for(let i=0;i<=12;i++){
        const x=left[0]+(right[0]-left[0])*i/12,y=left[1]+(right[1]-left[1])*i/12;
        path([[x,y],[x,y-size*.19]]);ctx.strokeStyle=`rgba(${accent()},.15)`;ctx.lineWidth=.6;ctx.stroke();
      }
      path([[left[0],left[1]-size*.19],[right[0],right[1]-size*.19]]);ctx.strokeStyle=`rgba(${accent()},.4)`;ctx.stroke();
    }
  }

  function football(cx,cy,r,t) {
    const rx = -.15 + pointer.smoothY*.1, ry = t*.12 + pointer.smoothX*.1;
    const faces = footballFaces.map(face => {
      const points = face.points.map(p => rotate(p,rx,ry,-.13));
      const center = points[0].map((_,i) => points.reduce((sum,p) => sum+p[i],0)/points.length);
      return {...face, points, center};
    }).sort((a,b)=>a.center[2]-b.center[2]);
    const light=normalize([-.5,-.65,1]);
    faces.forEach(face => {
      const brightness=.43+.57*Math.max(0,dot(normalize(face.center),light));
      const base=face.dark?[32,42,25]:[233,241,220];
      path(face.points.map(([x,y,z])=>[cx+x*r*3.7/(3.7-z),cy+y*r*3.7/(3.7-z)]),true);
      ctx.fillStyle=`rgb(${base.map(c=>Math.round(c*brightness)).join(",")})`;ctx.fill();
      ctx.strokeStyle="rgba(27,37,20,.85)";ctx.lineWidth=Math.max(.8,r/140);ctx.lineJoin="round";ctx.stroke();
    });
  }

  function sphere(cx,cy,r,colors) {
    const gradient=ctx.createRadialGradient(cx-r*.4,cy-r*.45,r*.05,cx+r*.18,cy+r*.2,r*1.14);
    gradient.addColorStop(0,colors[0]);gradient.addColorStop(.48,colors[1]);gradient.addColorStop(1,colors[2]);
    ctx.beginPath();ctx.arc(cx,cy,r,0,TAU);ctx.fillStyle=gradient;ctx.fill();
    ctx.save();ctx.beginPath();ctx.arc(cx,cy,r-1,0,TAU);ctx.clip();
  }

  function sphereLine(points,cx,cy,r,rx,ry,color,width) {
    let drawing=false;
    ctx.beginPath();
    points.forEach(point=>{
      const [x,y,z]=rotate(point,rx,ry,-.32);
      if(z<-.025){drawing=false;return;}
      const sx=cx+x*r,sy=cy+y*r;
      if(drawing)ctx.lineTo(sx,sy);else ctx.moveTo(sx,sy);
      drawing=true;
    });
    ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();
  }

  function basketball(cx,cy,r,t) {
    sphere(cx,cy,r,["#f6b65c","#c76a25","#412210"]);
    ctx.fillStyle="rgba(25,16,8,.13)";
    for(let i=0;i<2100;i++){
      const a=i*2.39996,rr=Math.sqrt((i+.5)/2100)*r;
      ctx.beginPath();ctx.arc(cx+Math.cos(a)*rr,cy+Math.sin(a)*rr,.75,0,TAU);ctx.fill();
    }
    const rx=.4,ry=t*.11;
    for(const offset of [0,Math.PI/2,Math.PI/4,-Math.PI/4]){
      const points=Array.from({length:181},(_,i)=>{
        const a=i/180*TAU;
        return rotate([Math.cos(a),Math.sin(a),0],0,offset);
      });
      sphereLine(points,cx,cy,r,rx,ry,"#372515",r*.022);
    }
    ctx.restore();
  }

  function tennis(cx,cy,r,t) {
    sphere(cx,cy,r,["#f0f6aa","#c2d953","#4e601f"]);
    ctx.fillStyle="rgba(246,255,192,.25)";
    for(let i=0;i<1500;i++){
      const a=i*2.39996,rr=Math.sqrt((i+.5)/1500)*r;
      ctx.fillRect(cx+Math.cos(a)*rr,cy+Math.sin(a)*rr,1.3,.6);
    }
    const seam=Array.from({length:401},(_,i)=>{
      const a=i/400*TAU,z=.58*Math.cos(2*a),d=Math.sqrt(1-z*z);
      return [Math.cos(a)*d,Math.sin(a)*d,z];
    });
    sphereLine(seam,cx,cy,r,.6,t*.12,"rgba(74,91,29,.6)",r*.065);
    sphereLine(seam,cx,cy,r,.6,t*.12,"#f4f5d5",r*.042);
    ctx.restore();
  }

  function render(now) {
    frame=0;
    const delta=last?Math.min((now-last)/1000,.045):0;
    last=now;if(!paused)time+=delta;
    pointer.smoothX+=(pointer.x-pointer.smoothX)*.035;
    pointer.smoothY+=(pointer.y-pointer.smoothY)*.035;
    ctx.clearRect(0,0,width,height);
    const mobile=width<=700&&window.innerHeight>600;
    const compact=width<=700&&!mobile;
    const cx=width*(mobile?.62:compact?.8:.752)+pointer.smoothX*9;
    const cy=height*(mobile?.215:compact?.39:.445)+Math.sin(time*.8)*8+pointer.smoothY*6;
    const r=mobile?Math.min(width*.245,height*.135):compact?Math.min(width*.18,height*.18):Math.min(width*.165,height*.235);
    const floorY=height*(mobile?.36:compact?.69:.77);
    const glow=ctx.createRadialGradient(cx,cy,0,cx,cy,r*2.1);
    glow.addColorStop(0,`rgba(${accent()},.06)`);glow.addColorStop(1,`rgba(${accent()},0)`);
    ctx.fillStyle=glow;ctx.fillRect(cx-r*2.1,cy-r*2.1,r*4.2,r*4.2);
    for(let i=0;i<24;i++){
      const x=cx+Math.sin(i*47.1)*r*2.1,y=height*.12+((i*67.3)%Math.max(height*.68,1));
      ctx.beginPath();ctx.arc(x,y+Math.sin(time*.25+i)*5,i%3===0?1.2:.7,0,TAU);ctx.fillStyle=`rgba(${accent()},${i%4===0?.3:.12})`;ctx.fill();
    }
    ctx.save();ctx.translate(cx,floorY);ctx.scale(1,.17);
    const shadow=ctx.createRadialGradient(0,0,0,0,0,r*1.1);
    shadow.addColorStop(0,"rgba(0,0,0,.75)");shadow.addColorStop(1,"rgba(0,0,0,0)");
    ctx.fillStyle=shadow;ctx.beginPath();ctx.arc(0,0,r*1.1,0,TAU);ctx.fill();ctx.restore();
    court(cx,floorY,r*(mobile?1.05:1.12));
    if(sport==="football")football(cx,cy,r,time);
    else if(sport==="basketball")basketball(cx,cy,r,time);
    else tennis(cx,cy,r,time);
    if(!paused&&!document.hidden)request();
  }

  window.addEventListener("pointermove",event=>{
    if(paused||event.pointerType!=="mouse")return;
    pointer.x=(event.clientX/window.innerWidth-.5)*2;
    pointer.y=(event.clientY/window.innerHeight-.5)*2;
  },{passive:true});
  document.addEventListener("visibilitychange",()=>{
    if(document.hidden){cancelAnimationFrame(frame);frame=0;last=0;}
    else request();
  });
  resize();
  return {
    setSport(value){sport=value;request();},
    setPaused(value){paused=value;last=0;cancelAnimationFrame(frame);frame=0;request();},
  };
}
