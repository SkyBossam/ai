"""Annotated loopback preview and queued caregiver feedback over an SSH tunnel."""
from collections import deque
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json,threading,time
from urllib.parse import urlsplit,parse_qs
import cv2
import numpy as np

PAGE=r'''<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sky Eye 카메라 테스트</title>
<style>body{font:16px system-ui;background:#111827;color:#eef2ff;margin:24px;max-width:1080px}h1{font-size:24px}img{width:100%;max-width:800px;background:#000;border:1px solid #475569;border-radius:8px}.grid{display:flex;gap:12px;flex-wrap:wrap}.card{background:#1f2937;padding:14px;border-radius:8px;min-width:170px}small{color:#cbd5e1}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}#connection{color:#fbbf24}code{color:#93c5fd}</style>
<h1>Sky Eye · 실시간 감지 테스트</h1><p id="connection">카메라 연결 중…</p>
<img id="camera" src="/stream" alt="감지 박스가 표시된 카메라 영상">
<p><small>몸: 초록/엎드림 빨강 · 얼굴: 하늘색/가림 주황 · 베개·장난감: 보라 · 숫자: 신뢰도</small></p>
<div class="grid"><div class="card">자세·얼굴<pre id="posture">대기 중</pre></div><div class="card">위험 판정<pre id="risk">대기 중</pre></div><div class="card">침대 경계<pre id="bed">대기 중</pre></div><div class="card">성능<pre id="perf">대기 중</pre></div></div>
<h2>울음·마이크 테스트</h2><div class="card"><pre id="audio">울음 테스트 꺼짐</pre>
<audio controls preload="none" src="/test-cry.wav"></audio><p><small>테스트 울음: PC 스피커로 재생해 파이 마이크에 들려주세요. <a href="https://github.com/karoldvl/ESC-50" style="color:#93c5fd">ESC-50 공개 테스트 음원</a> · CC BY-NC 3.0 · 파일별 출처는 assets/test-clip-attribution.json에 기록</small></p></div>
<h2>울음 돌봄 힌트 · 실험 기능</h2><div class="card"><pre id="hints">대기 중</pre>
<p><small>확정 원인이 아닌 돌봄 순서 참고입니다. 보호자 피드백 10건과 현재 울음 창 10개가 있어야 추천을 표시합니다. 수유·기저귀·안아주기 중 실제로 그친 행동을 기록해주세요.</small></p>
<button id="feedNow">지금 수유한 사실 기록</button><p id="feedbackResult" role="status"></p><div id="feedback"></div>
<button id="demoButton">시뮬레이션 예시 보기 · 가상 피드백 10개</button><pre id="demo"></pre></div>
<h2>현재 감지</h2><pre id="detections">대기 중</pre><h2>최근 이벤트</h2><pre id="events">아직 이벤트가 없습니다.</pre>
<p><small>벽만 보이면 박스 없음·no_baby가 정상입니다. 기본 모델에는 베개·장난감 클래스가 없습니다. 이 화면은 보호자 알림 서버에 연결하지 않습니다.</small></p>
<script>
const put=(id,v)=>document.getElementById(id).textContent=v;
const tr={supine:'바로 누움',side:'옆으로 누움',prone:'엎드림',airway_visible:'코·입 보임',airway_covered:'코·입 가림',normal:'정상',caution:'주의',risk:'위험',unavailable:'분석 불가'};
const label=v=>tr[v]||v||'미검출';
let feedbackKey='';
async function command(body){const r=await fetch('/api/cry/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const q=await r.json();if(!r.ok)throw Error(q.error||'요청 실패');
put('feedbackResult','기록 처리 중…');for(let i=0;i<20;i++){await new Promise(resolve=>setTimeout(resolve,500));const rr=await fetch('/api/cry/receipt?id='+q.command_id,{cache:'no-store'});if(rr.ok){const v=await rr.json();if(!v.ok)throw Error(v.error);put('feedbackResult','기록했습니다.');return}}throw Error('아직 처리되지 않았습니다. 울음 서비스 상태를 확인하세요.');}
document.getElementById('feedNow').onclick=()=>command({kind:'feed'}).catch(e=>put('feedbackResult',e.message));
document.getElementById('demoButton').onclick=async()=>{try{const r=await fetch('/api/cry/demo');if(!r.ok)throw Error();const d=await r.json();put('demo','시뮬레이션 전용 · 가상 기록 10개 · 실제 프로필 미변경\n예시 추천: '+d.hint.top2_ko.join(' → ')+'\n실제 원인 정확도 평가 결과가 아닙니다.')}catch(e){put('demo','시뮬레이션 파일이 없습니다.')}};
function hints(a){const p=a?.personalization;if(!a?.running||a.age_s>4||!p){put('hints','울음 서비스의 새 입력을 기다립니다.');document.getElementById('feedback').replaceChildren();feedbackKey='';return}
const states={insufficient_history:'보호자 피드백이 더 필요합니다',collecting_audio:'현재 울음 특징 수집 중',idle:'다음 울음 대기 중',ready:'먼저 확인해볼 돌봄 순서',low_confidence:'추천 보류'};
put('hints',(states[p.state]||p.state)+'\n피드백 '+p.n_feedback+'/'+p.required_feedback+' · 현재 울음 창 '+p.cry_windows+'/'+p.required_cry_windows+'\n'+(p.recommendations||[]).map((h,i)=>(i+1)+'. '+h.label).join('\n')+'\n소리 특징 반영: '+(p.sound_on?'켬':'검증 대기 · 맥락과 이력 사용'));
const episodes=(p.recent_episodes||[]).filter(e=>!e.action);const key=JSON.stringify(episodes);if(key===feedbackKey)return;feedbackKey=key;const box=document.getElementById('feedback');box.replaceChildren();
for(const ep of episodes){const row=document.createElement('p');row.textContent=new Date(ep.ended_at*1000).toLocaleTimeString()+' 울음은 무엇으로 그쳤나요? ';for(const [action,text] of [['feed','수유'],['diaper','기저귀'],['hold','안아주기·자세 바꾸기'],['self','저절로'],['unknown','모름']]){const b=document.createElement('button');b.textContent=text;b.onclick=()=>command({kind:'feedback',episode_uid:ep.episode_uid,action}).catch(e=>put('feedbackResult',e.message));row.append(b)}box.append(row)}}
async function update(){try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error();const s=await r.json();
put('connection',s.preview_age_s>3?'새 프레임 대기 중':'실시간 연결됨 · '+(s.model_classes||[]).length+'클래스 모델');
put('posture',label(s.posture?.posture)+' / '+label(s.posture?.airway));
put('risk',label(s.posture_state)+'\n'+(s.posture_reason||'')+'\n엎드림 '+(s.risk_elapsed_s?.prone||0).toFixed(1)+'초 / 얼굴 가림 '+(s.risk_elapsed_s?.face_covered||0).toFixed(1)+'초');
put('bed',s.geometry_valid?(s.fall?.state||'대기'):'미보정 — 가장자리 위험 판정 비활성');
put('perf',(s.processing_fps||0).toFixed(1)+' FPS\n'+(s.pipeline_ms||0).toFixed(0)+' ms\n'+(s.temperature_c==null?'':s.temperature_c.toFixed(1)+' °C'));
put('detections',(s.visible_detections||[]).map(d=>d.cls+' '+(100*d.conf).toFixed(1)+'%  ['+d.xyxy.map(Math.round).join(', ')+']').join('\n')||'감지 박스 없음');
put('events',s.recent_events?.length?JSON.stringify(s.recent_events,null,2):'아직 이벤트가 없습니다.');
const a=s.audio;
hints(a);
if(!a)put('audio','울음 테스트 꺼짐');
else if(a.state==='error')put('audio','입력 오류: '+a.error);
else if(!a.running||a.age_s>4)put('audio','울음 테스트 중지 또는 입력 갱신 없음');
else put('audio',(a.baby_cry_detected?'아기 울음 후보':a.cry_detected?'울음 후보':'울음 미검출')+'\n아기 울음 점수 '+(a.baby_cry_score||0).toFixed(3)+' / 일반 울음 '+(a.crying_score||0).toFixed(3)+'\n기준 '+(a.threshold||.3).toFixed(2)+' · 입력 '+(a.rms_dbfs??-180).toFixed(1)+' dBFS\n가장 높은 소리: '+(a.top_classes?.[0]?.label||'대기'));
}catch(e){put('connection','연결 끊김 — SSH 터널과 파이 서비스를 확인하세요.')}finally{setTimeout(update,500)}}
const img=document.getElementById('camera');img.onerror=()=>setTimeout(()=>{img.src='/stream?t='+Date.now()},1500);update();
</script></html>'''


def visible_detections(state,config):
    selected=[]
    for detection in state.get('detections',[]):
        cls=detection['cls']
        threshold=(config['body_confidence'] if cls in ('supine','side','prone') else
                   config['airway_confidence'] if cls.startswith('airway_') else config['object_confidence'])
        if detection['conf']>=threshold:
            selected.append(detection)
    return selected


def annotate(frame,state,config):
    image=frame.copy()
    colors={'prone':(70,70,255),'airway_covered':(0,150,255),'airway_visible':(255,220,0),
            'pillow':(240,80,220),'toy':(240,80,220)}
    for d in visible_detections(state,config):
        x1,y1,x2,y2=[int(round(v)) for v in d['xyxy']]
        color=colors.get(d['cls'],(80,230,80))
        cv2.rectangle(image,(x1,y1),(x2,y2),color,2)
        text=d['cls']+' '+f"{d['conf']:.2f}"
        cv2.putText(image,text,(max(0,x1),max(18,y1-6)),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,0),3,cv2.LINE_AA)
        cv2.putText(image,text,(max(0,x1),max(18,y1-6)),cv2.FONT_HERSHEY_SIMPLEX,.5,color,1,cv2.LINE_AA)
    text='posture='+str(state.get('posture',{}).get('posture') or 'none')+'  state='+state.get('posture_state','starting')
    cv2.putText(image,text,(8,22),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,0),3,cv2.LINE_AA)
    cv2.putText(image,text,(8,22),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1,cv2.LINE_AA)
    if not state.get('geometry_valid'):
        cv2.putText(image,'BED NOT CALIBRATED',(8,image.shape[0]-12),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,180,255),1,cv2.LINE_AA)
    return image


class PreviewServer:
    def __init__(self,port,config):
        self.config=config
        self.condition=threading.Condition()
        self.stopping=threading.Event()
        self.jpeg=None
        self.sequence=0
        self.state={}
        self.updated=None
        self.recent=deque(maxlen=12)
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*unused):
                pass

            def do_GET(self):
                path=self.path.split('?',1)[0]
                if path=='/':
                    self.send_payload(PAGE.encode('utf-8'),'text/html; charset=utf-8')
                elif path=='/api/cry/demo':
                    try:self.send_payload(Path('assets/cause-demo.json').read_bytes(),'application/json')
                    except OSError:self.send_error(404)
                elif path=='/api/cry/receipt':
                    identifier=parse_qs(urlsplit(self.path).query).get('id',[''])[0]
                    if len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):
                        self.send_error(400);return
                    folder=Path(owner.config.get('cry_command_dir','input/cry_commands')).parent/'cry_receipts'
                    try:self.send_payload((folder/(identifier+'.json')).read_bytes(),'application/json')
                    except OSError:self.send_error(404)
                elif path=='/api/status':
                    with owner.condition:
                        value=dict(owner.state,preview_age_s=time.monotonic()-owner.updated if owner.updated else None)
                    audio_path=Path(owner.config.get('audio_status_path','logs/cry/status.json'))
                    try:
                        audio=json.loads(audio_path.read_text())
                        audio['age_s']=max(0.,time.time()-audio['wall_time_unix'])
                        value['audio']=audio
                    except (OSError,ValueError,KeyError):
                        value['audio']=None
                    self.send_payload(json.dumps(value).encode(),'application/json')
                elif path=='/test-cry.wav':
                    sample=Path(owner.config.get('cry_sample_path','assets/test-cry-16k.wav'))
                    try:self.send_payload(sample.read_bytes(),'audio/wav')
                    except OSError:self.send_error(404,'Cry test sample is not installed')
                elif path=='/frame.jpg':
                    with owner.condition:
                        data=owner.jpeg
                    if data is None:
                        self.send_error(503,'Waiting for first frame')
                    else:
                        self.send_payload(data,'image/jpeg')
                elif path=='/stream':
                    self.send_response(200)
                    self.send_header('Content-Type','multipart/x-mixed-replace; boundary=frame')
                    self.send_header('Cache-Control','no-store')
                    self.end_headers()
                    previous=-1
                    try:
                        while not owner.stopping.is_set():
                            with owner.condition:
                                owner.condition.wait_for(lambda:(owner.jpeg is not None and owner.sequence!=previous) or owner.stopping.is_set(),timeout=2)
                                if owner.jpeg is None or owner.sequence==previous:
                                    continue
                                previous,data=owner.sequence,owner.jpeg
                            self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+b'\r\n\r\n'+data+b'\r\n')
                            self.wfile.flush()
                    except (BrokenPipeError,ConnectionResetError,OSError):
                        pass
                else:
                    self.send_error(404)

            def do_POST(self):
                from sky_edge.personalization import enqueue
                try:
                    if self.path!='/api/cry/command':self.send_error(404);return
                    host=self.headers.get('Host','')
                    if urlsplit('http://'+host).hostname not in ('127.0.0.1','localhost'):
                        raise ValueError('Loopback host required')
                    if self.headers.get('Origin','http://'+host)!='http://'+host:
                        raise ValueError('Same origin required')
                    if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                        raise ValueError('application/json required')
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=2048:raise ValueError('Invalid request size')
                    self.connection.settimeout(3)
                    value=enqueue(owner.config.get('cry_command_dir','input/cry_commands'),json.loads(self.rfile.read(size)))
                    self.send_payload(json.dumps(value).encode(),'application/json',202)
                except (ValueError,OSError) as exc:
                    self.send_payload(json.dumps(dict(error=str(exc))).encode(),'application/json',400)

            def send_payload(self,data,content_type,status=200):
                self.send_response(status)
                self.send_header('Content-Type',content_type)
                self.send_header('Content-Length',str(len(data)))
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError,ConnectionResetError):
                    pass
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        self.server.daemon_threads=True
        self.port=self.server.server_address[1]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def publish(self,frame,state,events=()):
        annotated=annotate(frame,state,self.config)
        ok,jpeg=cv2.imencode('.jpg',annotated,[cv2.IMWRITE_JPEG_QUALITY,80])
        if not ok:
            raise RuntimeError('Preview JPEG encoding failed')
        with self.condition:
            self.recent.extend(events)
            self.state=dict(state,visible_detections=visible_detections(state,self.config),recent_events=list(self.recent))
            self.jpeg=jpeg.tobytes()
            self.updated=time.monotonic()
            self.sequence+=1
            self.condition.notify_all()

    def close(self):
        self.stopping.set()
        with self.condition:
            self.condition.notify_all()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
