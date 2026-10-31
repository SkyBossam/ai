"""L4 fine-tuning with original-class replay and explicit partial-label masks."""
from pathlib import Path
import os, json, time, math, hashlib, traceback, shutil
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
BASE=Path(__file__).resolve().parent
os.environ['YOLO_CONFIG_DIR']=str(BASE/'.ultralytics')
os.environ['YOLO_AUTOINSTALL']='false'

import numpy as np
import torch
import yaml
from ultralytics import YOLO
import ultralytics
from partial_labels import PartialLabelTrainer,PartialLabelValidator,NAMES

BUNDLE=BASE/'bundle'
DATA=BUNDLE/'dataset'
REPORTS=BASE/'reports'
STARTED=time.time()
EPOCH_SECONDS=[]


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.pending')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    os.replace(temporary,path)


def status(phase,**extra):
    value=dict(phase=phase,updated_at_unix=time.time(),started_at_unix=STARTED,**extra)
    dump(BASE/'progress.json',value)


def metrics_summary(metrics):
    box=metrics.box
    classes={}
    for index,cls in enumerate(box.ap_class_index):
        cls=int(cls)
        classes[NAMES[cls]]=dict(precision=float(box.p[index]),recall=float(box.r[index]),
            map50=float(box.ap50[index]),map5095=float(box.ap[index]))
    return dict(overall={k:float(v) for k,v in metrics.results_dict.items()},classes=classes)


def evaluate(weights,data,split,name,classes=None):
    model=YOLO(str(weights))
    result=model.val(validator=PartialLabelValidator,data=str(data),split=split,imgsz=320,batch=16,
        device=0,workers=4,conf=.001,iou=.7,classes=classes,plots=False,verbose=False,
        project=str(REPORTS),name=name,exist_ok=False,rect=False)
    summary=metrics_summary(result)
    dump(REPORTS/f'{name}.json',summary)
    return summary


def attach_progress(model,phase,epochs):
    tick=[None]
    durations=[]
    def begin(trainer):
        tick[0]=time.perf_counter()
    def end(trainer):
        if tick[0] is not None:
            durations.append(time.perf_counter()-tick[0])
        completed=trainer.epoch+1
        estimated=None
        if phase in ('warmup','finetune') and durations:
            rate=float(np.median(durations[-3:]))
            remaining=max(0,epochs-completed)+(60 if phase=='warmup' else 0)
            estimated=rate*remaining+240
        selected={k:float(v) if math.isfinite(float(v)) else None for k,v in trainer.metrics.items()}
        status(phase,epoch=completed,max_epochs=epochs,epoch_seconds=durations[-5:],
               estimated_remaining_seconds=estimated,metrics=selected,save_dir=str(trainer.save_dir))
    model.add_callback('on_train_epoch_start',begin)
    model.add_callback('on_fit_epoch_end',end)


def train(weights,data,phase,epochs,batch=16,freeze=None):
    model=YOLO(str(weights))
    attach_progress(model,phase,epochs)
    status(phase,epoch=0,max_epochs=epochs)
    model.train(trainer=PartialLabelTrainer,data=str(data),imgsz=320,epochs=epochs,batch=batch,device=0,
        workers=2 if phase=='smoke' else 4,optimizer='AdamW',lr0=.0001,lrf=.1,weight_decay=.0005,
        warmup_epochs=1,cos_lr=True,freeze=freeze,patience=15,seed=42,deterministic=True,
        amp=True,cache=False,mosaic=0.,mixup=0.,cutmix=0.,copy_paste=0.,close_mosaic=0,
        fliplr=.5,flipud=0.,degrees=5.,translate=.05,scale=.20,hsv_h=0.,hsv_s=.1,hsv_v=.25,
        project=str(BASE/'runs'),name=phase,exist_ok=False,plots=True,save=True,verbose=False)
    best=Path(model.trainer.best)
    if not best.is_file():
        raise FileNotFoundError('Training completed without best.pt: '+phase)
    reloaded=YOLO(str(best))
    assert type(reloaded.model).__name__=='DetectionModel', 'Checkpoint requires custom training code at inference'
    assert list(reloaded.names.values())==NAMES
    return best


def make_yaml(path,train_path,val_path,test_path):
    spec=dict(path=str(DATA),train=str(train_path),val=str(val_path),test=str(test_path),names=NAMES)
    path.write_text(yaml.safe_dump(spec,sort_keys=False),encoding='utf-8')


def write_list(path,records):
    path.write_text(''.join(str(BUNDLE/r['image'])+'\n' for r in records),encoding='utf-8')


def setup_data():
    records=json.loads((BUNDLE/'manifest.json').read_text())
    for record in records:
        image=BUNDLE/record['image']
        assert image.is_file() and hashlib.sha256(image.read_bytes()).hexdigest()==record['sha256']
    lists=BASE/'lists'
    lists.mkdir()
    for split in ('train','val','test'):
        selected=[r for r in records if r['split']==split]
        write_list(lists/f'{split}.txt',selected)
        for source in ('baby_position','openimages_pillow'):
            write_list(lists/f'{source}_{split}.txt',[r for r in selected if r['source']==source])
        tiny=[]
        for c in range(7):
            candidate=next((r for r in selected if any(int(b[0])==c for b in r['boxes'])),None)
            if candidate and candidate not in tiny:
                tiny.append(candidate)
        limit=16 if split=='train' else 8
        for source in ('openimages_pillow','baby_position'):
            for r in selected:
                if r['source']==source and r not in tiny and len(tiny)<limit:
                    tiny.append(r)
        write_list(lists/f'smoke_{split}.txt',tiny)
    combined=BASE/'data-combined.yaml'
    make_yaml(combined,lists/'train.txt',lists/'val.txt',lists/'test.txt')
    smoke=BASE/'data-smoke.yaml'
    make_yaml(smoke,lists/'smoke_train.txt',lists/'smoke_val.txt',lists/'smoke_test.txt')
    original=BASE/'data-original.yaml'
    make_yaml(original,lists/'baby_position_train.txt',lists/'baby_position_val.txt',lists/'baby_position_test.txt')
    pillow=BASE/'data-pillow.yaml'
    make_yaml(pillow,lists/'openimages_pillow_train.txt',lists/'openimages_pillow_val.txt',lists/'openimages_pillow_test.txt')
    return records,combined,smoke,original,pillow


def export_and_verify(weights,records):
    import cv2,onnxruntime as ort,onnx
    from sleepsafe.detector_onnx import letterbox,postprocess
    export=BASE/'exports/infant_objects_n320'
    export.mkdir(parents=True)
    model=YOLO(str(weights))
    produced=Path(model.export(format='onnx',imgsz=320,batch=1,dynamic=False,half=False,opset=17,
                              nms=False,simplify=False,device='cpu'))
    destination=export/'infant_objects.onnx'
    shutil.copy2(produced,destination)
    onnx.checker.check_model(str(destination))
    options=ort.SessionOptions()
    options.intra_op_num_threads=2
    session=ort.InferenceSession(str(destination),sess_options=options,providers=['CPUExecutionProvider'])
    pt=YOLO(str(weights)).model.cpu().float().eval()
    torch.set_num_threads(2)
    selected=[]
    for source in ('baby_position','openimages_pillow'):
        selected.extend([r for r in records if r['split']=='val' and r['source']==source][:16])
    checks=[]
    for record in selected:
        frame=cv2.imread(str(BUNDLE/record['image']))
        assert frame is not None
        x,ratio,pad=letterbox(frame,320)
        tensor=np.ascontiguousarray(x[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/np.float32(255.)
        with torch.inference_mode():
            raw=pt(torch.from_numpy(tensor))
            raw=raw[0] if isinstance(raw,(tuple,list)) else raw
            raw=raw.cpu().numpy()
        other=session.run(None,{session.get_inputs()[0].name:tensor})[0]
        assert raw.shape==other.shape and raw.shape[1]==11
        raw_pass=bool(np.allclose(raw,other,rtol=1e-3,atol=2e-3))
        a=postprocess(raw,.15,.7,ratio,pad,frame.shape[:2])
        b=postprocess(other,.15,.7,ratio,pad,frame.shape[:2])
        boxes_pass=bool(a[0].shape==b[0].shape and np.array_equal(a[2],b[2])
            and np.allclose(a[0],b[0],atol=.5) and np.allclose(a[1],b[1],atol=1e-3))
        checks.append(dict(image=record['image'],raw_pass=raw_pass,boxes_pass=boxes_pass,
                          max_abs_difference=float(np.max(np.abs(raw-other)))))
    dump(export/'parity_report.json',dict(samples=checks,passed=all(c['raw_pass'] and c['boxes_pass'] for c in checks)))
    assert all(c['raw_pass'] and c['boxes_pass'] for c in checks), 'ONNX parity check failed'
    metadata=dict(classes=NAMES,imgsz=320,input_shape=[1,3,320,320],output_layout='[1,11,2100]',
        architecture='YOLOv8n detect',sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
        source_weights_sha256=hashlib.sha256(Path(weights).read_bytes()).hexdigest(),
        parity_passed=True,partial_labels=True,warning_policy='separate downstream state machines; object risk policy not selected')
    dump(export/'model_meta.json',metadata)
    return destination


def main():
    assert ultralytics.__version__=='8.4.176'
    assert torch.cuda.is_available() and 'L4' in torch.cuda.get_device_name(0)
    REPORTS.mkdir()
    status('checking_inputs')
    records,data,smoke,original,pillow=setup_data()
    baseline=BUNDLE/'baseline/best.pt'
    assert hashlib.sha256(baseline.read_bytes()).hexdigest()=='563ca62ba1e9330d3e8d39d5712721b20ad99550902b4099705e4b2b31e08b25'
    dump(REPORTS/'run_config.json',dict(classes=NAMES,imgsz=320,batch=16,seed=42,
        warmup_epochs=5,finetune_max_epochs=60,patience=15,lr0=.0001,optimizer='AdamW',
        ultralytics=ultralytics.__version__,torch=torch.__version__,gpu=torch.cuda.get_device_name(0),
        partial_label_policy={'baby_position':[0,1,2,3,4,6],'openimages_pillow':[5]},
        interpretation='Research fine-tuning; original infant split has no verified identity/session independence.'))
    status('baseline_validation')
    before=evaluate(baseline,original,'val','baseline_original_val',classes=[0,1,2,3,4])
    train(baseline,smoke,'smoke',2,batch=4,freeze=10)
    warm=train(baseline,data,'warmup',5,freeze=10)
    best=train(warm,data,'finetune',60)
    status('evaluating')
    after=evaluate(best,original,'val','finetuned_original_val',classes=[0,1,2,3,4])
    objects=evaluate(best,pillow,'val','finetuned_pillow_val',classes=[5])
    # Final fixed test evaluations are reported separately and are never used for threshold tuning here.
    old_test=evaluate(best,original,'test','finetuned_original_test',classes=[0,1,2,3,4])
    new_test=evaluate(best,pillow,'test','finetuned_pillow_test',classes=[5])
    joint_test=evaluate(best,data,'test','finetuned_joint_test')
    regression={name:{key:after['classes'][name][key]-before['classes'][name][key]
                for key in ('precision','recall','map50','map5095')} for name in before['classes'] if name in after['classes']}
    dump(REPORTS/'retention_comparison.json',dict(before=before,after=after,delta_by_class=regression,
        scope='same original validation set; raw detector metrics only; event-level warning performance not evaluated'))
    status('exporting')
    onnx_path=export_and_verify(best,records)
    result=dict(completed=True,elapsed_seconds=time.time()-STARTED,best_weights=str(best),onnx=str(onnx_path),
        original_validation=after,pillow_validation=objects,original_test=old_test,pillow_test=new_test,
        joint_test=joint_test,retention_delta_by_class=regression,
        caveats=['Toy has few original validation/test boxes','Infant identity/session independence is not established',
                 'Pi FPS, roll-transition events and real fall/bed-exit performance are not evaluated',
                 'Per-source annotation masks prevent unreviewed classes from becoming negative labels'])
    dump(BASE/'completion.json',result)
    status('complete',result=result)


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        status('failed',error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
        raise
