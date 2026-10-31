"""ARM NEON optimized FP32 inference with the same YOLO decoder."""
from pathlib import Path
import numpy as np
from sleepsafe.detector_onnx import letterbox,postprocess
from sleepsafe.decision import Detection


class NCNNDetector:
    def __init__(self,path,names,conf=.15,iou=.7,threads=4):
        import ncnn
        self.ncnn=ncnn
        self.net=ncnn.Net()
        self.net.opt.num_threads=int(threads)
        self.net.opt.use_vulkan_compute=False
        self.net.opt.use_fp16_packed=False
        self.net.opt.use_fp16_storage=False
        self.net.opt.use_fp16_arithmetic=False
        self.net.opt.use_bf16_storage=False
        self.net.opt.use_int8_inference=False
        root=Path(path).parent
        if self.net.load_param(str(root/'model.ncnn.param'))!=0 or self.net.load_model(str(root/'model.ncnn.bin'))!=0:
            raise RuntimeError('NCNN model could not be loaded')
        self.names=list(names)
        self.conf,self.iou,self.imgsz=conf,iou,320

    def raw(self,tensor):
        with self.net.create_extractor() as extractor:
            code=extractor.input('in0',self.ncnn.Mat(np.ascontiguousarray(tensor[0])).clone())
            if code!=0:
                raise RuntimeError('NCNN input failed')
            code,result=extractor.extract('out0')
            if code!=0:
                raise RuntimeError('NCNN output failed')
            output=np.array(result,copy=True)[None]
        if output.shape!=(1,4+len(self.names),2100) or not np.isfinite(output).all():
            raise ValueError('Invalid NCNN model output: '+str(output.shape))
        return output

    def __call__(self,frame):
        image,ratio,pad=letterbox(frame,self.imgsz)
        tensor=np.ascontiguousarray(image[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/np.float32(255.)
        boxes,scores,classes=postprocess(self.raw(tensor),self.conf,self.iou,ratio,pad,frame.shape[:2])
        return [Detection(self.names[int(c)],float(score),tuple(float(v) for v in box))
                for box,score,c in zip(boxes,scores,classes)]
