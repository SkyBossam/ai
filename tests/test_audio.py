from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
from sky_edge.audio import audio_levels,summarize_scores

class AudioTests(unittest.TestCase):
    def test_cry_and_baby_cry_are_distinguished(self):
        scores=np.zeros(521,np.float32)
        labels=[str(i) for i in range(521)]
        scores[19]=.7
        out=summarize_scores(scores,labels)
        self.assertTrue(out['cry_detected'])
        self.assertFalse(out['baby_cry_detected'])
        self.assertEqual(out['state'],'cry_candidate')
        scores[20]=.9
        out=summarize_scores(scores,labels)
        self.assertEqual(out['state'],'baby_cry_candidate')
        self.assertEqual(out['top_classes'][0]['index'],20)

    def test_silence_levels_and_invalid_audio(self):
        self.assertEqual(audio_levels(np.zeros(16000,np.float32))['rms_dbfs'],-180.)
        with self.assertRaises(ValueError):audio_levels([float('nan')])
        with self.assertRaises(ValueError):audio_levels([])

    def test_model_shape_is_not_silently_misinterpreted(self):
        with self.assertRaises(ValueError):summarize_scores(np.zeros(1024),['x']*1024)
        scores=np.zeros(521);scores[0]=float('nan')
        with self.assertRaises(ValueError):summarize_scores(scores,['x']*521)

if __name__=='__main__':unittest.main()
