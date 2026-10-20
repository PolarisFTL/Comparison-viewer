"""Generate small original synthetic fixtures without third-party runtime packages."""
import math
import struct
import zlib
from pathlib import Path


def png(path,width,height,pixels):
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+bytes(pixels[y*width*3:(y+1)*width*3]) for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows,6))+chunk(b'IEND',b''))


def generate_demo(folder,count=16):
    folder=Path(folder);methods=[]
    for mi,name in enumerate(('Input','Baseline A','Our Model','Ground Truth')):
        root=folder/('method-'+str(mi));root.mkdir(parents=True,exist_ok=True)
        methods.append({'id':'demo-'+str(mi),'name':name,'root':str(root.resolve())})
        for sample in range(count):
            width,height=(384,256) if sample%3 else (320,320)
            file=root/('scene-{:04d}.png'.format(sample+1))
            if file.exists():continue
            pixels=bytearray(width*height*3)
            for y in range(height):
                for x in range(width):
                    base=28+int(14*y/height)+(5 if ((x//40+y//40)%2) else 0)
                    offset=(y*width+x)*3;pixels[offset:offset+3]=bytes((base,base+7,base+15))
            for car in range(8):
                cx=40+(sample*17+car*43)%(width-80);cy=35+(sample*11+car*37)%(height-70)
                angle=(car*.31+sample*.11);c,s=math.cos(angle),math.sin(angle)
                for y in range(max(0,cy-20),min(height,cy+21)):
                    for x in range(max(0,cx-25),min(width,cx+26)):
                        dx,dy=x-cx,y-cy;u,v=dx*c+dy*s,-dx*s+dy*c
                        fill=abs(u)<12 and abs(v)<6
                        shift=2 if mi==1 and car%3==0 else 0
                        border=mi>0 and not (mi==1 and car==4) and abs(u-shift)<=17 and abs(v)<=10 and (abs(u-shift)>15 or abs(v)>8)
                        if fill or border:
                            color=(242,177,71) if border else (95+car*10,119+car*5,145)
                            if mi==2 and border:color=(59,210,167)
                            offset=(y*width+x)*3;pixels[offset:offset+3]=bytes(color)
            png(file,width,height,pixels)
    return {'schema':2,'dataset':'Synthetic OBB Demo','datasetId':'04d47b8f-10e1-47d8-8d94-65b2a4ad84a5','referenceId':'demo-0','methods':methods}
