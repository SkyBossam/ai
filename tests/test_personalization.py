from pathlib import Path
import json,sys,tempfile,time,unittest,uuid
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sky_edge.personalization import Personalizer,atomic,demo,enqueue
from sky_edge.export import Exporter


class PersonalTests(unittest.TestCase):
    def config(self,folder):
        return dict(artifacts=str(ROOT/'models/cry-personal'),state_path=str(folder/'state/profile.json'),
                    command_dir=str(folder/'input/cry_commands'))

    def test_cold_start_real_feedback_and_isolated_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);config=self.config(folder);worker=Personalizer(config)
            e=np.zeros(1024,np.float32);t=time.time()-40
            for i in range(10):s,_=worker.step(True,e,None,t+i,i)
            self.assertEqual(s['recommendations'],[])
            self.assertEqual(s['state'],'insufficient_history')
            worker.step(False,e,None,t+10,10)
            worker.step(False,e,None,t+11,11)
            self.assertEqual(len(worker.personal.episodes),0)
            s,_=worker.step(False,e,None,t+12,12)
            uid=s['recent_episodes'][0]['episode_uid']
            receipt=enqueue(config['command_dir'],dict(kind='feedback',episode_uid=uid,action='hold'))
            worker.commands()
            self.assertTrue(json.loads((worker.receipt_dir/(receipt['command_id']+'.json')).read_text())['ok'])
            self.assertEqual(worker.status()['n_feedback'],1)
            original=Path(config['state_path']).read_bytes()
            output=demo(config)
            self.assertTrue(output['simulation'])
            self.assertTrue(output['hint']['show2'])
            self.assertEqual(Path(config['state_path']).read_bytes(),original)
            restored=Personalizer(config)
            self.assertEqual(restored.status()['n_feedback'],1)

    def test_bad_feedback_cannot_modify_real_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.config(Path(tmp));worker=Personalizer(config)
            with self.assertRaises(ValueError):enqueue(config['command_dir'],dict(kind='feedback',episode_uid='-1',action='feed'))
            receipt=enqueue(config['command_dir'],dict(kind='feedback',episode_uid=str(uuid.uuid4()),action='feed'))
            worker.commands()
            record=json.loads((worker.receipt_dir/(receipt['command_id']+'.json')).read_text())
            self.assertFalse(record['ok'])
            self.assertIsNone(worker.personal.last_feed)

    def test_input_gap_cannot_become_completed_feedback_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker=Personalizer(self.config(Path(tmp)))
            e=np.zeros(1024,np.float32)
            worker.step(True,e,None,100,0)
            state,events=worker.step(False,e,None,110,10)
            self.assertEqual(events[0]['end_reason'],'input_gap')
            self.assertEqual(state['recent_episodes'],[])


class ExportTests(unittest.TestCase):
    def test_stale_is_unavailable_and_events_resume_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);logs=root/'logs';folder=logs/'20261101-000001';folder.mkdir(parents=True)
            atomic(folder/'status.json',dict(wall_time_unix=100,posture_state='normal',posture_reason=''))
            atomic(logs/'cry/status.json',dict(wall_time_unix=100,running=True,personalization=dict(n_feedback=0)))
            event=folder/'events.jsonl'
            event.write_text('{"kind":"risk_started","event_id":"same-episode"}\n')
            output=root/'output'
            s=Exporter(logs,output).tick(101)
            self.assertEqual(s['status'],'normal')
            self.assertEqual(s['personalization']['n_feedback'],0)
            first=(output/'events.jsonl').read_text()
            worker=Exporter(logs,output);s=worker.tick(110)
            self.assertEqual(s['status'],'unavailable')
            self.assertIsNone(s['personalization'])
            self.assertEqual((output/'events.jsonl').read_text(),first)
            with event.open('a') as dest:dest.write('{"kind":"risk_ended"')
            worker.tick(111)
            self.assertEqual((output/'events.jsonl').read_text(),first)
            with event.open('a') as dest:dest.write('}\n')
            worker.tick(112)
            lines=(output/'events.jsonl').read_text().splitlines()
            self.assertEqual(len(lines),2)
            self.assertNotEqual(json.loads(lines[0])['id'],json.loads(lines[1])['id'])

if __name__=='__main__':unittest.main()
