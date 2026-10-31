"""Stable file interface for an external device sender. This module does not send HTTP."""
from pathlib import Path
import argparse,hashlib,json,signal,threading,time
from sky_edge.personalization import atomic


def read_source(path,now,limit):
    try:
        value=json.loads(path.read_text())
        age=max(0.,now-float(value['wall_time_unix']))
        fresh=age<=limit and value.get('running',True) and not value.get('error')
        if (path.parent/'run_summary.json').exists():fresh=False
        return dict(available=bool(fresh),age_s=age,source=str(path),data=value)
    except (OSError,ValueError,KeyError,TypeError):
        return dict(available=False,age_s=None,source=str(path),data=None)


class Exporter:
    def __init__(self,logs,output):
        self.logs,self.output=Path(logs),Path(output)
        self.output.mkdir(parents=True,exist_ok=True)
        self.checkpoint=self.output/'export-checkpoint.json'
        try:self.offsets=json.loads(self.checkpoint.read_text())
        except FileNotFoundError:self.offsets={}

    def tick(self,now=None):
        now=time.time() if now is None else now
        candidates=sorted(self.logs.glob('[0-9]*/status.json'))
        video=read_source(candidates[-1],now,3) if candidates else dict(available=False,data=None,age_s=None,source=None)
        audio=read_source(self.logs/'cry/status.json',now,4)
        v=video['data'] or {}
        a=audio['data'] or {}
        result=dict(schema_version='sky-eye.status.v1',wall_time_unix=now,
                    status=v.get('posture_state','unavailable') if video['available'] else 'unavailable',
                    reason=v.get('posture_reason','') if video['available'] else 'video_unavailable',
                    video=video,audio=audio,
                    personalization=a.get('personalization') if audio['available'] else None)
        atomic(self.output/'status.json',result)
        # Checkpoint advances only past complete lines. Stable IDs allow receiver deduplication
        # if a crash occurs after appending but before saving the checkpoint.
        changed=False
        with (self.output/'events.jsonl').open('a',encoding='utf-8') as destination:
            for path in sorted(self.logs.glob('*/events.jsonl')):
                key=path.relative_to(self.logs).as_posix()
                offset=int(self.offsets.get(key,0))
                if path.stat().st_size<offset:raise RuntimeError('Source event file was truncated: '+key)
                with path.open('rb') as source:
                    source.seek(offset)
                    while True:
                        line=source.readline()
                        if not line.endswith(b'\n'):break
                        try:payload=json.loads(line)
                        except ValueError:raise ValueError('Invalid complete event line: '+key)
                        identity=hashlib.sha256(key.encode()+b'\0'+str(offset).encode()+b'\0'+line).hexdigest()
                        kind=payload.get('kind',payload.get('event_type','unknown'))
                        event=dict(schema_version='sky-eye.event.v1',id=identity,source=key,
                                   source_event_id=payload.get('event_id'),kind=kind,
                                   wall_time_unix=payload.get('wall_time_unix'),payload=payload)
                        destination.write(json.dumps(event,ensure_ascii=False,allow_nan=False)+'\n')
                        destination.flush()
                        offset=source.tell()
                        self.offsets[key]=offset
                        changed=True
        if changed:atomic(self.checkpoint,self.offsets)
        return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--logs',default='logs')
    parser.add_argument('--output',default='output')
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    worker=Exporter(args.logs,args.output)
    stop=threading.Event()
    for signum in (signal.SIGTERM,signal.SIGINT):signal.signal(signum,lambda *unused:stop.set())
    while not stop.is_set():
        worker.tick()
        if args.once:break
        stop.wait(.5)

if __name__=='__main__':main()
