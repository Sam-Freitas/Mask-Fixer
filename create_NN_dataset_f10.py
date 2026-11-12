import os
import shutil
import glob
from natsort import natsorted


export_path_data = 'F10_dataset/data'
export_path_labels = 'F10_dataset/labels'
name_base = 'F10'
os.makedirs(export_path_data,exist_ok=True)
os.makedirs(export_path_labels,exist_ok=True)

all_files = natsorted(glob.glob(os.path.join('Fluorescent_test_010','*.png')))


data = []
labels = []
for this_file in all_files:

    if '_img.png' in this_file:
        data.append(this_file)
    if '_mask.png' in this_file:
        labels.append(this_file)

# check
data_checker = []
for this_data in data:
    data_checker.append(this_data.split('\\')[-1].replace('_img.png',''))
labels_checker = []
for this_label in labels:
    labels_checker.append(this_label.split('\\')[-1].replace('_mask.png',''))

assert data_checker == labels_checker


for i,(this_data,this_label) in enumerate(zip(data,labels)):

    this_name = name_base + '_' + str(i) + '.png'
    shutil.copy(this_data,os.path.join(export_path_data,this_name))
    shutil.copy(this_label,os.path.join(export_path_labels,this_name))

data = []