"""Create geometry from pixel coordinates on an SSH-captured snapshot; no GUI required."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from camera_fall.geometry import validate_geometry

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--size',nargs=2,type=int,metavar=('WIDTH','HEIGHT'),required=True)
    p.add_argument('--polygon',required=True,help='Pixel vertices in perimeter order: x,y;x,y;x,y;x,y')
    p.add_argument('--edges',required=True,help='One type per polygon edge: rail,open,wall,unknown')
    p.add_argument('--output',default='deploy/pi/geometry.json')
    p.add_argument('--confirmed',action='store_true',help='Confirm actual camera framing and edge types were checked')
    args=p.parse_args()
    w,h=args.size
    if w<=0 or h<=0:
        p.error('Positive frame dimensions required')
    polygon=[[float(x)/w,float(y)/h] for x,y in (v.split(',') for v in args.polygon.split(';'))]
    kinds=args.edges.split(',')
    if len(kinds)!=len(polygon):
        p.error('One edge type per polygon vertex required')
    geometry=dict(coordinate_system='normalized_image_xy',reference_width=w,reference_height=h,
        calibration_valid=args.confirmed,bed_polygon=polygon,boundaries=[dict(id=f'edge_{i}',type=kind,
        points=[polygon[i],polygon[(i+1)%len(polygon)]]) for i,kind in enumerate(kinds)])
    validate_geometry(geometry)
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(geometry,indent=2)+'\n')
    print('Saved geometry; calibration_valid='+str(args.confirmed))

if __name__=='__main__':
    main()
