"""ONNX inference on 32-bit Raspberry Pi OS through OpenCV DNN."""
import cv2
import numpy as np
from sleepsafe.detector_onnx import letterbox,postprocess
from sleepsafe.decision import Detection


class OpenCVDetector:
    def __init__(self,path,names,conf=.15,iou=.7,threads=2):
        cv2.setNumThreads(int(threads))
        self.net=cv2.dnn.readNetFromONNX(str(path))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        if hasattr(self.net,'enableWinograd'):
            self.net.enableWinograd(False)
        self.names=list(names)
        self.conf,self.iou,self.imgsz=conf,iou,320

    def raw(self,tensor):
        self.net.setInput(tensor)
        output=self.net.forward()
        if output.shape!=(1,4+len(self.names),2100) or not np.isfinite(output).all():
            raise ValueError('Invalid OpenCV model output: '+str(output.shape))
        return output

    def __call__(self,frame):
        image,ratio,pad=letterbox(frame,self.imgsz)
        tensor=np.ascontiguousarray(image[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/np.float32(255.)
        boxes,scores,classes=postprocess(self.raw(tensor),self.conf,self.iou,ratio,pad,frame.shape[:2])
        return [Detection(self.names[int(c)],float(score),tuple(float(v) for v in box))
                for box,score,c in zip(boxes,scores,classes)]
