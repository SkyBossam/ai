"""Class-wise annotation masks for mixed infant and Pillow images (Ultralytics 8.4.176)."""
from copy import copy
from pathlib import Path
import torch
from torch import nn
from torch.nn import functional as F
from ultralytics.nn.tasks import DetectionModel
from ultralytics.models.yolo.detect import DetectionTrainer, DetectionValidator
from ultralytics.utils.loss import v8DetectionLoss

NAMES=['supine','side','prone','airway_visible','airway_covered','pillow','toy']


def known_classes(path):
    name=Path(path).name
    if name.startswith('bp_'):
        return (0,1,2,3,4,6)
    if name.startswith('oi_'):
        return (5,)
    raise ValueError('Unknown annotation provenance: '+str(path))


class KnownClassBCE(nn.Module):
    def __init__(self):
        super().__init__()
        self.known_mask=None

    def forward(self,logits,targets):
        if self.known_mask is None or logits.shape[0]!=self.known_mask.shape[0]:
            raise ValueError('Annotation mask was not set for this batch')
        mask=self.known_mask.to(device=logits.device,dtype=logits.dtype)[:,None,:]
        return F.binary_cross_entropy_with_logits(logits,targets,reduction='none')*mask


class PartialLabelLoss(v8DetectionLoss):
    def __init__(self,model):
        super().__init__(model)
        if self.nc!=7:
            raise ValueError('This annotation policy requires exactly seven classes')
        self.bce=KnownClassBCE()

    def __call__(self,preds,batch):
        paths=batch.get('im_file')
        if paths is None or len(paths)!=len(batch['img']):
            raise ValueError('Per-image annotation provenance is required')
        mask=torch.zeros((len(paths),self.nc),device=self.device)
        for i,path in enumerate(paths):
            mask[i,list(known_classes(path))]=1
        if batch['cls'].numel():
            valid=mask[batch['batch_idx'].long(),batch['cls'].view(-1).long()]
            if not bool(valid.all()):
                raise ValueError('Positive label outside the annotated class set')
        self.bce.known_mask=mask
        return super().__call__(preds,batch)


class PartialLabelModel(DetectionModel):
    def init_criterion(self):
        return PartialLabelLoss(self)


class PartialLabelValidator(DetectionValidator):
    def update_metrics(self,preds,batch):
        filtered=[]
        for prediction,path in zip(preds,batch['im_file']):
            classes=prediction['cls']
            keep=torch.zeros_like(classes,dtype=torch.bool)
            for value in known_classes(path):
                keep|=classes==value
            filtered.append({k:v[keep] if isinstance(v,torch.Tensor) and v.ndim and len(v)==len(classes) else v
                             for k,v in prediction.items()})
        return super().update_metrics(filtered,batch)


class PartialLabelTrainer(DetectionTrainer):
    def get_model(self,cfg=None,weights=None,verbose=True):
        for setting in ('mosaic','mixup','cutmix','copy_paste'):
            if float(getattr(self.args,setting,0) or 0)!=0:
                raise ValueError('Mixed-source image augmentation invalidates annotation masks: '+setting)
        model=self.set_model_names_for_load(PartialLabelModel(cfg,nc=self.data['nc'],ch=self.data['channels'],verbose=False))
        if weights:
            model.load(weights)
        return model

    def get_validator(self):
        return PartialLabelValidator(self.test_loader,save_dir=self.save_dir,args=copy(self.args),_callbacks=self.callbacks)

    def save_model(self):
        # Store a standard Ultralytics model so inference never needs this custom training module.
        ema=self.ema.ema
        original_class=ema.__class__
        ema.__class__=DetectionModel
        try:
            return super().save_model()
        finally:
            ema.__class__=original_class
