#!/usr/bin/env python3
"""Standalone SVG flamegraph generator, version javatype-flamegraph-1.

Input: folded stacks weighted by perf event periods. No statistical inference
is performed. Incomplete DWARF stacks are retained as independent roots.
"""
import argparse
import hashlib
import html
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    root={'name':'all sampled opt user cycles','weight':0,'children':{}}
    depth=1
    for line in args.input.read_text().splitlines():
        stack,weight=line.rsplit(' ',1);weight=int(weight)
        frames=stack.split(';');depth=max(depth,len(frames)+1)
        node=root;node['weight']+=weight
        for name in frames:
            node=node['children'].setdefault(name,{'name':name,'weight':0,'children':{}})
            node['weight']+=weight
    width=1500;row=18;height=100+row*depth
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
         '<rect width="100%" height="100%" fill="#fff"/>',
         '<style>text{font-family:monospace;font-size:11px}g:hover rect{stroke:#111;stroke-width:1.5}</style>',
         '<text x="10" y="22" font-size="16">deep-static / S1 — cycle-weighted sampled stacks</text>',
         '<text x="10" y="43">3 profiles; cycles:u, 199 Hz, DWARF 8 KiB. Width denominator: all sampled opt user cycles.</text>',
         '<text x="10" y="61">Root stacks can be incomplete. Hover for full symbols and inclusive period weight. Generator: javatype-flamegraph-1.</text>']
    def draw(node,x,w,level,path):
        if w<0.3:return
        y=height-20-row*(level+1)
        name=node['name'];label=html.escape(name)
        h=hashlib.sha256(name.encode()).digest()
        color=f'rgb({210+h[0]%45},{100+h[1]%120},{50+h[2]%110})'
        title=html.escape(f'{" → ".join(path+[name])}\n{node["weight"]:,} sampled periods; {100*node["weight"]/root["weight"]:.3f}% of process')
        out.append(f'<g><title>{title}</title><rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="17" fill="{color}" stroke="#fff" stroke-width="0.5"/>')
        limit=max(0,int(w/6.5)-2)
        if limit>3:
            text=name if len(name)<=limit else name[:limit-1]+'…'
            out.append(f'<text x="{x+3:.2f}" y="{y+12}">{html.escape(text)}</text>')
        out.append('</g>')
        pos=x
        for child in sorted(node['children'].values(),key=lambda child:child['name']):
            cw=w*child['weight']/node['weight']
            draw(child,pos,cw,level+1,path+[name]);pos+=cw
    draw(root,10,width-20,0,[])
    out.append('</svg>')
    args.output.write_text('\n'.join(out)+'\n')


if __name__=='__main__':main()
