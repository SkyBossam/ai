"""Headless Pi entry point; no torch, ultralytics or display required."""
from pathlib import Path
import argparse,hashlib,json,platform,signal,sys,time,threading
from collections import deque
import numpy as np
from camera_fall.common import load,dump
from sleepsafe.detector_onnx import OnnxDetector
from sky_edge.pipeline import SharedPipeline

EXPECTED=['supine','side','prone','airway_visible','airway_covered']


def make_detector(config):
    path=Path(config['model'])
    meta=load(path.with_name('model_meta.json'))
    names=meta['classes']
    if names not in (EXPECTED,EXPECTED+['pillow','toy']):
        raise ValueError('Unsupported model class order: '+str(names))
    if hashlib.sha256(path.read_bytes()).hexdigest()!=meta['sha256']:
        raise ValueError('Model checksum differs from model_meta.json')
    if not meta.get('parity_passed'):
        raise ValueError('PT/ONNX export consistency must be verified before deployment')
    confidence=min(config['body_confidence'],config['airway_confidence'],config['object_confidence'])
    backend=config.get('inference_backend','onnxruntime')
    if backend=='ncnn':
        from sky_edge.detector_ncnn import NCNNDetector
        conversion=load(path.with_name('ncnn_meta.json'))
        if conversion['source_onnx_sha256']!=meta['sha256'] or not conversion['parity_passed']:
            raise ValueError('NCNN export consistency not verified')
        for name,expected in conversion['files'].items():
            if hashlib.sha256(path.with_name(name).read_bytes()).hexdigest()!=expected:
                raise ValueError('NCNN file checksum mismatch: '+name)
        detector=NCNNDetector(path,names,confidence,.7,config['threads'])
    elif backend=='opencv':
        from sky_edge.detector_opencv import OpenCVDetector
        detector=OpenCVDetector(path,names,confidence,.7,config['threads'])
    elif backend=='onnxruntime':
        detector=OnnxDetector(path,conf=confidence,iou=.7,threads=config['threads'],names=names)
        if detector.session.get_inputs()[0].shape != [1,3,320,320]:
            raise ValueError('Expected static FP32 model input [1,3,320,320]')
    else:
        raise ValueError('Unknown inference_backend: '+str(backend))
    detector(np.zeros((320,320,3),np.uint8))
    return detector,meta


class Camera:
    def __init__(self,config):
        import cv2
        self.config=config
        self.lock=threading.Lock()
        self.latest=None
        self.error=None
        self.stop=threading.Event()
        self.last_sequence=-1
        self.csi=None
        if config['camera_backend']=='picamera2':
            from picamera2 import Picamera2
            self.csi=Picamera2(config['camera_index'])
            # Picamera2 RGB888 has byte order B,G,R, matching OpenCV.
            self.csi.configure(self.csi.create_video_configuration(main={'size':tuple(config['frame_size']),
                               'format':'RGB888'},buffer_count=2,controls={'FrameRate':config['camera_fps']}))
            self.csi.start()
        else:
            source=config['camera_source']
            source=int(source) if str(source).isdigit() else source
            self.cap=cv2.VideoCapture(source,cv2.CAP_V4L2 if isinstance(source,int) and sys.platform=='linux' else cv2.CAP_ANY)
            if not self.cap.isOpened():
                raise RuntimeError('Cannot open camera: '+str(source))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,config['frame_size'][0])
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT,config['frame_size'][1])
            self.cap.set(cv2.CAP_PROP_FPS,config['camera_fps'])
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
        self.thread=threading.Thread(target=self._capture,daemon=True)
        self.thread.start()

    def _capture(self):
        sequence=0
        try:
            while not self.stop.is_set():
                if self.csi:
                    frame=self.csi.capture_array('main')
                else:
                    ok,frame=self.cap.read()
                    if not ok:
                        raise RuntimeError('Camera read failed')
                ts=time.monotonic()
                with self.lock:
                    self.latest=(sequence,ts,frame)
                sequence+=1
        except Exception as exc:
            self.error=str(exc)

    def read(self,timeout):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            with self.lock:
                data=self.latest
                if data is not None and data[0]!=self.last_sequence:
                    self.last_sequence=data[0]
                    return data[1],data[2]
            if self.error:
                raise RuntimeError(self.error)
            time.sleep(.005)
        raise TimeoutError('No fresh camera frame')

    def close(self):
        self.stop.set()
        if self.csi:
            self.csi.stop()
            self.csi.close()
        else:
            self.cap.release()
        self.thread.join(timeout=2)


def thermal():
    path=Path('/sys/class/thermal/thermal_zone0/temp')
    return float(path.read_text())/1000 if path.exists() else None


def run(config,args):
    import cv2
    cv2.setNumThreads(1)
    detector,meta=make_detector(config)
    geometry=load(config['geometry'])
    pipeline=SharedPipeline(detector,geometry,load(config['fall_policy']),config)
    output=Path(args.output)
    output.mkdir(parents=True,exist_ok=True)
    if (output/'events.jsonl').exists():
        raise FileExistsError('Choose a new --output directory')
    camera=Camera(config)
    time.sleep(config.get('camera_warmup_s',2.))
    preview=None
    preview_port=args.preview_port or config.get('preview_port',0)
    if preview_port:
        from sky_edge.preview import PreviewServer
        preview=PreviewServer(preview_port,config)
    stopping=threading.Event()
    for signum in (signal.SIGINT,signal.SIGTERM):
        signal.signal(signum,lambda *unused:stopping.set())
    durations=deque(maxlen=120)
    started=time.monotonic()
    frames=0
    maximum_age=0.
    try:
        with (output/'events.jsonl').open('x',encoding='utf-8') as events:
            while not stopping.is_set() and (args.seconds<=0 or time.monotonic()-started<args.seconds):
                tick=time.monotonic()
                ts,frame=camera.read(config['camera_timeout_s'])
                age=time.monotonic()-ts
                if age>config['maximum_frame_age_s']:
                    raise RuntimeError('Stale camera frame')
                maximum_age=max(maximum_age,age)
                result=pipeline.step(frame,ts)
                frames+=1
                durations.append(time.monotonic()-tick)
                frame_events=result.pop('events')
                for event in frame_events:
                    events.write(json.dumps(dict(wall_time_unix=time.time(),**event),ensure_ascii=False)+'\n')
                    events.flush()
                result.update(wall_time_unix=time.time(),frames=frames,model_classes=meta['classes'],
                              temperature_c=thermal(),pipeline_ms=float(np.mean(durations)*1000),
                              processing_fps=frames/max(time.monotonic()-started,1e-6),
                              risk_elapsed_s=pipeline.posture.elapsed(ts))
                if preview:
                    preview.publish(frame,result,frame_events)
                temp=output/'status.pending'
                dump(temp,result)
                temp.replace(output/'status.json')
                if args.print_status:
                    print(json.dumps(result,ensure_ascii=False),flush=True)
                stopping.wait(max(0.,1/config['target_fps']-(time.monotonic()-tick)))
    except Exception as exc:
        error=dict(error=str(exc),wall_time_unix=time.time(),status='unavailable',
                   posture_state='risk' if pipeline.posture.active else 'unavailable',
                   fall=dict(state='unavailable',observation_valid=False,active_warning=pipeline.fall.active))
        dump(output/'error.json',error)
        dump(output/'status.pending',error)
        (output/'status.pending').replace(output/'status.json')
        raise
    finally:
        camera.close()
        if preview:
            preview.close()
        elapsed=time.monotonic()-started
        dump(output/'run_summary.json',dict(frames=frames,elapsed_s=elapsed,fps=frames/elapsed,
             maximum_frame_age_s=maximum_age,temperature_c=thermal(),model_sha256=meta['sha256']))


def benchmark(config,args):
    import cv2
    cv2.setNumThreads(1)
    detector,meta=make_detector(config)
    frame=cv2.imread(args.image) if args.image else np.full((480,640,3),114,np.uint8)
    if frame is None:
        raise ValueError('Cannot read --image')
    for _ in range(5):
        detector(frame)
    temperatures=[thermal()]
    times=[]
    start=time.monotonic()
    while len(times)<args.samples or time.monotonic()-start<args.seconds:
        before=time.perf_counter()
        detector(frame)
        times.append(time.perf_counter()-before)
    temperatures.append(thermal())
    p95=float(np.percentile(times,95))
    value=dict(samples=len(times),elapsed_s=time.monotonic()-start,mean_ms=float(np.mean(times)*1000),
               p50_ms=float(np.percentile(times,50)*1000),p95_ms=p95*1000,mean_fps=1/float(np.mean(times)),
               inference_path='letterbox + '+config.get('inference_backend','onnxruntime')+' CPU + class-aware NMS; excludes camera and policy',
               representative_image=bool(args.image),temperature_c=temperatures,threads=config['threads'],
               platform=platform.platform(),machine=platform.machine(),model_sha256=meta['sha256'],
               model_classes=meta['classes'],r0_gap_budget_s=load(config['fall_policy'])['max_observation_gap_s'],
               r0_timing_budget_met=p95<load(config['fall_policy'])['max_observation_gap_s'])
    dump(args.output,value)
    print(json.dumps(value,indent=2))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=('run','benchmark','check','snapshot'))
    parser.add_argument('--config',default='deploy/pi/config.json')
    parser.add_argument('--output',default=None)
    parser.add_argument('--seconds',type=float,default=0.)
    parser.add_argument('--samples',type=int,default=100)
    parser.add_argument('--image')
    parser.add_argument('--print-status',action='store_true')
    parser.add_argument('--preview-port',type=int,default=0,help='Loopback HTTP preview port; access over SSH -L')
    args=parser.parse_args()
    config=load(args.config)
    if not 0<=args.preview_port<=65535 or not 0<=config.get('preview_port',0)<=65535:
        parser.error('preview port must be 0 (disabled) or 1..65535')
    for name in ('body_confidence','airway_confidence','object_confidence','minimum_brightness','body_duplicate_iou'):
        if not 0<=config[name]<=1:
            parser.error('Invalid probability/ratio: '+name)
    for name in ('threads','target_fps','camera_timeout_s','maximum_frame_age_s','track_gap_s','posture_stable_s'):
        if config[name]<=0:
            parser.error('Positive value required: '+name)
    if any(value<0 for value in config['posture_risk'].values()):
        parser.error('Posture timers must be nonnegative')
    if args.command=='check':
        _,meta=make_detector(config)
        print(json.dumps(dict(ok=True,model=meta,platform=platform.platform()),indent=2))
    elif args.command=='snapshot':
        import cv2
        camera=Camera(config)
        try:
            time.sleep(config.get('camera_warmup_s',2.))
            _,frame=camera.read(config['camera_timeout_s'])
            if not cv2.imwrite(args.output or 'snapshot.jpg',frame):
                raise RuntimeError('Cannot save snapshot')
        finally:
            camera.close()
    elif args.command=='benchmark':
        if args.samples<=0 or args.seconds<0:
            parser.error('Positive samples and nonnegative seconds required')
        args.output=args.output or 'benchmark.json'
        benchmark(config,args)
    else:
        args.output=args.output or 'logs/'+time.strftime('%Y%m%d-%H%M%S')
        run(config,args)


if __name__=='__main__':
    main()
