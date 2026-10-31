from pathlib import Path
import sys,json,unittest,urllib.request,urllib.error,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np,cv2
from sky_edge.preview import PreviewServer,annotate,visible_detections
from sky_edge.watch import format_status

CONFIG=dict(body_confidence=.2,airway_confidence=.15,object_confidence=.25)

class PreviewTests(unittest.TestCase):
    def test_feedback_queue_and_cross_origin_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            server=PreviewServer(0,dict(CONFIG,cry_command_dir=str(Path(tmp)/'commands')))
            base='http://127.0.0.1:'+str(server.port)
            try:
                body=json.dumps(dict(kind='feed')).encode()
                req=urllib.request.Request(base+'/api/cry/command',data=body,headers={'Content-Type':'application/json','Origin':'https://example.com'})
                with self.assertRaises(urllib.error.HTTPError) as failure:urllib.request.urlopen(req,timeout=3)
                self.assertEqual(failure.exception.code,400)
                self.assertEqual(list(Path(tmp).rglob('*.json')),[])
                req=urllib.request.Request(base+'/api/cry/command',data=body,headers={'Content-Type':'application/json','Origin':base})
                with urllib.request.urlopen(req,timeout=3) as response:
                    self.assertEqual(response.status,202)
                    self.assertTrue(json.load(response)['queued'])
                self.assertEqual(len(list(Path(tmp).rglob('*.json'))),1)
            finally:server.close()

    def test_thresholds_and_boxes_are_the_same_detections(self):
        state=dict(detections=[dict(cls='prone',conf=.9,xyxy=[40,40,90,90]),
                               dict(cls='pillow',conf=.2,xyxy=[100,50,150,100])],posture_state='caution')
        self.assertEqual(len(visible_detections(state,CONFIG)),1)
        frame=np.zeros((160,200,3),np.uint8)
        result=annotate(frame,state,CONFIG)
        self.assertTrue(np.array_equal(frame,np.zeros_like(frame)))
        self.assertTrue(np.any(result[40,40]))

    def test_http_image_status_and_stream(self):
        server=PreviewServer(0,CONFIG)
        try:
            self.assertEqual(server.server.server_address[0],'127.0.0.1')
            state=dict(detections=[],posture_state='unavailable',posture_reason='no_baby',model_classes=['supine'])
            server.publish(np.full((160,200,3),100,np.uint8),state,[dict(kind='status_changed')])
            base='http://127.0.0.1:'+str(server.port)
            with urllib.request.urlopen(base+'/api/status',timeout=3) as response:
                payload=json.load(response)
            self.assertEqual(payload['posture_reason'],'no_baby')
            self.assertEqual(payload['recent_events'][0]['kind'],'status_changed')
            with urllib.request.urlopen(base+'/frame.jpg',timeout=3) as response:
                self.assertEqual(response.headers['Content-Type'],'image/jpeg')
                image=cv2.imdecode(np.frombuffer(response.read(),np.uint8),cv2.IMREAD_COLOR)
            self.assertEqual(image.shape,(160,200,3))
            with urllib.request.urlopen(base+'/stream',timeout=3) as response:
                self.assertEqual(response.readline(),b'--frame\r\n')
                self.assertIn(b'image/jpeg',response.readline())
            with urllib.request.urlopen(base,timeout=3) as response:
                self.assertIn('Sky Eye',response.read().decode())
        finally:
            server.close()

    def test_terminal_summary(self):
        text=format_status(dict(posture=dict(posture='prone'),posture_state='caution',
                                detections=[dict(cls='prone',conf=.92)],processing_fps=5),.2)
        self.assertIn('posture=prone',text)
        self.assertIn('prone 0.92',text)
        self.assertIn('fps=5.0',text)

if __name__=='__main__':
    unittest.main()
