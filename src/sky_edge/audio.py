"""YAMNet cry scores and optional experimental personalized care hints."""
from pathlib import Path
from collections import deque
import argparse,csv,hashlib,json,queue,signal,subprocess,threading,time,wave
import numpy as np

SR,WINDOW=16000,15600


def write_status(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    pending=path.with_name(path.name+'.pending')
    pending.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    pending.replace(path)


def audio_levels(samples):
    x=np.asarray(samples,dtype=np.float32)
    if not x.size or not np.isfinite(x).all():
        raise ValueError('Finite nonempty audio samples required')
    return dict(rms_dbfs=float(20*np.log10(max(float(np.sqrt(np.mean(x*x))),1e-9))),
                peak=float(np.max(np.abs(x))),clipping_ratio=float(np.mean(np.abs(x)>=.999)))


def summarize_scores(scores,labels,threshold=.3):
    values=np.asarray(scores,dtype=np.float32).reshape(-1)
    if values.shape!=(521,) or not np.isfinite(values).all():
        raise ValueError('Expected 521 finite YAMNet scores')
    baby,general=float(values[20]),float(values[19])
    detected=max(baby,general)>=threshold
    top=np.argsort(values)[-3:][::-1]
    return dict(baby_cry_score=baby,crying_score=general,cry_score=max(baby,general),threshold=threshold,
                cry_detected=bool(detected),baby_cry_detected=bool(baby>=threshold),
                state='baby_cry_candidate' if baby>=threshold else 'cry_candidate' if detected else 'other_or_quiet',
                top_classes=[dict(index=int(i),label=labels[i],score=float(values[i])) for i in top])


class Yamnet:
    def __init__(self,config):
        from tflite_runtime.interpreter import Interpreter
        model=Path(config['model'])
        labels_path=Path(config['class_map'])
        metadata=json.loads(model.with_name('model_meta.json').read_text())
        if hashlib.sha256(model.read_bytes()).hexdigest()!=metadata['sha256']:
            raise ValueError('YAMNet checksum mismatch')
        if hashlib.sha256(labels_path.read_bytes()).hexdigest()!=metadata['class_map_sha256']:
            raise ValueError('YAMNet class map checksum mismatch')
        with labels_path.open(newline='') as source:
            rows=list(csv.DictReader(source))
        self.labels=[row['display_name'] for row in rows]
        assert len(self.labels)==521 and self.labels[19]=='Crying, sobbing' and self.labels[20]=='Baby cry, infant cry'
        self.interpreter=Interpreter(model_path=str(model),num_threads=1)
        self.interpreter.allocate_tensors()
        source=self.interpreter.get_input_details()[0]
        outputs=[o for o in self.interpreter.get_output_details() if int(o['shape'][-1])==521]
        if source['shape'].tolist()!=[WINDOW] or source['dtype']!=np.float32 or len(outputs)!=1:
            raise ValueError('Unsupported YAMNet input/output layout')
        self.input_index,self.output_index=source['index'],outputs[0]['index']
        embeddings=[o for o in self.interpreter.get_output_details() if int(o['shape'][-1])==1024]
        self.embedding_index=embeddings[0]['index'] if len(embeddings)==1 else None
        self.threshold=config['threshold']
        self.sha256=metadata['sha256']

    def predict(self,samples,with_embedding=False):
        samples=np.asarray(samples,dtype=np.float32)
        if samples.shape!=(WINDOW,) or not np.isfinite(samples).all():
            raise ValueError('Expected 15600 mono float32 samples')
        before=time.perf_counter()
        self.interpreter.set_tensor(self.input_index,samples)
        self.interpreter.invoke()
        result=summarize_scores(self.interpreter.get_tensor(self.output_index),self.labels,self.threshold)
        result.update(audio_levels(samples))
        result['inference_ms']=1000*(time.perf_counter()-before)
        if with_embedding:
            if self.embedding_index is None:raise ValueError('Personalization requires a YAMNet embedding output')
            embedding=self.interpreter.get_tensor(self.embedding_index).reshape(-1).copy()
            if embedding.shape!=(1024,) or not np.isfinite(embedding).all():
                raise ValueError('Expected finite 1024-dimensional YAMNet embedding')
            return result,embedding
        return result


class PCMInput:
    """Keep the latest one-second microphone blocks; never save raw audio."""
    def __init__(self,device):
        self.blocks=queue.Queue(maxsize=2)
        self.messages=deque(maxlen=6)
        self.stopping=threading.Event()
        self.error=None
        self.dropped=0
        self.process=subprocess.Popen(['arecord','-q','-D',device,'-f','S16_LE','-c','1','-r',str(SR),'-t','raw'],
                                      stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
        threading.Thread(target=self._stderr,daemon=True).start()
        self.thread=threading.Thread(target=self._read,daemon=True)
        self.thread.start()

    def _stderr(self):
        for line in iter(self.process.stderr.readline,b''):
            self.messages.append(line.decode('utf-8','replace').strip())

    def _read(self):
        buffer=bytearray()
        try:
            while not self.stopping.is_set():
                chunk=self.process.stdout.read(4096)
                if not chunk:
                    if not self.stopping.is_set():
                        self.error='Microphone stream closed: '+'; '.join(self.messages)
                    return
                buffer.extend(chunk)
                while len(buffer)>=SR*2:
                    samples=np.frombuffer(bytes(buffer[:SR*2]),dtype='<i2').astype(np.float32)/np.float32(32768.)
                    del buffer[:SR*2]
                    if self.blocks.full():
                        try:self.blocks.get_nowait();self.dropped+=1
                        except queue.Empty:pass
                    self.blocks.put_nowait((time.monotonic(),samples))
        except Exception as exc:
            if not self.stopping.is_set():self.error=str(exc)

    def close(self):
        self.stopping.set()
        self.process.terminate()
        try:self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.thread.join(timeout=2)
        self.process.stdout.close()
        self.process.stderr.close()


def live(config,args):
    model=Yamnet(config)
    personal=None
    if config.get('personalization',{}).get('enabled'):
        from sky_edge.personalization import Personalizer
        personal=Personalizer(config['personalization'])
        if model.embedding_index is None:raise ValueError('Embedding model required for personalized hints')
    microphone=PCMInput(config['device'])
    stop=threading.Event()
    for signum in (signal.SIGINT,signal.SIGTERM):
        signal.signal(signum,lambda *unused:stop.set())
    started=time.monotonic()
    last_sample=started
    count=0
    previous=False
    failed=False
    path=Path(config['status_path'])
    path.parent.mkdir(parents=True,exist_ok=True)
    write_status(path,dict(state='starting',running=True,wall_time_unix=time.time(),device=config['device']))
    try:
        with path.with_name('events.jsonl').open('a') as events:
            while not stop.is_set() and (args.seconds<=0 or time.monotonic()-started<args.seconds):
                if microphone.error:
                    raise RuntimeError(microphone.error)
                try:timestamp,samples=microphone.blocks.get(timeout=.2)
                except queue.Empty:
                    if time.monotonic()-last_sample>5:raise TimeoutError('No fresh microphone samples')
                    continue
                last_sample=time.monotonic()
                before=time.perf_counter()
                personal_events=[]
                if personal:
                    result,embedding=model.predict(samples[:WINDOW],with_embedding=True)
                    hint,personal_events=personal.step(result['cry_detected'],embedding,samples[:WINDOW],time.time(),timestamp)
                    result['personalization']=hint
                else:result=model.predict(samples[:WINDOW])
                count+=1
                result.update(running=True,wall_time_unix=time.time(),windows=count,sample_rate=SR,
                              window_samples=WINDOW,device=config['device'],audio_age_s=time.monotonic()-timestamp,
                              dropped_windows=microphone.dropped,model_sha256=model.sha256,
                              processing_ms=(time.perf_counter()-before)*1000,
                              scope='Experimental care hints, not confirmed causes' if personal else 'Cry-presence test')
                write_status(path,result)
                for event in personal_events:
                    events.write(json.dumps(event,ensure_ascii=False)+'\n');events.flush()
                if result['cry_detected']!=previous:
                    event=dict(kind='cry_candidate_started' if result['cry_detected'] else 'cry_candidate_ended',
                               wall_time_unix=time.time(),baby_cry_score=result['baby_cry_score'],crying_score=result['crying_score'])
                    events.write(json.dumps(event)+'\n');events.flush()
                previous=result['cry_detected']
                if args.print_status:print(json.dumps(result),flush=True)
    except Exception as exc:
        failed=True
        write_status(path,dict(state='error',running=False,error=str(exc),wall_time_unix=time.time()))
        raise
    finally:
        microphone.close()
        if personal:
            personal.finish(time.time(),'service_stopped')
        if not failed:write_status(path,dict(state='stopped',running=False,wall_time_unix=time.time(),windows=count))


def classify_file(config,args):
    model=Yamnet(config)
    with wave.open(str(args.wav)) as source:
        if (source.getframerate(),source.getnchannels(),source.getsampwidth())!=(SR,1,2):
            raise ValueError('File test requires 16 kHz mono PCM16 WAV')
        samples=np.frombuffer(source.readframes(source.getnframes()),'<i2').astype(np.float32)/32768.
    if len(samples)<WINDOW:samples=np.pad(samples,(0,WINDOW-len(samples)))
    results=[model.predict(samples[start:start+WINDOW]) for start in range(0,len(samples)-WINDOW+1,SR)]
    result=dict(file=str(args.wav),windows=len(results),cry_windows=sum(r['cry_detected'] for r in results),
                max_baby_cry_score=max(r['baby_cry_score'] for r in results),predictions=results)
    if args.output:write_status(args.output,result)
    print(json.dumps(result,indent=2))


def watch(config):
    try:
        while True:
            try:
                state=json.loads(Path(config['status_path']).read_text())
                age=max(0,time.time()-state.get('wall_time_unix',0))
                top=state.get('top_classes',[{}])[0].get('label','-')
                print(f"{time.strftime('%H:%M:%S')} age={age:.1f}s state={state['state']} "
                      f"baby_cry={state.get('baby_cry_score',0):.3f} crying={state.get('crying_score',0):.3f} "
                      f"level={state.get('rms_dbfs',-180):.1f}dBFS top={top} {state.get('error','')}",flush=True)
            except (OSError,ValueError):print('Waiting for cry test. Run: bash ~/sky-eye/cry-start.sh',flush=True)
            time.sleep(1)
    except KeyboardInterrupt:pass


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['live','file','watch'])
    parser.add_argument('--config',default='deploy/pi/cry.json')
    parser.add_argument('--seconds',type=float,default=0.)
    parser.add_argument('--wav',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--print-status',action='store_true')
    args=parser.parse_args()
    if args.seconds<0:parser.error('--seconds must be nonnegative')
    config=json.loads(Path(args.config).read_text())
    if not 0<=config['threshold']<=1:parser.error('Threshold must be in [0,1]')
    if args.command=='live':live(config,args)
    elif args.command=='file':
        if args.wav is None:parser.error('--wav is required')
        classify_file(config,args)
    else:watch(config)

if __name__=='__main__':main()
