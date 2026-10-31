"""Watch an existing camera process; does not open the camera or run inference."""
from pathlib import Path
import json,time


def format_status(status,age):
    posture=status.get('posture',{})
    detections=status.get('detections',[])
    boxes=', '.join(d['cls']+' '+f"{d['conf']:.2f}" for d in detections[:8]) or '-'
    if len(detections)>8:
        boxes+=' …'
    return (f"{time.strftime('%H:%M:%S')} age={age:.1f}s | "
            f"posture={posture.get('posture') or '-'} airway={posture.get('airway') or '-'} | "
            f"state={status.get('posture_state','-')} reason={status.get('posture_reason','-')} | "
            f"bed={'ready' if status.get('geometry_valid') else 'UNCALIBRATED'} | "
            f"fps={status.get('processing_fps',0):.1f} | boxes: {boxes}")


def main():
    root=Path('logs')
    try:
        while True:
            files=sorted(root.glob('20*/status.json'))
            if not files:
                print('Waiting for camera service. Run: bash ~/sky-eye/start.sh',flush=True)
            else:
                try:
                    status=json.loads(files[-1].read_text())
                    age=max(0.,time.time()-status.get('wall_time_unix',0))
                    print(format_status(status,age),flush=True)
                except (OSError,ValueError):
                    print('Waiting for a complete status update',flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass

if __name__=='__main__':
    main()
