# ── Frogger — standalone game ────────────────────────────────────────────────
#
# Run standalone:   python frogger.py
# Then open:        http://localhost:5001/
#
# Also used by CineVault (media_library.py imports FROGGER_HTML and serves it
# at /frogger, which is loaded in an iframe when the Konami code is entered).
# The game sends  window.parent.postMessage('frogger:exit', '*')  when the
# player exits, so CineVault can tear down the iframe overlay.
# ---------------------------------------------------------------------------

FROGGER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Frogger</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:100%;height:100%;overflow:hidden;background:#040410}
body{display:flex;flex-direction:column;align-items:center;justify-content:center;
     font-family:"Courier New",monospace;min-height:100vh}
#arcade-label{color:#44dd88;font-size:.72rem;letter-spacing:.22em;margin-bottom:8px;
              opacity:.55;text-align:center;user-select:none}
#game-canvas{border:2px solid #2a8a5a;
             box-shadow:0 0 50px rgba(0,255,136,.18),0 0 100px rgba(0,200,100,.06);
             image-rendering:pixelated;display:block}
#close-btn{margin-top:12px;padding:7px 22px;background:transparent;
           border:2px solid #2a8a5a;color:#44dd88;
           font-family:"Courier New",monospace;font-size:.8rem;font-weight:700;
           letter-spacing:.14em;cursor:pointer;border-radius:4px;
           transition:background .18s,color .18s}
#close-btn:hover{background:#44dd88;color:#000}
#info-txt{color:#333355;font-size:.68rem;letter-spacing:.1em;
          margin-top:8px;text-align:center;user-select:none}
</style>
</head>
<body>
<div id="arcade-label">&#x2191; &#x2191; &#x2193; &#x2193; &#x2190; &#x2192; &#x2190; &#x2192; &nbsp;&middot;&nbsp; SECRET ARCADE &nbsp;&middot;&nbsp; &#x2191; &#x2191; &#x2193; &#x2193; &#x2190; &#x2192; &#x2190; &#x2192;</div>
<canvas id="game-canvas"></canvas>
<button id="close-btn" onclick="closeGame()">&#x2715;&nbsp; EXIT ARCADE &nbsp;[ESC]</button>
<div id="info-txt">ARROW KEYS / WASD &nbsp;&middot;&nbsp; R = RESTART &nbsp;&middot;&nbsp; ESC = EXIT</div>

<script>
// ── Constants ────────────────────────────────────────────────────────────────
const CELL=44,COLS=13,ROWS=13,HH=56;
const CW=COLS*CELL,CH=ROWS*CELL+HH;
const HOME_COLS=[1,3,5,7,9];

// ── Canvas setup ─────────────────────────────────────────────────────────────
const canvas=document.getElementById('game-canvas');
canvas.width=CW;canvas.height=CH;
function applyScale(){
  const scl=Math.min(1,(innerWidth-28)/CW,(innerHeight-120)/CH);
  canvas.style.width=Math.round(CW*scl)+'px';
  canvas.style.height=Math.round(CH*scl)+'px';
}
applyScale();
window.addEventListener('resize',applyScale);
const ctx=canvas.getContext('2d');

// ── Audio (Web Audio API, no external files) ─────────────────────────────────
let _ac=null;
function getAC(){if(!_ac)_ac=new(window.AudioContext||window.webkitAudioContext)();return _ac;}
function tone(freq,dur,type,vol,t0){
  try{const a=getAC(),o=a.createOscillator(),g=a.createGain();
  o.connect(g);g.connect(a.destination);o.type=type||'square';o.frequency.value=freq;
  const st=a.currentTime+(t0||0);g.gain.setValueAtTime(vol||0.1,st);
  g.gain.exponentialRampToValueAtTime(0.001,st+dur);o.start(st);o.stop(st+dur+0.02);}catch(_e){}
}
const SFX={
  hop:   ()=>tone(480,0.05,'square',0.1),
  splash:()=>{tone(280,0.07,'sine',0.16);tone(180,0.12,'sine',0.1,0.04);},
  squash:()=>{[210,160,110].forEach((f,i)=>tone(f,0.12,'sawtooth',0.14,i*0.06));},
  home:  ()=>{[523,659,784,1047].forEach((f,i)=>tone(f,0.10,'square',0.15,i*0.09));},
  level: ()=>{[523,659,784,1047,1318].forEach((f,i)=>tone(f,0.14,'square',0.18,i*0.08));},
  over:  ()=>{[440,349,294,220,175].forEach((f,i)=>tone(f,0.18,'sawtooth',0.13,i*0.12));}
};

// ── Difficulty ────────────────────────────────────────────────────────────────
// 0=Easy  1=Medium  2=Hard
let difficulty=1,selDiff=1;
const DIFF_LABEL=['EASY','MEDIUM','HARD'];
const DIFF_EMOJI=['\u{1F7E2}','\u{1F7E1}','\u{1F534}'];
const DIFF_DESC =['Slow traffic \u00b7 wide logs \u00b7 5 lives',
                  'Moderate speed \u00b7 standard logs \u00b7 3 lives',
                  'Fast & unforgiving \u00b7 3 lives'];
const DIFF_SPD  =[0.50,0.74,1.00];
const DIFF_SCL  =[0.12,0.17,0.22];
const DIFF_LIVES=[5,3,3];

// ── Row layout: 0=start(bottom) … 12=home(top) ───────────────────────────────
function buildRows(lv){
  const m=DIFF_SPD[difficulty];
  const sc=DIFF_SCL[difficulty];
  const s=m*(1+(lv-1)*sc);
  return [
    {type:'safe', bg:'#2a5216'},
    {type:'road', bg:'#242424',dir: 1,spd:2.0*s},
    {type:'road', bg:'#2e2e2e',dir:-1,spd:2.5*s},
    {type:'road', bg:'#242424',dir: 1,spd:1.7*s},
    {type:'road', bg:'#2e2e2e',dir:-1,spd:3.0*s},
    {type:'road', bg:'#242424',dir: 1,spd:2.2*s},
    {type:'safe', bg:'#2a5216'},
    {type:'water',bg:'#1a3e7a',dir: 1,spd:1.3*s},
    {type:'water',bg:'#163569',dir:-1,spd:1.7*s},
    {type:'water',bg:'#1a3e7a',dir: 1,spd:1.0*s},
    {type:'water',bg:'#163569',dir:-1,spd:2.0*s},
    {type:'water',bg:'#1a3e7a',dir: 1,spd:1.5*s},
    {type:'home', bg:'#0d1f07'},
  ];
}

// Vehicle configs per difficulty: [count,widthCells,color,darkColor]
const VCFG_D=[
  // Easy
  [null,[2,2,'#e53e3e','#9b2626'],[1,4,'#e8821a','#a35812'],
        [3,2,'#3b82f6','#1e40af'],[2,2,'#a855f7','#6b21a8'],[1,4,'#ef4444','#991b1b']],
  // Medium & Hard
  [null,[3,2,'#e53e3e','#9b2626'],[2,4,'#e8821a','#a35812'],
        [4,2,'#3b82f6','#1e40af'],[3,2,'#a855f7','#6b21a8'],[2,4,'#ef4444','#991b1b']],
];
// Log configs per difficulty: [count,widthCells]
const LCFG_D=[
  // Easy: wider logs
  [null,null,null,null,null,null,null,[3,4],[2,5],[2,6],[3,4],[2,5]],
  // Medium & Hard: standard
  [null,null,null,null,null,null,null,[3,3],[2,4],[2,5],[3,3],[2,4]],
];

function vcfg(){return difficulty===0?VCFG_D[0]:VCFG_D[1];}
function lcfg(){return difficulty===0?LCFG_D[0]:LCFG_D[1];}

function spawnVehicles(ri){
  const[cnt,wc,col,dark]=vcfg()[ri];const w=wc*CELL,sp=CW/cnt;
  return Array.from({length:cnt},(_,i)=>({x:i*sp+Math.random()*Math.max(0,sp-w-8),w,col,dark}));
}
function spawnLogs(ri){
  const[cnt,wc]=lcfg()[ri];const w=wc*CELL,sp=CW/cnt;
  return Array.from({length:cnt},(_,i)=>({x:i*sp+Math.random()*Math.max(0,sp-w-8),w}));
}

// ── Game state ────────────────────────────────────────────────────────────────
let rows,objs,frog,lives,score,level,homes,phase,phaseTimer,hiScore=0;

// ── Leaderboard (persisted in localStorage) ───────────────────────────────────
let leaderboard=JSON.parse(localStorage.getItem('frogger_lb')||'[]');
let _initials=['A','A','A'],_initCursor=0,_newEntryRank=-1;
const ALPHA='ABCDEFGHIJKLMNOPQRSTUVWXYZ '.split('');
const LB_MAX=5;
function qualifies(s){return s>0&&(leaderboard.length<LB_MAX||s>leaderboard[leaderboard.length-1].score);}
function saveLBEntry(){
  const entry={name:_initials.join(''),score,level,diff:DIFF_LABEL[difficulty]};
  leaderboard.push(entry);leaderboard.sort((a,b)=>b.score-a.score);
  if(leaderboard.length>LB_MAX)leaderboard.length=LB_MAX;
  _newEntryRank=leaderboard.indexOf(entry);
  if(score>hiScore)hiScore=score;
  localStorage.setItem('frogger_lb',JSON.stringify(leaderboard));
}

// ── Game functions ────────────────────────────────────────────────────────────
function initGame(){
  difficulty=selDiff;
  lives=DIFF_LIVES[difficulty];score=0;level=1;homes=Array(5).fill(false);
  phase='playing';phaseTimer=0;buildLevel();resetFrog();
}
function showSelect(){phase='select';}
function buildLevel(){
  rows=buildRows(level);objs={};
  for(let r=1;r<=11;r++){
    if(rows[r].type==='road')objs[r]=spawnVehicles(r);
    else if(rows[r].type==='water')objs[r]=spawnLogs(r);
  }
}
function resetFrog(){frog={px:Math.floor(COLS/2)*CELL,row:0,facing:'up'};}
function rowY(r){return HH+(ROWS-1-r)*CELL;}

// ── Input ─────────────────────────────────────────────────────────────────────
let lastMove=0;
function onKey(e){
  const DIRS={ArrowUp:[1,0,'up'],ArrowDown:[-1,0,'down'],ArrowLeft:[0,-1,'left'],ArrowRight:[0,1,'right'],
              w:[1,0,'up'],s:[-1,0,'down'],a:[0,-1,'left'],d:[0,1,'right'],
              W:[1,0,'up'],S:[-1,0,'down'],A:[0,-1,'left'],D:[0,1,'right']};
  if(e.key==='Escape'){
    if(phase==='select')closeGame();
    else{showSelect();return;}
  }
  if(phase==='select'){
    if(['ArrowLeft','a','A'].includes(e.key)){e.preventDefault();selDiff=Math.max(0,selDiff-1);tone(300,0.04,'square',0.08);}
    if(['ArrowRight','d','D'].includes(e.key)){e.preventDefault();selDiff=Math.min(2,selDiff+1);tone(400,0.04,'square',0.08);}
    if(e.key==='Enter'||e.key===' '){e.preventDefault();initGame();}
    return;
  }
  if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key))e.preventDefault();
  if(phase==='gameover'){
    if(['r','R','Enter',' '].includes(e.key)){phaseTimer=0;}
    return;
  }
  if(phase==='initials'){
    e.preventDefault();
    if(e.key==='ArrowUp'||e.key==='ArrowDown'){
      const d=e.key==='ArrowUp'?1:-1;
      const ci=ALPHA.indexOf(_initials[_initCursor]);
      _initials[_initCursor]=ALPHA[(ci+d+ALPHA.length)%ALPHA.length];
      tone(e.key==='ArrowUp'?420:360,0.04,'square',0.08);
    } else if(e.key==='ArrowLeft'&&_initCursor>0){
      _initCursor--;
    } else if(e.key==='ArrowRight'||e.key==='Tab'){
      if(_initCursor<2){_initCursor++;tone(460,0.05,'square',0.1);}
      else{saveLBEntry();phase='leaderboard';}
    } else if(e.key==='Enter'||e.key===' '){
      if(_initCursor<2){_initCursor++;tone(460,0.05,'square',0.1);}
      else{saveLBEntry();[523,659,784].forEach((f,i)=>tone(f,0.1,'square',0.15,i*0.08));phase='leaderboard';}
    } else if(e.key==='Backspace'&&_initCursor>0){
      _initCursor--;_initials[_initCursor]='A';
    } else if(e.key.length===1&&/[A-Za-z]/.test(e.key)){
      _initials[_initCursor]=e.key.toUpperCase();
      tone(460,0.04,'square',0.1);
      if(_initCursor<2){_initCursor++;}
      else{saveLBEntry();[523,659,784].forEach((f,i)=>tone(f,0.1,'square',0.15,i*0.08));phase='leaderboard';}
    }
    return;
  }
  if(phase==='leaderboard'){
    if(['Enter',' ','r','R'].includes(e.key)){e.preventDefault();showSelect();}
    return;
  }
  if(phase!=='playing')return;
  const d=DIRS[e.key];if(!d)return;
  const now=Date.now();if(now-lastMove<110)return;lastMove=now;
  const[dr,dc,face]=d;
  const nr=frog.row+dr,npx=frog.px+dc*CELL;
  if(nr<0||nr>=ROWS||npx<0||npx+CELL>CW)return;
  frog.row=nr;frog.px=npx;frog.facing=face;
  SFX.hop();if(dr>0)score+=10;
  if(rows[frog.row]&&rows[frog.row].type==='water'&&!isOnLog()){SFX.splash();loseLife();}
  else if(frog.row===ROWS-1)checkHome();
}
document.addEventListener('keydown',onKey);

function isOnLog(){
  const r=rows[frog.row];if(!r||r.type!=='water')return false;
  const fc=frog.px+CELL/2;
  return(objs[frog.row]||[]).some(o=>fc>o.x+3&&fc<o.x+o.w-3);
}
function loseLife(){if(phase!=='playing')return;lives--;phase='dying';phaseTimer=1.0;}
function checkHome(){
  const col=Math.round(frog.px/CELL);frog.px=col*CELL;
  const hi=HOME_COLS.indexOf(col);
  if(hi>=0&&!homes[hi]){
    homes[hi]=true;score+=100+50*(level-1);SFX.home();resetFrog();
    if(homes.every(Boolean)){
      score+=500;if(score>hiScore)hiScore=score;
      SFX.level();phase='levelup';phaseTimer=2.8;
    }
  }else{SFX.splash();loseLife();}
}

// ── Update ────────────────────────────────────────────────────────────────────
let waterT=0;
function update(dt){
  waterT+=dt;
  if(phase==='select')return;
  if(phase==='dying'){
    phaseTimer-=dt;
    if(phaseTimer<=0){
      if(lives<=0){
        SFX.over();phase='gameover';phaseTimer=2.5;
        _initials=['A','A','A'];_initCursor=0;_newEntryRank=-1;
      }else{phase='playing';resetFrog();}
    }
    return;
  }
  if(phase==='levelup'){
    phaseTimer-=dt;
    if(phaseTimer<=0){level++;homes=Array(5).fill(false);buildLevel();resetFrog();phase='playing';}
    return;
  }
  if(phase==='gameover'){
    phaseTimer-=dt;
    if(phaseTimer<=0){
      if(qualifies(score)){phase='initials';}
      else{phase='leaderboard';}
    }
    return;
  }
  if(phase==='initials'||phase==='leaderboard')return;
  if(phase!=='playing')return;
  for(let r=1;r<=11;r++){
    const row=rows[r];if(!row)continue;
    (objs[r]||[]).forEach(o=>{
      o.x+=row.dir*row.spd;
      if(row.dir===1&&o.x>CW+20)o.x=-o.w-20;
      if(row.dir===-1&&o.x<-o.w-20)o.x=CW+20;
    });
  }
  const crow=rows[frog.row];
  if(crow&&crow.type==='water'){
    frog.px+=crow.dir*crow.spd;
    if(frog.px<-CELL*0.6||frog.px>=CW){SFX.splash();loseLife();return;}
    if(!isOnLog()){SFX.splash();loseLife();return;}
  }
  if(crow&&crow.type==='road'){
    const fl=frog.px+7,fr2=frog.px+CELL-7;
    if((objs[frog.row]||[]).some(o=>fr2>o.x+5&&fl<o.x+o.w-5)){SFX.squash();loseLife();}
  }
}

// ── Drawing ───────────────────────────────────────────────────────────────────
function rrect(x,y,w,h,rad){
  ctx.beginPath();ctx.moveTo(x+rad,y);ctx.lineTo(x+w-rad,y);
  ctx.quadraticCurveTo(x+w,y,x+w,y+rad);ctx.lineTo(x+w,y+h-rad);
  ctx.quadraticCurveTo(x+w,y+h,x+w-rad,y+h);ctx.lineTo(x+rad,y+h);
  ctx.quadraticCurveTo(x,y+h,x,y+h-rad);ctx.lineTo(x,y+rad);
  ctx.quadraticCurveTo(x,y,x+rad,y);ctx.closePath();
}
function drawGrass(y){
  ctx.fillStyle='#214710';
  for(let x=6;x<CW;x+=20){ctx.fillRect(x,y+7,11,8);ctx.fillRect(x+10,y+25,8,6);}
  ctx.fillStyle='#1c3d0c';ctx.fillRect(0,y,CW,3);ctx.fillRect(0,y+CELL-3,CW,3);
}
function drawHomeRow(y){
  ctx.fillStyle='#0c1d06';ctx.fillRect(0,y,CW,CELL);
  for(let x=0;x<CW;x+=10){
    ctx.fillStyle=x%20<10?'#173808':'#1a4a0a';
    ctx.fillRect(x,y,10,10+Math.abs(Math.sin(x*0.3))*8);
  }
  ctx.fillStyle='#1a3e7a';ctx.fillRect(0,y+3,CW,CELL-6);
  ctx.strokeStyle='rgba(80,150,255,.15)';ctx.lineWidth=1;ctx.setLineDash([8,14]);
  ctx.beginPath();ctx.moveTo(0,y+13);ctx.lineTo(CW,y+13);ctx.stroke();
  ctx.beginPath();ctx.moveTo(0,y+29);ctx.lineTo(CW,y+29);ctx.stroke();
  ctx.setLineDash([]);
  HOME_COLS.forEach((hc,i)=>{
    const hx=hc*CELL;
    ctx.fillStyle=homes[i]?'#1a5c1a':'#0e280a';ctx.fillRect(hx+1,y+1,CELL-2,CELL-2);
    ctx.fillStyle=homes[i]?'#29c764':'#1a4a1a';
    ctx.beginPath();ctx.arc(hx+CELL/2,y+CELL/2,CELL/2-5,0,Math.PI*2);ctx.fill();
    ctx.fillStyle=homes[i]?'#1a5c1a':'#0e280a';
    ctx.beginPath();ctx.moveTo(hx+CELL/2,y+CELL/2);
    ctx.lineTo(hx+CELL/2-8,y+5);ctx.lineTo(hx+CELL/2+8,y+5);ctx.closePath();ctx.fill();
    if(!homes[i]){ctx.fillStyle='#ffcc00';ctx.beginPath();ctx.arc(hx+CELL/2,y+CELL/2,4,0,Math.PI*2);ctx.fill();}
    if(homes[i])drawFrogMini(hx+CELL/2-11,y+CELL/2-11,22);
  });
}
function drawRoad(r,y){
  ctx.strokeStyle='rgba(255,255,180,.09)';ctx.setLineDash([16,14]);ctx.lineWidth=1.5;
  ctx.beginPath();ctx.moveTo(0,y+CELL/2);ctx.lineTo(CW,y+CELL/2);ctx.stroke();
  ctx.setLineDash([]);ctx.strokeStyle='rgba(255,255,180,.18)';ctx.lineWidth=1.5;
  ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(CW,y);ctx.stroke();
  (objs[r]||[]).forEach(v=>drawVehicle(v,y,rows[r].dir));
}
function drawVehicle(v,y,dir){
  const vy=y+5,vh=CELL-10,isLng=v.w>=3*CELL;
  ctx.fillStyle='rgba(0,0,0,.35)';ctx.fillRect(v.x+4,vy+vh-1,v.w-4,4);
  ctx.fillStyle=v.col;rrect(v.x+2,vy,v.w-4,vh,5);ctx.fill();
  const cabW=isLng?v.w*0.3:v.w*0.52;
  const cabX=dir===1?v.x+v.w-cabW-4:v.x+4;
  ctx.fillStyle=v.dark;rrect(cabX,vy+3,cabW,vh-6,3);ctx.fill();
  ctx.fillStyle='rgba(200,230,255,.25)';ctx.fillRect(cabX+3,vy+5,cabW-6,4);
  ctx.fillStyle='#fffaaa';
  const hlx=dir===1?v.x+v.w-8:v.x+3;
  ctx.fillRect(hlx,vy+5,4,5);ctx.fillRect(hlx,vy+vh-10,4,5);
  ctx.fillStyle='#cc2222';
  const tlx=dir===1?v.x+3:v.x+v.w-8;
  ctx.fillRect(tlx,vy+5,3,5);ctx.fillRect(tlx,vy+vh-10,3,5);
}
function drawWater(r,y){
  const row=rows[r];
  for(let wx=0;wx<CW+60;wx+=60){
    const rx=((wx+waterT*row.spd*row.dir*14)%(CW+80))-40;
    ctx.strokeStyle='rgba(100,170,255,.12)';ctx.lineWidth=1.5;ctx.setLineDash([7,18]);
    ctx.beginPath();
    for(let tx=0;tx<CW+80;tx+=3)ctx.lineTo(rx+tx,y+12+Math.sin((tx*0.12)+waterT*2.2)*2);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  (objs[r]||[]).forEach(log=>drawLog(log,y));
}
function drawLog(log,y){
  const lh=CELL-8,ly=y+4;
  ctx.fillStyle='rgba(0,0,0,.28)';ctx.fillRect(log.x+2,ly+lh,log.w-2,4);
  ctx.fillStyle='#7a4a1a';rrect(log.x,ly,log.w,lh,7);ctx.fill();
  ctx.strokeStyle='#5a3210';ctx.lineWidth=1.5;
  for(let gx=log.x+20;gx<log.x+log.w-12;gx+=14){
    ctx.beginPath();ctx.moveTo(gx,ly+3);ctx.lineTo(gx,ly+lh-3);ctx.stroke();
  }
  ctx.fillStyle='#9a6030';
  ctx.beginPath();ctx.ellipse(log.x+10,ly+lh/2,9,lh/2-3,0,0,Math.PI*2);ctx.fill();
  ctx.beginPath();ctx.ellipse(log.x+log.w-10,ly+lh/2,9,lh/2-3,0,0,Math.PI*2);ctx.fill();
  ctx.strokeStyle='#7a4a1a';ctx.lineWidth=2;
  ctx.beginPath();ctx.ellipse(log.x+10,ly+lh/2,4,lh/4,0,0,Math.PI*2);ctx.stroke();
  ctx.beginPath();ctx.ellipse(log.x+log.w-10,ly+lh/2,4,lh/4,0,0,Math.PI*2);ctx.stroke();
  ctx.strokeStyle='rgba(200,140,70,.28)';ctx.lineWidth=1.5;
  ctx.beginPath();ctx.moveTo(log.x+12,ly+3);ctx.lineTo(log.x+log.w-12,ly+3);ctx.stroke();
}
function drawFrog(x,y,facing){
  const cx=x+CELL/2,cy=y+CELL/2,rad=CELL/2-4;
  ctx.save();ctx.translate(cx,cy);
  if(facing==='down')ctx.rotate(Math.PI);
  if(facing==='left')ctx.rotate(-Math.PI/2);
  if(facing==='right')ctx.rotate(Math.PI/2);
  ctx.strokeStyle='#1a8a36';ctx.lineWidth=5;ctx.lineCap='round';
  ctx.beginPath();ctx.moveTo(-rad+5,rad-4);ctx.lineTo(-rad-7,rad+7);ctx.stroke();
  ctx.beginPath();ctx.moveTo(rad-5,rad-4);ctx.lineTo(rad+7,rad+7);ctx.stroke();
  ctx.fillStyle='#1a7a30';
  ctx.beginPath();ctx.arc(-rad-7,rad+7,5,0,Math.PI*2);ctx.fill();
  ctx.beginPath();ctx.arc(rad+7,rad+7,5,0,Math.PI*2);ctx.fill();
  ctx.fillStyle='#22aa44';ctx.beginPath();ctx.ellipse(0,3,rad,rad-3,0,0,Math.PI*2);ctx.fill();
  ctx.fillStyle='#88dd99';ctx.beginPath();ctx.ellipse(0,5,rad-5,rad-9,0,0,Math.PI*2);ctx.fill();
  ctx.fillStyle='#2abb4e';ctx.beginPath();ctx.ellipse(0,-rad+5,rad-2,rad-5,0,0,Math.PI*2);ctx.fill();
  ctx.fillStyle='#1a3a1a';
  ctx.beginPath();ctx.arc(-8,-rad+2,7,0,Math.PI*2);ctx.fill();
  ctx.beginPath();ctx.arc(8,-rad+2,7,0,Math.PI*2);ctx.fill();
  ctx.fillStyle='#44ff66';
  ctx.beginPath();ctx.arc(-8,-rad+2,5,0,Math.PI*2);ctx.fill();
  ctx.beginPath();ctx.arc(8,-rad+2,5,0,Math.PI*2);ctx.fill();
  ctx.fillStyle='#111';
  ctx.beginPath();ctx.arc(-7,-rad+2,3,0,Math.PI*2);ctx.fill();
  ctx.beginPath();ctx.arc(7,-rad+2,3,0,Math.PI*2);ctx.fill();
  ctx.fillStyle='#fff';
  ctx.beginPath();ctx.arc(-5.8,-rad+1,1.3,0,Math.PI*2);ctx.fill();
  ctx.beginPath();ctx.arc(5.8,-rad+1,1.3,0,Math.PI*2);ctx.fill();
  ctx.strokeStyle='#1a8a36';ctx.lineWidth=4;
  ctx.beginPath();ctx.moveTo(-rad+3,2);ctx.lineTo(-rad-5,10);ctx.stroke();
  ctx.beginPath();ctx.moveTo(rad-3,2);ctx.lineTo(rad+5,10);ctx.stroke();
  ctx.restore();
}
function drawFrogMini(x,y,size){
  ctx.save();ctx.translate(x+size/2,y+size/2);
  ctx.fillStyle='#22aa44';ctx.beginPath();ctx.ellipse(0,1,size/2-1,size/2-2,0,0,Math.PI*2);ctx.fill();
  ctx.fillStyle='#fff';
  ctx.beginPath();ctx.arc(-size/5,-size/4,size/6,0,Math.PI*2);ctx.fill();
  ctx.beginPath();ctx.arc(size/5,-size/4,size/6,0,Math.PI*2);ctx.fill();
  ctx.fillStyle='#111';
  ctx.beginPath();ctx.arc(-size/5,-size/4,size/10,0,Math.PI*2);ctx.fill();
  ctx.beginPath();ctx.arc(size/5,-size/4,size/10,0,Math.PI*2);ctx.fill();
  ctx.restore();
}

// ── Difficulty select screen ──────────────────────────────────────────────────
function drawDiffSelect(){
  ctx.clearRect(0,0,CW,CH);
  ctx.fillStyle='#040410';ctx.fillRect(0,0,CW,CH);
  for(let y=0;y<CH;y+=4){ctx.fillStyle='rgba(0,0,0,.18)';ctx.fillRect(0,y,CW,2);}
  ctx.font='bold 28px "Courier New",monospace';ctx.fillStyle='#44dd88';
  const tt='SELECT DIFFICULTY';ctx.fillText(tt,CW/2-ctx.measureText(tt).width/2,80);
  ctx.font='12px "Courier New",monospace';ctx.fillStyle='#444466';
  const st='\u2190 \u2192 or click to choose  \u00b7  ENTER to start';
  ctx.fillText(st,CW/2-ctx.measureText(st).width/2,104);
  drawFrog(CW/2-CELL/2,18,'up');
  const boxW=148,boxH=112,gap=14;
  const totalW=3*boxW+2*gap;
  const bx0=Math.round(CW/2-totalW/2);
  const by=CH/2-24;
  const COLORS=[['#1a4a1a','#2ecc71','#44ff88'],
                ['#3a3a00','#ccaa00','#ffdd44'],
                ['#4a0a0a','#cc2222','#ff4444']];
  for(let i=0;i<3;i++){
    const bx=bx0+i*(boxW+gap);
    const sel=i===selDiff;
    const[bgDark,border,text]=COLORS[i];
    if(sel){ctx.shadowColor=border;ctx.shadowBlur=18;}
    ctx.fillStyle=sel?bgDark:'#0c0c18';
    rrect(bx,by,boxW,boxH,8);ctx.fill();
    ctx.shadowBlur=0;
    ctx.strokeStyle=sel?border:'#222240';ctx.lineWidth=sel?2.5:1.5;
    rrect(bx,by,boxW,boxH,8);ctx.stroke();
    ctx.font='28px serif';ctx.textAlign='center';
    ctx.fillText(DIFF_EMOJI[i],bx+boxW/2,by+36);
    ctx.font=(sel?'bold ':'')+'17px "Courier New",monospace';
    ctx.fillStyle=sel?text:'#888899';
    ctx.fillText(DIFF_LABEL[i],bx+boxW/2,by+62);
    ctx.font='11px "Courier New",monospace';ctx.fillStyle=sel?text:'#555577';
    const lv2=DIFF_LIVES[i]+' lives';ctx.fillText(lv2,bx+boxW/2,by+80);
    ctx.font='9px "Courier New",monospace';ctx.fillStyle=sel?'rgba(255,255,255,.55)':'#333355';
    const words=DIFF_DESC[i].split(' \u00b7 ');
    words.forEach((w,wi)=>ctx.fillText(w,bx+boxW/2,by+94+wi*11));
    ctx.textAlign='left';
    if(sel){
      ctx.fillStyle=text;ctx.font='bold 16px "Courier New",monospace';ctx.textAlign='center';
      ctx.fillText('\u25b2',bx+boxW/2,by+boxH+18);ctx.textAlign='left';
    }
  }
  if(hiScore>0){
    ctx.font='12px "Courier New",monospace';ctx.fillStyle='#444466';ctx.textAlign='center';
    ctx.fillText('BEST: '+hiScore,CW/2,CH-28);ctx.textAlign='left';
  }
  ctx.font='11px "Courier New",monospace';ctx.fillStyle='#2a2a44';ctx.textAlign='center';
  ctx.fillText('ESC = EXIT',CW/2,CH-12);ctx.textAlign='left';
}

function draw(){
  if(phase==='select'){drawDiffSelect();return;}
  ctx.clearRect(0,0,CW,CH);
  ctx.fillStyle='#0a0a12';ctx.fillRect(0,0,CW,HH);
  ctx.fillStyle='#111120';ctx.fillRect(0,HH-2,CW,2);
  ctx.font='bold 22px "Courier New",monospace';ctx.fillStyle='#44dd88';ctx.fillText('FROGGER',10,34);
  ctx.font='11px "Courier New",monospace';ctx.fillStyle='#555577';
  ctx.fillText('SCORE',172,22);ctx.fillText('BEST',302,22);ctx.fillText('LVL',CW-120,22);
  ctx.font='bold 18px "Courier New",monospace';
  ctx.fillStyle='#ffffff';ctx.fillText(String(score).padStart(6,'0'),170,42);
  ctx.fillStyle='#ffdd44';ctx.fillText(String(hiScore).padStart(6,'0'),300,42);
  ctx.fillStyle='#44bbff';ctx.fillText(String(level).padStart(2,'0'),CW-118,42);
  const DIFF_HDR_COL=['#44ff88','#ffdd44','#ff6666'];
  ctx.font='10px "Courier New",monospace';ctx.fillStyle=DIFF_HDR_COL[difficulty];
  ctx.fillText(DIFF_EMOJI[difficulty]+' '+DIFF_LABEL[difficulty],CW-118,54+2);
  for(let i=0;i<lives;i++)drawFrogMini(CW-26*(i+1)+4,13,20);
  for(let r=0;r<ROWS;r++){
    const y=rowY(r),row=rows[r];
    ctx.fillStyle=row.bg;ctx.fillRect(0,y,CW,CELL);
    if(row.type==='safe')drawGrass(y);
    else if(row.type==='home')drawHomeRow(y);
    else if(row.type==='road')drawRoad(r,y);
    else if(row.type==='water')drawWater(r,y);
  }
  if(phase==='playing'||phase==='levelup')drawFrog(frog.px,rowY(frog.row),frog.facing);
  if(phase==='dying'){
    const fx=frog.px,fy=rowY(frog.row);
    ctx.save();ctx.strokeStyle='#ff4040';ctx.lineWidth=3;
    ctx.globalAlpha=0.7+0.3*Math.sin(phaseTimer*28);
    ctx.beginPath();ctx.moveTo(fx+5,fy+5);ctx.lineTo(fx+CELL-5,fy+CELL-5);ctx.stroke();
    ctx.beginPath();ctx.moveTo(fx+CELL-5,fy+5);ctx.lineTo(fx+5,fy+CELL-5);ctx.stroke();
    ctx.restore();
  }
  if(phase==='levelup'){
    ctx.fillStyle='rgba(0,0,0,.62)';ctx.fillRect(0,HH,CW,ROWS*CELL);
    ctx.font='bold 30px "Courier New",monospace';ctx.fillStyle='#ffdd44';
    const lc='LEVEL '+level+' CLEAR!';ctx.fillText(lc,CW/2-ctx.measureText(lc).width/2,HH+ROWS*CELL/2-18);
    ctx.font='18px "Courier New",monospace';ctx.fillStyle='#44dd88';
    const bn='+500 BONUS!';ctx.fillText(bn,CW/2-ctx.measureText(bn).width/2,HH+ROWS*CELL/2+18);
  }
  if(phase==='gameover'){
    ctx.fillStyle='rgba(0,0,0,.84)';ctx.fillRect(0,0,CW,CH);
    ctx.font='bold 40px "Courier New",monospace';ctx.fillStyle='#ff4444';
    const go='GAME OVER';ctx.fillText(go,CW/2-ctx.measureText(go).width/2,CH/2-80);
    ctx.font='14px "Courier New",monospace';ctx.fillStyle='#666688';
    const dif=DIFF_EMOJI[difficulty]+' '+DIFF_LABEL[difficulty]+' \u00b7 LEVEL '+level;
    ctx.fillText(dif,CW/2-ctx.measureText(dif).width/2,CH/2-46);
    ctx.font='20px "Courier New",monospace';ctx.fillStyle='#ffffff';
    const sc='SCORE: '+score;ctx.fillText(sc,CW/2-ctx.measureText(sc).width/2,CH/2-10);
    ctx.font='16px "Courier New",monospace';ctx.fillStyle='#ffdd44';
    const bs='BEST: '+hiScore;ctx.fillText(bs,CW/2-ctx.measureText(bs).width/2,CH/2+22);
    const secs=Math.ceil(Math.max(0,phaseTimer));
    if(qualifies(score)){
      ctx.font='bold 15px "Courier New",monospace';ctx.fillStyle='#44ffaa';
      const qt='\u2605  NEW HIGH SCORE!  \u2605';ctx.fillText(qt,CW/2-ctx.measureText(qt).width/2,CH/2+58);
      ctx.font='13px "Courier New",monospace';ctx.fillStyle='#aaaacc';
      const ent='ENTERING INITIALS IN '+secs+'\u2026';ctx.fillText(ent,CW/2-ctx.measureText(ent).width/2,CH/2+82);
    }else{
      ctx.font='13px "Courier New",monospace';ctx.fillStyle='#aaaacc';
      const lb='LEADERBOARD IN '+secs+'\u2026';ctx.fillText(lb,CW/2-ctx.measureText(lb).width/2,CH/2+58);
    }
    ctx.font='12px "Courier New",monospace';ctx.fillStyle='#333355';
    const skip='ENTER / SPACE  \u00b7  SKIP';ctx.fillText(skip,CW/2-ctx.measureText(skip).width/2,CH/2+108);
    ctx.font='11px "Courier New",monospace';ctx.fillStyle='#2a2a44';
    const ex='ESC  \u00b7  EXIT';ctx.fillText(ex,CW/2-ctx.measureText(ex).width/2,CH/2+128);
  }
  if(phase==='initials')drawInitials();
  if(phase==='leaderboard')drawLeaderboard();
}

// ── Initials entry screen ─────────────────────────────────────────────────────
function drawInitials(){
  ctx.fillStyle='rgba(0,0,0,.92)';ctx.fillRect(0,0,CW,CH);
  ctx.font='bold 32px "Courier New",monospace';ctx.fillStyle='#44ffaa';
  const t='NEW HIGH SCORE!';ctx.fillText(t,CW/2-ctx.measureText(t).width/2,110);
  ctx.font='18px "Courier New",monospace';ctx.fillStyle='#ffffff';
  const sc='SCORE: '+score;ctx.fillText(sc,CW/2-ctx.measureText(sc).width/2,148);
  ctx.font='13px "Courier New",monospace';ctx.fillStyle='#888899';
  const ins='\u2191 \u2193  CHOOSE LETTER   \u2190 \u2192  MOVE   ENTER  CONFIRM';
  ctx.fillText(ins,CW/2-ctx.measureText(ins).width/2,190);
  const bW=62,bH=72,gap=20;
  const totalW=3*bW+2*gap;
  const bx0=Math.round(CW/2-totalW/2);
  const by=216;
  for(let i=0;i<3;i++){
    const bx=bx0+i*(bW+gap);
    const active=i===_initCursor;
    ctx.strokeStyle=active?'#44ffaa':'#334455';
    ctx.lineWidth=active?2.5:1.5;
    ctx.fillStyle=active?'rgba(68,255,170,.12)':'rgba(30,30,60,.5)';
    rrect(bx,by,bW,bH,10);ctx.fill();ctx.stroke();
    ctx.font='bold 38px "Courier New",monospace';
    ctx.fillStyle=active?'#ffffff':'#667788';
    const ch=_initials[i];
    ctx.fillText(ch,bx+bW/2-ctx.measureText(ch).width/2,by+bH-16);
    if(active){
      ctx.fillStyle='#44ffaa';ctx.font='14px "Courier New",monospace';
      ctx.fillText('\u25b2',bx+bW/2-6,by-8);
      ctx.fillText('\u25bc',bx+bW/2-6,by+bH+18);
    }
  }
  ctx.font='13px "Courier New",monospace';ctx.fillStyle='#44aa88';
  const hint=_initCursor<2?'ENTER \u00b7 NEXT LETTER':'ENTER \u00b7 SUBMIT';
  ctx.fillText(hint,CW/2-ctx.measureText(hint).width/2,by+bH+44);
}

// ── Leaderboard screen ────────────────────────────────────────────────────────
function drawLeaderboard(){
  ctx.fillStyle='rgba(0,0,0,.93)';ctx.fillRect(0,0,CW,CH);
  ctx.font='bold 28px "Courier New",monospace';ctx.fillStyle='#ffdd44';
  const t='\u{1F3C6}  LEADERBOARD';ctx.fillText(t,CW/2-ctx.measureText(t).width/2,72);
  ctx.font='11px "Courier New",monospace';ctx.fillStyle='#445566';
  ctx.fillText('RANK',62,112);ctx.fillText('NAME',130,112);
  ctx.fillText('SCORE',230,112);ctx.fillText('LVL',335,112);ctx.fillText('DIFF',392,112);
  ctx.strokeStyle='#223344';ctx.lineWidth=1;
  ctx.beginPath();ctx.moveTo(44,118);ctx.lineTo(CW-44,118);ctx.stroke();
  const RANK_COLORS=['#ffd700','#c0c0c0','#cd7f32','#aaaacc','#667788'];
  const rowH=48,rowY0=132;
  for(let i=0;i<leaderboard.length;i++){
    const e=leaderboard[i];
    const ry=rowY0+i*rowH;
    const isNew=(i===_newEntryRank);
    if(isNew){
      ctx.fillStyle='rgba(68,255,170,.1)';
      rrect(44,ry-26,CW-88,38,8);ctx.fill();
      ctx.strokeStyle='rgba(68,255,170,.35)';ctx.lineWidth=1.5;
      rrect(44,ry-26,CW-88,38,8);ctx.stroke();
    }
    ctx.font='bold 18px "Courier New",monospace';
    ctx.fillStyle=RANK_COLORS[i]||(isNew?'#44ffaa':'#334455');
    const rk='#'+(i+1);ctx.fillText(rk,62,ry+4);
    ctx.font='bold 20px "Courier New",monospace';
    ctx.fillStyle=isNew?'#44ffaa':'#ccddee';
    ctx.fillText(e.name,130,ry+4);
    ctx.font='18px "Courier New",monospace';ctx.fillStyle=isNew?'#44ffaa':'#ffffff';
    ctx.fillText(e.score,230,ry+4);
    ctx.font='15px "Courier New",monospace';ctx.fillStyle='#889aaa';
    ctx.fillText(e.level,345,ry+4);
    ctx.font='12px "Courier New",monospace';ctx.fillStyle='#667788';
    ctx.fillText(e.diff.slice(0,3),394,ry+4);
  }
  if(!leaderboard.length){
    ctx.font='16px "Courier New",monospace';ctx.fillStyle='#445566';
    const em='No scores yet \u2014 play to earn your place!';
    ctx.fillText(em,CW/2-ctx.measureText(em).width/2,260);
  }
  ctx.font='13px "Courier New",monospace';ctx.fillStyle='#44dd88';
  const ft='ENTER \u00b7 PLAY AGAIN';ctx.fillText(ft,CW/2-ctx.measureText(ft).width/2,CH-48);
  ctx.font='11px "Courier New",monospace';ctx.fillStyle='#2a2a44';
  const ex='ESC \u00b7 EXIT';ctx.fillText(ex,CW/2-ctx.measureText(ex).width/2,CH-26);
}

// ── Canvas click (difficulty select boxes) ────────────────────────────────────
canvas.addEventListener('click',function(e){
  if(phase!=='select')return;
  const rect=canvas.getBoundingClientRect();
  const mx=(e.clientX-rect.left)*(CW/rect.width);
  const my=(e.clientY-rect.top)*(CH/rect.height);
  const boxW=148,boxH=112,gap=14;
  const totalW=3*boxW+2*gap;
  const bx0=Math.round(CW/2-totalW/2);
  const by=CH/2-24;
  for(let i=0;i<3;i++){
    const bx=bx0+i*(boxW+gap);
    if(mx>=bx&&mx<=bx+boxW&&my>=by&&my<=by+boxH){selDiff=i;initGame();}
  }
});

// ── Exit ──────────────────────────────────────────────────────────────────────
function closeGame(){
  cancelAnimationFrame(rafId);
  document.removeEventListener('keydown',onKey);
  if(_ac){try{_ac.close();}catch(_e){}}
  if(window.self!==window.top){
    // Running inside CineVault iframe — tell parent to close us
    window.parent.postMessage('frogger:exit','*');
  } else {
    // Standalone — try to close the tab; show hint if browser blocks it
    window.close();
    setTimeout(()=>{
      const btn=document.getElementById('close-btn');
      if(btn)btn.textContent='Close this tab to exit';
    },300);
  }
}

// ── Game loop ─────────────────────────────────────────────────────────────────
let rafId,lastTs=0;
showSelect();
function loop(ts){
  const dt=Math.min((ts-lastTs)/1000,0.05);lastTs=ts;
  update(dt);draw();rafId=requestAnimationFrame(loop);
}
rafId=requestAnimationFrame(ts=>{lastTs=ts;rafId=requestAnimationFrame(loop);});
</script>
</body>
</html>"""


# ── Standalone Flask app ──────────────────────────────────────────────────────
if __name__ == '__main__':
    from flask import Flask, Response

    app = Flask(__name__)

    @app.route('/')
    def index():
        return Response(FROGGER_HTML, mimetype='text/html')

    print('=' * 52)
    print('  Frogger  —  standalone mode')
    print('  Open:  http://localhost:5001/')
    print('  Stop:  Ctrl+C')
    print('=' * 52)
    app.run(host='127.0.0.1', port=5001, debug=False)
