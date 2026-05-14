# -*- coding: utf-8 -*-
'''
画像ファイルをSVG形式に変換する
'''

import os
import base64
import svgwrite


dstdir = 'type_img/'
filenames = os.listdir(dstdir)

for filename in filenames:

    if 'ステラ' not in filename:
        continue

    if (filename[-4:] != '.png'):
        continue
    
    with open(dstdir + filename, 'rb') as pngfile:
        img = base64.b64encode(pngfile.read())
        dwg = svgwrite.Drawing(dstdir + filename.replace('.png', '.svg'))
        dwg.add(dwg.image('data:image/png;base64,' + img.decode("ascii"), size=(160, 160)))
        dwg.save()