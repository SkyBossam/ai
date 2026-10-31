from dataclasses import asdict
import math
import numpy as np
from sleepsafe.classes import BODY_CLASSES
from sleepsafe.decision import FrameDecision, decide
from sleepsafe.risk import RiskConfig, RiskMonitor
from camera_fall.risk import FeatureExtractor, R0, iou


class SharedPipeline:
    """The selected body and each frame's single inference are shared by both policies."""
    def __init__(self, detector, geometry, policy, config):
        self.detector, self.geometry, self.config = detector, geometry, config
        self.features = FeatureExtractor(geometry, policy['max_observation_gap_s'])
        self.fall = R0(policy)
        self.posture = RiskMonitor(RiskConfig(**config['posture_risk']))
        self.last_ts = self.last_body = self.last_seen = None
        self.subject_id=0
        self.stable = self.candidate = self.candidate_since = None

    def step(self, frame, ts):
        if not math.isfinite(ts) or (self.last_ts is not None and ts <= self.last_ts):
            raise ValueError('Frame timestamps must strictly increase')
        gap = None if self.last_ts is None else ts-self.last_ts
        self.last_ts = ts
        # A single model invocation per accepted frame.
        raw = self.detector(frame)
        detections = [d for d in raw if math.isfinite(d.conf) and 0 <= d.conf <= 1
                      and all(math.isfinite(v) for v in d.xyxy)
                      and d.xyxy[2] > d.xyxy[0] and d.xyxy[3] > d.xyxy[1]
                      and (d.cls not in ('pillow','toy') or d.conf >= self.config['object_confidence'])]
        height,width = frame.shape[:2]
        brightness = float(np.mean(frame)/255.)
        bodies = sorted((d for d in detections if d.cls in BODY_CLASSES
                         and d.conf >= self.config['body_confidence']), key=lambda d:-d.conf)
        unique=[]
        for d in bodies:
            if not any(iou(d.xyxy, other.xyxy) >= self.config['body_duplicate_iou'] for other in unique):
                unique.append(d)
        chosen=None
        if self.last_body is not None and ts-self.last_seen <= self.config['track_gap_s']:
            matches=[d for d in unique if iou(d.xyxy,self.last_body.xyxy) >= .1]
            if len(matches)==1:
                chosen=matches[0]
        if chosen is None and len(unique)==1:
            chosen=unique[0]
        if len(unique)>1 and chosen is None:
            decision=FrameDecision(False,reason='ambiguous_bodies')
        else:
            filtered=[d for d in detections if d.cls not in BODY_CLASSES]
            if chosen is not None:
                filtered.append(chosen)
            decision=decide(filtered,self.config['body_confidence'],self.config['airway_confidence'],True)
        if brightness < self.config['minimum_brightness']:
            decision=FrameDecision(False,reason='dark')
            chosen=None
        replaced=bool(chosen is not None and self.last_body is not None and
                      (ts-self.last_seen>self.config['track_gap_s'] or iou(chosen.xyxy,self.last_body.xyxy)<.1))
        if chosen is not None:
            if self.subject_id==0 or replaced:
                self.subject_id+=1
            self.last_body,self.last_seen=chosen,ts
        body=[] if chosen is None else [dict(bbox=[chosen.xyxy[0]/width,chosen.xyxy[1]/height,
                                                   chosen.xyxy[2]/width,chosen.xyxy[3]/height],confidence=chosen.conf)]
        reference_ratio=self.geometry['reference_width']/self.geometry['reference_height']
        geometry_valid=abs(width/height-reference_ratio) < 1e-3
        features=self.features.step(ts,body,brightness,geometry_valid=geometry_valid)
        fall=self.fall.step(features)
        events=[]
        if replaced:
            if self.posture.active:
                old=asdict(self.posture.active)
                old.update(kind='risk_interrupted',ts=ts,reason='track_changed')
                events.append(dict(branch='posture',**old))
            self.posture=RiskMonitor(self.posture.config)
            self.stable=self.candidate=self.candidate_since=None
        if gap is not None and gap > self.posture.config.gap_tolerance_s:
            # Valid frames separated by a long inference/camera gap are not continuous evidence.
            events.extend(dict(branch='posture',**asdict(e)) for e in
                          self.posture.update(ts-1e-6,FrameDecision(False,reason='frame_gap')))
            self.candidate=self.candidate_since=None
        events.extend(dict(branch='posture',**asdict(e)) for e in self.posture.update(ts,decision))
        if decision.posture is None or not decision.valid:
            self.candidate=self.candidate_since=None
        elif decision.posture != self.candidate:
            self.candidate,self.candidate_since=decision.posture,ts
        elif ts-self.candidate_since >= self.config['posture_stable_s'] and self.candidate != self.stable:
            previous=self.stable
            self.stable=self.candidate
            if previous is not None:
                events.append(dict(branch='posture',kind='posture_changed',ts=ts,
                                   previous=previous,current=self.stable))
        events.extend(dict(branch='fall',**e) for e in fall['events'])
        return dict(schema_version=1,ts=ts,posture=asdict(decision),posture_state=self.posture.status,
                    posture_reason=self.posture.reason,stable_posture=self.stable,
                    fall=fall,geometry_valid=bool(self.geometry['calibration_valid'] and geometry_valid),
                    detections=[asdict(d) for d in detections],events=events,
                    observation_gap_s=gap,subject_id=self.subject_id or None,forward_calls=1)
