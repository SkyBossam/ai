"""Build a checksummed SSH deployment archive; weights are kept outside Git."""
from pathlib import Path
import argparse,hashlib,json,shutil,sys,tarfile,tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--model',type=Path,required=True)
    p.add_argument('--meta',type=Path)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--tag',default='sky-eye-pi')
    p.add_argument('--backend',choices=['onnxruntime','opencv','ncnn'],default='onnxruntime')
    p.add_argument('--ncnn-dir',type=Path)
    p.add_argument('--extra-ncnn-dir',type=Path)
    p.add_argument('--extra-model',type=Path)
    p.add_argument('--extra-meta',type=Path)
    p.add_argument('--integrated',action='store_true',help='Include cry personalization, feedback, simulation and stable file export')
    args=p.parse_args()
    if args.backend=='ncnn' and (not args.ncnn_dir or (args.extra_model and not args.extra_ncnn_dir)):
        p.error('NCNN backend requires converted model directories')
    if args.out.exists():
        raise FileExistsError(args.out)
    if '/' in args.tag or '\\' in args.tag or args.tag in ('.','..'):
        p.error('Tag must be a directory name')
    import onnxruntime as ort
    import ast,numpy as np
    opts=ort.SessionOptions()
    opts.intra_op_num_threads=2
    session=ort.InferenceSession(str(args.model),sess_options=opts,providers=['CPUExecutionProvider'])
    names=list(ast.literal_eval(session.get_modelmeta().custom_metadata_map['names']).values())
    if names not in (['supine','side','prone','airway_visible','airway_covered'],
                    ['supine','side','prone','airway_visible','airway_covered','pillow','toy']):
        raise ValueError('Unsupported model names/order')
    assert session.get_inputs()[0].shape==[1,3,320,320]
    raw=session.run(None,{session.get_inputs()[0].name:np.zeros((1,3,320,320),np.float32)})[0]
    assert raw.shape==(1,4+len(names),2100) and np.isfinite(raw).all()
    digest=hashlib.sha256(args.model.read_bytes()).hexdigest()
    meta=json.loads(args.meta.read_text()) if args.meta else dict(parity_passed=False,
        provenance='Original A_original_320_aug ONNX from user model archive',
        validation_scope='ONNX shape/finite output and shared-policy integration; PT parity not established by this build')
    if args.meta and meta['sha256']!=digest:
        raise ValueError('Supplied metadata checksum mismatch')
    meta.update(classes=names,sha256=digest,imgsz=320,input_shape=[1,3,320,320],
                onnx_cpu_smoke_passed=True,pi_hardware_benchmarked=False)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.out.parent) as tmp:
        stage=Path(tmp)/args.tag
        stage.mkdir()
        for folder in ('sky_edge','sleepsafe','camera_fall'):
            shutil.copytree(ROOT/'src'/folder,stage/'src'/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copytree(ROOT/'deploy/pi',stage/'deploy/pi',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        guide=stage/'deploy/pi/SSH_DEPLOY.md'
        guide.write_text(guide.read_text(encoding='utf-8').replace('sky-eye-pi-baseline',args.tag),encoding='utf-8')
        config_path=stage/'deploy/pi/config.json'
        config=json.loads(config_path.read_text())
        config['inference_backend']=args.backend
        config_path.write_text(json.dumps(config,indent=2)+'\n')
        if args.extra_model:
            if not args.extra_meta:
                p.error('--extra-meta is required with --extra-model')
            extra_meta=json.loads(args.extra_meta.read_text())
            assert extra_meta['parity_passed'] and hashlib.sha256(args.extra_model.read_bytes()).hexdigest()==extra_meta['sha256']
            extra=stage/'models/objects/model.onnx'
            extra.parent.mkdir(parents=True)
            shutil.copy2(args.extra_model,extra)
            extra.with_name('model_meta.json').write_text(json.dumps(extra_meta,indent=2)+'\n')
            objects_config=dict(config,model='models/objects/model.onnx')
            (stage/'deploy/pi/config.objects.json').write_text(json.dumps(objects_config,indent=2)+'\n')
        (stage/'configs').mkdir()
        shutil.copy2(ROOT/'configs/risk_r0.yaml',stage/'configs/risk_r0.yaml')
        shutil.copy2(ROOT/'LICENSE',stage/'LICENSE')
        shutil.copy2(ROOT/'requirements.txt',stage/'requirements.txt')
        model=stage/'models/infant/model.onnx'
        model.parent.mkdir(parents=True)
        shutil.copy2(args.model,model)
        model.with_name('model_meta.json').write_text(json.dumps(meta,indent=2)+'\n')
        if args.backend=='ncnn':
            pairs=[(args.ncnn_dir,model.parent,digest)]
            if args.extra_model:
                pairs.append((args.extra_ncnn_dir,stage/'models/objects',extra_meta['sha256']))
            for source,destination,original_sha in pairs:
                conversion=json.loads((source/'ncnn_meta.json').read_text())
                assert conversion['source_onnx_sha256']==original_sha and conversion['parity_passed']
                for name,expected in conversion['files'].items():
                    assert Path(name).name==name and hashlib.sha256((source/name).read_bytes()).hexdigest()==expected
                    shutil.copy2(source/name,destination/name)
                shutil.copy2(source/'ncnn_meta.json',destination/'ncnn_meta.json')
            config['threads']=4
            config['camera_warmup_s']=2.
            config_path.write_text(json.dumps(config,indent=2)+'\n')
            if args.extra_model:
                objects_config=dict(config,model='models/objects/model.onnx')
                (stage/'deploy/pi/config.objects.json').write_text(json.dumps(objects_config,indent=2)+'\n')
        if args.integrated:
            shutil.copy2(ROOT/'cry_personal.py',stage/'cry_personal.py')
            for folder in ('sim','assets'):
                shutil.copytree(ROOT/folder,stage/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            for folder in ('cry','cry-personal'):
                shutil.copytree(ROOT/'models'/folder,stage/'models'/folder)
            (stage/'docs').mkdir(exist_ok=True)
            shutil.copy2(ROOT/'docs/PI_INTEGRATION.md',stage/'docs/PI_INTEGRATION.md')
            (stage/'tests').mkdir()
            for name in ('test_audio.py','test_preview.py','test_personalization.py'):
                shutil.copy2(ROOT/'tests'/name,stage/'tests'/name)
            for path in (stage/'deploy/pi').glob('config*.json'):
                c=json.loads(path.read_text());c['preview_port']=8765
                path.write_text(json.dumps(c,indent=2)+'\n')
            # Ensure an unpacked bundle contains runnable examples even before installation.
            sys.path.insert(0,str(ROOT))
            from sky_edge.personalization import demo
            simulated=demo(dict(artifacts=str(ROOT/'models/cry-personal')))
            (stage/'assets/cause-demo.json').write_text(json.dumps(simulated,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            report=ROOT.parent/'output/pi-personal-20261101/personal-deployment.json'
            if report.exists():
                (stage/'reports').mkdir(exist_ok=True)
                shutil.copy2(report,stage/'reports/validated-device.json')
        checks={str(f.relative_to(stage)).replace('\\','/'):hashlib.sha256(f.read_bytes()).hexdigest()
                for f in stage.rglob('*') if f.is_file()}
        (stage/'SHA256SUMS').write_text(''.join(f'{checksum}  {name}\n' for name,checksum in sorted(checks.items())))
        (stage/'release.json').write_text(json.dumps(dict(tag=args.tag,model=meta,
            contents='Inference code, model, configuration, installer; no training data or credentials',
            camera_and_geometry_require_on_device_setup=True),indent=2)+'\n')
        args.out.parent.mkdir(parents=True,exist_ok=True)
        with tarfile.open(args.out,'w:gz') as archive:
            archive.add(stage,arcname=args.tag)
    args.out.with_suffix(args.out.suffix+'.sha256').write_text(hashlib.sha256(args.out.read_bytes()).hexdigest()+'  '+args.out.name+'\n')
    print(json.dumps(dict(archive=str(args.out.resolve()),bytes=args.out.stat().st_size,classes=names,
                         model_sha256=digest),indent=2))

if __name__=='__main__':
    main()
