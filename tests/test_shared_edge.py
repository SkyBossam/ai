import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
from sleepsafe.decision import Detection
from sky_edge.pipeline import SharedPipeline

ROOT=Path(__file__).resolve().parents[1]
import json,yaml
CONFIG=json.loads((ROOT/'deploy/pi/config.json').read_text())
G=dict(coordinate_system='normalized_image_xy',reference_width=320,reference_height=320,
       calibration_valid=True,bed_polygon=[[.1,.1],[.9,.1],[.9,.9],[.1,.9]],
       boundaries=[dict(id='right',type='open',points=[[.9,.1],[.9,.9]])])
P=yaml.safe_load((ROOT/'configs/risk_r0.yaml').read_text())

class Fake:
    def __init__(self):
        self.calls=0
        self.items=[]
    def __call__(self,frame):
        self.calls+=1
        return self.items

def body(cls='prone',cx=240,conf=.95):
    return Detection(cls,conf,(cx-30,120,cx+30,200))

class SharedTests(unittest.TestCase):
    def setUp(self):
        self.detector=Fake()
        self.pipeline=SharedPipeline(self.detector,copy.deepcopy(G),P,CONFIG)
        self.frame=np.full((320,320,3),120,np.uint8)

    def test_single_forward_independent_risks_and_duplicate_body(self):
        events=[]
        for i in range(31):
            ts=i*.2
            cx=240+ts*8
            self.detector.items=[body(cx=cx),body('supine',cx,.85),
                Detection('airway_visible',.9,(cx-8,130,cx+8,150)),
                Detection('pillow',.99,(20,20,50,50))]
            result=self.pipeline.step(self.frame,ts)
            events+=result['events']
            self.assertTrue(result['posture']['valid'])
        self.assertEqual(self.detector.calls,31)
        a=[e for e in events if e['branch']=='fall' and e.get('event_type')=='risk_started']
        b=[e for e in events if e['branch']=='posture' and e['kind']=='risk_started']
        self.assertEqual(len(a),1)
        self.assertEqual(len(b),1)
        self.assertLess(a[0]['video_ts_s'],b[0]['ts'])
        self.assertAlmostEqual(b[0]['ts'],5)

    def test_ambiguous_infants_not_guessed(self):
        self.detector.items=[body(cx=80),body(cx=240)]
        result=self.pipeline.step(self.frame,0)
        self.assertFalse(result['posture']['valid'])
        self.assertEqual(result['posture']['reason'],'ambiguous_bodies')
        self.assertFalse(result['fall']['observation_valid'])

    def test_long_gap_does_not_confirm_prone(self):
        self.detector.items=[body()]
        self.pipeline.step(self.frame,0)
        result=self.pipeline.step(self.frame,6)
        self.assertFalse(any(e.get('kind')=='risk_started' for e in result['events']))

    def test_slow_frames_do_not_share_the_two_policies_gap_limits(self):
        self.detector.items=[body()]
        events=[]
        for i in range(9):
            events+=self.pipeline.step(self.frame,i*.8)['events']
        self.assertTrue(any(e.get('kind')=='risk_started' and e.get('risk_type')=='prone' for e in events))
        self.assertFalse(any(e.get('event_type')=='risk_started' for e in events))

    def test_uncalibrated_or_changed_aspect_disables_edge_only(self):
        self.pipeline.geometry['calibration_valid']=False
        self.detector.items=[body()]
        result=self.pipeline.step(self.frame,0)
        self.assertFalse(result['geometry_valid'])
        self.assertTrue(result['posture']['valid'])
        self.assertFalse(result['fall']['observation_valid'])

    def test_active_risk_persists_during_missing_frames(self):
        self.detector.items=[body()]
        for i in range(27):
            self.pipeline.step(self.frame,i*.2)
        self.detector.items=[]
        result=self.pipeline.step(self.frame,7)
        self.assertEqual(result['posture_state'],'risk')
        self.assertFalse(any(e.get('kind')=='risk_ended' for e in result['events']))

    def test_objects_do_not_become_body_or_risk(self):
        self.detector.items=[Detection('pillow',.99,(100,100,200,200))]
        result=self.pipeline.step(self.frame,0)
        self.assertFalse(result['posture']['valid'])
        self.assertFalse(result['fall']['observation_valid'])

    def test_invalid_body_boxes_are_dropped(self):
        self.detector.items=[Detection('prone',.99,(20,20,20,30)),
                             Detection('supine',float('nan'),(20,20,30,30))]
        result=self.pipeline.step(self.frame,0)
        self.assertFalse(result['posture']['valid'])

    def test_actual_onnx_runtime_five_and_seven_class_models(self):
        import tempfile,onnx
        from onnx import helper,TensorProto,numpy_helper
        from sleepsafe.detector_onnx import OnnxDetector
        names=['supine','side','prone','airway_visible','airway_covered','pillow','toy']
        with tempfile.TemporaryDirectory() as tmp:
            for count in (5,7):
                values=np.zeros((1,4+count,2),np.float32)
                values[0,:4,:]=[[240,240],[160,140],[60,20],[80,20]]
                values[0,6,0]=.95
                values[0,7,1]=.9
                graph=helper.make_graph([helper.make_node('Constant',[],['output'],value=numpy_helper.from_array(values))],
                     'fixture',[helper.make_tensor_value_info('images',TensorProto.FLOAT,[1,3,320,320])],
                     [helper.make_tensor_value_info('output',TensorProto.FLOAT,[1,4+count,2])])
                model=helper.make_model(graph,opset_imports=[helper.make_opsetid('',17)])
                model.ir_version=9
                helper.set_model_props(model,{'names':str(dict(enumerate(names[:count]))),'imgsz':'[320,320]'})
                path=Path(tmp)/f'model-{count}.onnx'
                onnx.save(model,path)
                detector=OnnxDetector(path,conf=.15,threads=1)
                calls=[]
                def count_forward(frame):
                    calls.append(1)
                    return detector(frame)
                pipeline=SharedPipeline(count_forward,copy.deepcopy(G),P,CONFIG)
                events=[]
                for i in range(26):
                    events+=pipeline.step(self.frame,i*.2)['events']
                self.assertEqual(len(calls),26)
                self.assertTrue(any(e.get('risk_type')=='prone' and e.get('kind')=='risk_started' for e in events))

if __name__=='__main__':
    unittest.main()
