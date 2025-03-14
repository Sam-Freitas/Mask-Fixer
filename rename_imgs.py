import os,glob
from natsort import natsorted 

p = 'GFP_low_signal\exported_masks'

imgs = natsorted(glob.glob(os.path.join(p,'*.png')))

added = 0

for i,pp in enumerate(imgs):
    print(i,pp)
    s = os.path.split(pp)
    img_name = int(s[1][:-5])
    new_name = str(img_name+added)
    new_path = os.path.join(s[0],new_name + '.png')
    print(i,new_path)
    os.rename(pp,new_path)

print(imgs)