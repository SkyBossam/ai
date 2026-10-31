"""Compare the ARMv7 DNN runtime with frozen ONNX Runtime reference inputs."""
from pathlib import Path
import argparse,hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
import numpy as np
from sky_edge.detector_opencv import OpenCVDetector
from sleepsafe.detector_onnx import postprocess

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--model',type=Path,required=True)
    p.add_argument('--fixtures',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--backend',choices=['opencv','ncnn'],default='opencv')
    args=p.parse_args()
    meta=json.loads(args.model.with_name('model_meta.json').read_text())
    manifest=json.loads((args.fixtures/'manifest.json').read_text())
    assert hashlib.sha256(args.model.read_bytes()).hexdigest()==manifest['model_sha256']==meta['sha256']
    if args.backend=='ncnn':
        from sky_edge.detector_ncnn import NCNNDetector
        detector=NCNNDetector(args.model,meta['classes'],threads=4)
    else:
        detector=OpenCVDetector(args.model,meta['classes'],threads=2)
    checks=[]
    for name in manifest['samples']:
        with np.load(args.fixtures/name) as data:
            raw=detector.raw(data['tensor'])
            expected=data['expected']
            a=postprocess(expected,.15,.7,float(data['ratio']),data['pad'],data['shape'])
            b=postprocess(raw,.15,.7,float(data['ratio']),data['pad'],data['shape'])
            raw_ok=bool(np.allclose(raw,expected,rtol=1e-3,atol=2e-3))
            boxes_ok=bool(a[0].shape==b[0].shape and np.array_equal(a[2],b[2]) and
                          np.allclose(a[0],b[0],atol=.5) and np.allclose(a[1],b[1],atol=1e-3))
            checks.append(dict(sample=name,raw_passed=raw_ok,boxes_passed=boxes_ok,
                               maximum_raw_abs_difference=float(np.max(np.abs(raw-expected)))))
    assert checks
    report=dict(passed=all(c['raw_passed'] and c['boxes_passed'] for c in checks),samples=checks,
                backend=args.backend,scope=args.backend+' versus ONNX Runtime numerical and postprocessing parity; not accuracy',
                model_sha256=meta['sha256'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    assert report['passed']

if __name__=='__main__':
    main()
