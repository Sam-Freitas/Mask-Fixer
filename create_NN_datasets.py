import os,glob,shutil
from natsort import natsorted

datasets = [
    'GFP_low_signal',
    'tdTomato',
    'redgeen2_blueex',
    'redgreen2_greenex'
]

associated_fluor_images = [
    r"C:\Users\LabPC2\Documents\GitHub\WP_imager\output\RG_fluor_test2\CL2166 (gst-4-GFP)",
    r"C:\Users\LabPC2\Documents\GitHub\WP_imager\output\RG_fluor_test2\EG7565 (etf3-TdTomato)",
    r"C:\Users\LabPC2\Documents\GitHub\WP_imager\output\RG_fluor_test2\Red_Green 2(GLS473)",
    r"C:\Users\LabPC2\Documents\GitHub\WP_imager\output\RG_fluor_test2\Red_Green 2(GLS473)"
]

additional_fluor_name_filter = [
    '',
    '',
    '_BLUEex',
    'GREENex'
]

def find_files(folder_path, file_extension='.png', filter1=None, filter2 = None):
    """
    Recursively finds and returns all files with the specified extension in the given folder,
    only if the filter string is contained within the file path.

    Args:
        folder_path (str): The path to the folder to search.
        file_extension (str): The file extension to search for (default is '.png').
        filter (str): The filter string that must be in the file path to be included in the result (default is 'fluorescent_data').

    Returns:
        list: A list of file paths that match the specified extension and contain the filter string.
    """
    found_files = []

    if filter1:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith(file_extension.lower()) and filter1 in os.path.join(root, file):
                    found_files.append(os.path.join(root, file))
    else:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith(file_extension.lower()):
                    found_files.append(os.path.join(root, file))

    # secondary optional filter
    if filter2:
        found_files2 = []
        for file in found_files:
            if filter2 in file:
                found_files2.append(file)
        return found_files2
    else:
        return found_files

def copy_over_imgs_masks(imgs_paths_to_copy,masks_paths_to_copy,testing_imgs_to_copy,new_dataset_name,counter_copy,testing_counter_copy):

    for linked_img,linked_mask in zip(imgs_paths_to_copy,masks_paths_to_copy):
        
        shutil.copyfile(linked_img, os.path.join(os.getcwd(),new_dataset_name,'data',str(counter_copy) + '.png'))
        shutil.copyfile(linked_mask, os.path.join(os.getcwd(),new_dataset_name,'labels',str(counter_copy) + '.png'))
        counter_copy += 1

    for this_testing_img in testing_imgs:
        shutil.copyfile(this_testing_img, os.path.join(os.getcwd(),new_dataset_name,'testing_imgs',str(testing_counter_copy) + '.png'))
        testing_counter_copy +=1

    return counter_copy, testing_counter_copy

def get_imgs_to_copy(imgs_paths,masks_indexes):

    imgs_to_copy_temp = []
    testing_imgs_temp = []
    for i,temp in enumerate(imgs_paths):
        if i in masks_indexes:
            imgs_to_copy_temp.append(temp)
        else:
            testing_imgs_temp.append(temp)

    return imgs_to_copy_temp, testing_imgs_temp

if __name__ == "__main__":

    new_dataset_name = 'isolate_worms_from_single_well_dataset_norm'

    os.makedirs(os.path.join(os.getcwd(),new_dataset_name,'labels'),exist_ok=True)
    os.makedirs(os.path.join(os.getcwd(),new_dataset_name,'data'),exist_ok=True)
    os.makedirs(os.path.join(os.getcwd(),new_dataset_name,'testing_imgs'),exist_ok=True)

    counter = 0
    testing_counter = 0
    for this_dataset in datasets:
        print('DATASET:',this_dataset)

        m_path = os.path.join(this_dataset,'exported_masks')
        i_path = os.path.join(this_dataset,'image_time_stacks')

        print('---finding images')
        masks_paths = natsorted(find_files(m_path, file_extension='.png', filter1=None))
        imgs_paths = natsorted(find_files(i_path, file_extension='.png', filter1='_img'))
        mod_paths = natsorted(find_files(i_path, file_extension='.png', filter1='_mod'))

        imgs_paths_exp0 = natsorted(find_files(i_path, file_extension='.png', filter1='_i0mg'))
        imgs_paths_exp1 = natsorted(find_files(i_path, file_extension='.png', filter1='_i1mg'))
        imgs_paths_exp2 = natsorted(find_files(i_path, file_extension='.png', filter1='_i2mg'))
        imgs_paths_exp3 = natsorted(find_files(i_path, file_extension='.png', filter1='_i3mg'))

        mod_paths_exp0 = natsorted(find_files(i_path, file_extension='.png', filter1='_m0od'))
        mod_paths_exp1 = natsorted(find_files(i_path, file_extension='.png', filter1='_m1od'))
        mod_paths_exp2 = natsorted(find_files(i_path, file_extension='.png', filter1='_m2od'))
        mod_paths_exp3 = natsorted(find_files(i_path, file_extension='.png', filter1='_m3od'))

        print('---checking number of images')
        assert len(imgs_paths) == len(mod_paths)

        print('---associating known good masks')
        masks_indexes = [int(os.path.split(this_path)[1][:-4]) for this_path in masks_paths]

        # get intial images
        imgs_to_copy, testing_imgs = get_imgs_to_copy(imgs_paths,masks_indexes)
        mod_to_copy,  testing_mods = get_imgs_to_copy(mod_paths,masks_indexes)

        # now do exposures and mods 0
        imgs_to_copy_exp0, testing_imgs_exp0 = get_imgs_to_copy(imgs_paths_exp0,masks_indexes)
        mod_to_copy_exp0,  testing_mods_exp0 = get_imgs_to_copy(mod_paths_exp0,masks_indexes)

        # now do exposures and mods 1
        imgs_to_copy_exp1, testing_imgs_exp1 = get_imgs_to_copy(imgs_paths_exp1,masks_indexes)
        mod_to_copy_exp1,  testing_mods_exp1 = get_imgs_to_copy(mod_paths_exp1,masks_indexes)

        # now do exposures and mods 2
        imgs_to_copy_exp2, testing_imgs_exp2 = get_imgs_to_copy(imgs_paths_exp2,masks_indexes)
        mod_to_copy_exp2,  testing_mods_exp2 = get_imgs_to_copy(mod_paths_exp2,masks_indexes)

        # now do exposures and mods 3
        imgs_to_copy_exp3, testing_imgs_exp3 = get_imgs_to_copy(imgs_paths_exp3,masks_indexes)
        mod_to_copy_exp3,  testing_mods_exp3 = get_imgs_to_copy(mod_paths_exp3,masks_indexes)

        print('---copying over files')
        # inital images
        counter, testing_counter = copy_over_imgs_masks(imgs_to_copy,masks_paths,testing_imgs,new_dataset_name,counter,testing_counter)
        counter, testing_counter = copy_over_imgs_masks(mod_to_copy,masks_paths,testing_mods,new_dataset_name,counter,testing_counter)

        # now do exposures and mods 0
        counter, testing_counter = copy_over_imgs_masks(imgs_to_copy_exp0,masks_paths,testing_imgs_exp0,new_dataset_name,counter,testing_counter)
        counter, testing_counter = copy_over_imgs_masks(mod_to_copy_exp0,masks_paths,testing_mods_exp0,new_dataset_name,counter,testing_counter)

        # now do exposures and mods 1
        counter, testing_counter = copy_over_imgs_masks(imgs_to_copy_exp1,masks_paths,testing_imgs_exp1,new_dataset_name,counter,testing_counter)
        counter, testing_counter = copy_over_imgs_masks(mod_to_copy_exp1,masks_paths,testing_mods_exp1,new_dataset_name,counter,testing_counter)

        # now do exposures and mods 2
        counter, testing_counter = copy_over_imgs_masks(imgs_to_copy_exp2,masks_paths,testing_imgs_exp2,new_dataset_name,counter,testing_counter)
        counter, testing_counter = copy_over_imgs_masks(mod_to_copy_exp2,masks_paths,testing_mods_exp2,new_dataset_name,counter,testing_counter)

        # now do exposures and mods 3
        counter, testing_counter = copy_over_imgs_masks(imgs_to_copy_exp3,masks_paths,testing_imgs_exp3,new_dataset_name,counter,testing_counter)
        counter, testing_counter = copy_over_imgs_masks(mod_to_copy_exp3,masks_paths,testing_mods_exp3,new_dataset_name,counter,testing_counter)
    
        print('loop')

    print('EOF')