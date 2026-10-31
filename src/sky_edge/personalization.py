"""Device adapter for the original CryPersonal simulation, with an isolated real profile."""
from pathlib import Path
import argparse,hashlib,json,os,sys,time,uuid
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from cry_personal import CryPersonal,LABEL_KO

ACTIONS=('feed','diaper','hold','unknown','self')


def atomic(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    pending=path.with_name(path.name+'.'+uuid.uuid4().hex+'.pending')
    pending.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')
    pending.replace(path)


def load_personal(config,state=True):
    folder=Path(config.get('artifacts','models/cry-personal'))
    meta=json.loads((folder/'model_meta.json').read_text())
    for name in ('cry_personal_basis.npz','cry_personal_acoustic.npz','cry_personal_ctx.json'):
        if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=meta['files'][name]:
            raise ValueError('Personalization artifact checksum mismatch: '+name)
    state_path=Path(config.get('state_path','state/cry-personal/profile.json')) if state else None
    if state_path:state_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    return CryPersonal(str(folder/'cry_personal_basis.npz'),str(folder/'cry_personal_ctx.json'),
                       state_path=str(state_path) if state_path else None,
                       acoustic_path=str(folder/'cry_personal_acoustic.npz'))


def enqueue(directory,command):
    if not isinstance(command,dict) or command.get('kind') not in ('feedback','feed'):
        raise ValueError('kind must be feedback or feed')
    if command['kind']=='feedback':
        if command.get('action') not in ACTIONS:raise ValueError('Unsupported action')
        try:uuid.UUID(command.get('episode_uid',''))
        except (ValueError,TypeError,AttributeError):raise ValueError('Valid episode_uid required')
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if sum(1 for _ in directory.glob('*.json'))>=100:raise ValueError('Command queue is full')
    command_id=uuid.uuid4().hex
    body={k:command[k] for k in ('kind','action','episode_uid') if k in command}
    body.update(command_id=command_id,created_at=time.time())
    atomic(directory/(command_id+'.json'),body)
    return dict(queued=True,command_id=command_id)


class Personalizer:
    def __init__(self,config):
        self.config=config
        self.personal=load_personal(config)
        self.quiet=0
        self.last_positive=None
        self.last_observation=None
        self.active_uid=None
        self.command_dir=Path(config.get('command_dir','input/cry_commands'))
        self.receipt_dir=self.command_dir.parent/'cry_receipts'

    def commands(self):
        for path in sorted(self.command_dir.glob('*.json'))[:20]:
            receipt=dict(command_id=path.stem,processed_at=time.time(),ok=False)
            try:
                if path.stat().st_size>2048:raise ValueError('Command too large')
                cmd=json.loads(path.read_text())
                if not isinstance(cmd,dict):raise ValueError('Command must be an object')
                created=cmd.get('created_at')
                if not isinstance(created,(float,int)) or not 0<=time.time()-created<=300:
                    raise ValueError('Command expired or timestamp invalid')
                if cmd.get('kind')=='feed':
                    self.personal.log_feed(created)
                elif cmd.get('kind')=='feedback' and cmd.get('action') in ACTIONS:
                    matches=[ep for ep in self.personal.episodes if ep.get('uid')==cmd.get('episode_uid')]
                    if len(matches)!=1 or matches[0].get('end_reason')!='quiet':
                        raise ValueError('Completed cry episode not found')
                    ep=matches[0]
                    if ep['action'] is not None and ep['action']!=cmd['action']:
                        raise ValueError('Feedback already recorded for this episode')
                    if ep['action'] is None:self.personal.feedback(ep['id'],cmd['action'])
                else:raise ValueError('Invalid command')
                receipt['ok']=True
            except (OSError,ValueError,TypeError,KeyError) as exc:
                receipt['error']=str(exc)
            atomic(self.receipt_dir/path.name,receipt)
            path.unlink()

    def finish(self,t,reason):
        if self.personal.cur is None:return None
        number=self.personal.end(t)
        if number is None:return None
        ep=self.personal.episodes[number]
        ep.update(uid=self.active_uid,end_reason=reason)
        self.personal.save()
        self.active_uid=None
        self.quiet=0
        return dict(kind='cry_episode_ended',episode_uid=ep['uid'],end_reason=reason,wall_time_unix=t)

    def step(self,detected,embedding,samples,t,observation_time=None):
        events=[]
        observed=time.monotonic() if observation_time is None else observation_time
        if self.last_observation is not None and observed-self.last_observation>2.5:
            event=self.finish(self.last_positive or t,'input_gap')
            if event:events.append(event)
        self.last_observation=observed
        self.commands()
        if detected:
            if self.personal.cur is None:
                self.personal.start(t)
                self.active_uid=str(uuid.uuid4())
                events.append(dict(kind='cry_episode_started',episode_uid=self.active_uid,wall_time_unix=t))
            self.personal.add_window(embedding,samples)
            self.quiet=0
            self.last_positive=t
            if len(self.personal.cur['embs'])>=self.config.get('max_windows',300):
                event=self.finish(t,'segment_limit')
                if event:events.append(event)
        elif self.personal.cur is not None:
            self.quiet+=1
            if self.quiet>=self.config.get('quiet_windows',3):
                event=self.finish(self.last_positive,'quiet')
                if event:events.append(event)
        return self.status(),events

    def status(self):
        p=self.personal
        n=sum(ep['action'] in p.actions for ep in p.episodes)
        windows=len(p.cur['embs']) if p.cur else 0
        result=dict(experimental=True,simulation=False,n_feedback=n,required_feedback=p.k_min,
                    active_episode_uid=self.active_uid,cry_windows=windows,
                    required_cry_windows=p.hint_seconds,available_actions=list(ACTIONS),recommendations=[],
                    state='insufficient_history' if n<p.k_min else 'collecting_audio' if windows<p.hint_seconds else 'ready',
                    sound_on=False,last_feed_unix=p.last_feed,
                    recent_episodes=[dict(episode_uid=e.get('uid'),started_at=e['t0'],ended_at=e['t1'],action=e['action'])
                                     for e in p.episodes[-5:][::-1] if e.get('end_reason')=='quiet'])
        if not p.cur and n>=p.k_min:result['state']='idle'
        if n>=p.k_min and windows>=p.hint_seconds:
            hint=p.hint()
            result.update(sound_on=hint['sound_on'],recent_validation=hint['recent'])
            if hint['show2']:
                result['recommendations']=[dict(action=a,label=LABEL_KO.get(a,a),score=hint['probs'][a]) for a in hint['top2']]
            elif hint['show']:
                result['recommendations']=[dict(action=hint['top'],label=hint['top_ko'],score=hint['confidence'])]
            else:result['state']='low_confidence'
        return result


def demo(config):
    """Exercise the original algorithm with synthetic feedback; never save to the real profile."""
    p=load_personal(config,state=False)
    rng=np.random.default_rng(67)
    t=1700000000.
    for i in range(10):
        p.start(t+i*1800)
        p.add_window((p.mu+p.sd*rng.normal(0,.1,1024)).astype(np.float32))
        number=p.end(t+i*1800+12)
        p.feedback(number,p.actions[i%3])
    p.start(t+18000)
    for _ in range(10):p.add_window((p.mu+p.sd*rng.normal(0,.1,1024)).astype(np.float32))
    return dict(simulation=True,synthetic_feedback=True,real_profile_modified=False,
                scope='Synthetic demonstration of the original algorithm; no real-cause accuracy measurement',
                hint=p.hint(),feedback_count=10)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['demo','feedback','feed'])
    parser.add_argument('--episode-uid')
    parser.add_argument('--action',choices=ACTIONS)
    parser.add_argument('--config',default='deploy/pi/cry.json')
    parser.add_argument('--output')
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text())['personalization']
    if args.command=='demo':result=demo(config)
    else:
        result=enqueue(config.get('command_dir','input/cry_commands'),dict(
            kind=args.command,episode_uid=args.episode_uid,action=args.action))
    if args.output:atomic(args.output,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
