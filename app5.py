import tkinter as tk
from PIL import Image, ImageTk, ImageDraw
import numpy as np
import os, time, glob, subprocess, platform, sys, torch, cv2
from natsort import natsorted
from kornia.contrib import connected_components

# Device configuration
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
if device.type == 'cpu' and torch.backends.mps.is_available():
    device = torch.device('mps')

def leave_only_largest_blob(binary_image, device='cpu', num_iterations=1000):
    """
    Keeps only the largest connected component in a binary image.
    Args:
        binary_image (torch.Tensor): A 2D binary image tensor (HxW) with values 0 and 1.
    Returns:
        torch.Tensor: The binary image with only the largest component retained.
    """
    if isinstance(binary_image, (list, tuple)) or 'numpy' in str(type(binary_image)):
        binary_image = torch.as_tensor(binary_image, dtype=torch.uint8)
    
    if binary_image.ndim != 2 or binary_image.dtype != torch.uint8:
        raise ValueError("binary_image must be a 2D binary tensor of type torch.uint8.")
    
    # Move tensor to the target device early
    binary_image = binary_image.to(device)
    
    # Reshape for Kornia's connected_components function and convert to float
    labels = connected_components(binary_image[None, None].float(), num_iterations=num_iterations)
    labels = labels.squeeze(0).squeeze(0)  # Back to (H, W)
    
    # Compute component sizes efficiently
    unique_labels, counts = torch.unique(labels, return_counts=True)
    counts[unique_labels == 0] = 0  # Ignore background
    
    # Find the largest component label
    largest_label = unique_labels[torch.argmax(counts)]
    
    # Create mask for the largest component
    largest_component = labels == largest_label
    
    return largest_component.to(device)

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

class ImageEditor:
    def __init__(self, root,path1,path2,path3,i,export_path):

        # s = 275
        s = 290
        self.image_size_small = (s,s)
        n = 3.25
        self.image_size_large = (int(s*n),int(s*n))

        self.root = root
        self.root.title("Image Editor --- Image " + str(i))
        # self.root.geometry("1000x1000+50+1")  # Set an initial size dynamically fitting the screen
        self.root.geometry("+50+1")

        # set up the export 
        self.i = i
        self.export_path = export_path
        
        # # Load and resize images
        # Modified image
        self.mod_img = Image.open(path1).convert("RGBA").resize(self.image_size_small)
        # Binary mask
        self.mask_img = Image.open(path2).convert("L").resize(self.image_size_large, resample=Image.Resampling.NEAREST)  
        # Unmodified image
        self.unmod_img = Image.open(path3).convert("RGBA").resize(self.image_size_small)
        
        self.mask = self.mask_img.copy()  # Use path2 directly as the mask
        self.overlay_image = self.create_overlay()
        
        # Convert images for display
        self.tk_img1 = ImageTk.PhotoImage(self.mod_img)
        self.tk_img2 = ImageTk.PhotoImage(self.mask)  # Display path2 as editable
        self.tk_img3 = ImageTk.PhotoImage(self.unmod_img)
        self.tk_overlay = ImageTk.PhotoImage(self.overlay_image)
        
        # Create labels and canvas
        self.frame = tk.Frame(root)
        self.frame.pack(expand=True, fill=tk.BOTH)

        span = 5
        self.label2 = tk.Label(self.frame, text="Image 2 (Editable Mask)")
        self.label2.grid(row=0, column=1, sticky="nsew")
        self.canvas2 = tk.Canvas(self.frame, width=self.image_size_large[0], height=self.image_size_large[1])
        self.canvas2.grid(row=1, column=1, sticky="nsew",columnspan=span,rowspan=span)
        self.canvas2.create_image(0, 0, anchor=tk.NW, image=self.tk_img2)
        self.canvas2.bind("<Button-1>", self.paint)
        self.canvas2.bind("<B1-Motion>", self.paint)
        self.canvas2.bind("<Motion>", self.preview_brush)
        
        self.label1 = tk.Label(self.frame, text="Image 1")
        self.label1.grid(row=0, column=0, sticky="nsew")
        self.canvas1 = tk.Label(self.frame, image=self.tk_img1)
        self.canvas1.grid(row=1, column=0, sticky="nsew")
        
        self.label3 = tk.Label(self.frame, text="Image 3")
        self.label3.grid(row=2, column=0, sticky="nsew")
        self.canvas3 = tk.Label(self.frame, image=self.tk_img3)
        self.canvas3.grid(row=3, column=0, sticky="nsew")
        
        self.label4 = tk.Label(self.frame, text="Overlay Image")
        self.label4.grid(row=4, column=0, sticky="nsew")
        self.canvas4 = tk.Label(self.frame, image=self.tk_overlay)
        self.canvas4.grid(row=5, column=0, sticky="nsew")

        self.label1 = tk.Label(self.frame, text="test")
        self.label1.grid(row=0, column=span+1, sticky="nsew")
        self.canvas1 = tk.Label(self.frame, image=self.tk_img1)
        self.canvas1.grid(row=1, column=span+1, sticky="nsew")
        
        # Controls
        self.control_frame = tk.Frame(root)
        self.control_frame.pack(fill=tk.X)
        
        self.color = "black"
        self.brush_size = 10

        # # Buttons at the bottom of the frame
        # large black fill
        self.btn_large_black = tk.Button(self.control_frame, text="Large Black", command=lambda: self.set_large_black())
        self.btn_large_black.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # black fill
        self.btn_black = tk.Button(self.control_frame, text="Black", command=lambda: self.set_color("black"))
        self.btn_black.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # white fill
        self.btn_white = tk.Button(self.control_frame, text="White", command=lambda: self.set_color("white"))
        self.btn_white.pack(side=tk.LEFT, expand=True, fill=tk.X)
        #isolate only the largest blob
        self.btn_ISO = tk.Button(self.control_frame, text="Isolate Largest", command=self.isolate_large_blob)
        self.btn_ISO.pack(side=tk.LEFT, expand=True, fill=tk.X)

        # reset binary image
        self.btn_reset = tk.Button(self.control_frame, text="Reset", command=self.reset_image)
        self.btn_reset.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # save the mask
        self.btn_save = tk.Button(self.control_frame, text="Save", command=self.save_image)
        self.btn_save.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # prev img
        self.btn_prev = tk.Button(self.control_frame, text="Prev", command=self.prev_image)
        self.btn_prev.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # next img
        self.btn_next = tk.Button(self.control_frame, text="Next", command=self.next_image)
        self.btn_next.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # quit application
        self.btn_QUIT = tk.Button(self.control_frame, text="Quit", command=self.quit_app)
        self.btn_QUIT.pack(side=tk.LEFT, expand=True, fill=tk.X)

        # # Make grid layout responsive
        # for i in range(4):
        #     self.frame.rowconfigure(i, weight=1)
        # for i in range(2):
        #     self.frame.columnconfigure(i, weight=1)

    def isolate_large_blob(self):

        temp_mask_np = (np.asarray(self.mask)/255).astype(np.uint8)
        temp_mask_torch = leave_only_largest_blob(temp_mask_np, device=device, num_iterations = 500)
        temp_mask_np = temp_mask_torch.cpu().numpy().astype(np.uint8)*255

        self.mask = Image.fromarray(temp_mask_np)

        self.tk_img2 = ImageTk.PhotoImage(self.mask)
        self.canvas2.create_image(0, 0, anchor=tk.NW, image=self.tk_img2)

        print('TEST')
    
    def set_large_black(self):
        """Set large brush size for black color."""
        self.color = "black"
        self.brush_size = 200  # Set a larger brush size

    def set_color(self, color):
        """Set drawing color."""
        self.color = color
        self.brush_size = 10 if color == "white" else 10
    
    def create_overlay(self):
        """Create an overlay image based on img1 and the current mask."""

        data = [self.mask.size,self.mod_img.size,self.mask_img.size]
        resize_size = min(data, key = lambda t: t[1])

        mask_np = np.array(self.mask.resize(resize_size)) / 255.0
        img1_np = np.array(self.mod_img.resize(resize_size), dtype=np.float32)
        img2_np = np.array(self.mask_img.convert("RGBA").resize(resize_size), dtype=np.float32)
        overlay_np = img1_np * (1 - mask_np[..., None]) + (img2_np * mask_np[..., None])
        return Image.fromarray(overlay_np.astype(np.uint8))
    
    def paint(self, event):

        """Allow drawing on the mask by adding (white) or removing (black) parts."""
        draw = ImageDraw.Draw(self.mask)
        color = 255 if self.color == "white" else 0
        draw.ellipse((event.x - self.brush_size//2, event.y - self.brush_size//2, 
                      event.x + self.brush_size//2, event.y + self.brush_size//2), fill=color)
        
        # Update displayed mask
        self.tk_img2 = ImageTk.PhotoImage(self.mask)
        self.canvas2.create_image(0, 0, anchor=tk.NW, image=self.tk_img2)

        # Update overlay image
        self.overlay_image = self.create_overlay()
        self.tk_overlay = ImageTk.PhotoImage(self.overlay_image)
        self.canvas4.config(image=self.tk_overlay)

        """Show a preview of the brush size."""
        self.canvas2.delete("brush_preview")
        self.canvas2.create_oval(event.x - self.brush_size//2, event.y - self.brush_size//2, 
                                 event.x + self.brush_size//2, event.y + self.brush_size//2, 
                                 outline="red", tags="brush_preview")
    
    def preview_brush(self, event):
        """Show a preview of the brush size."""
        self.canvas2.delete("brush_preview")
        self.canvas2.create_oval(event.x - self.brush_size//2, event.y - self.brush_size//2, 
                                 event.x + self.brush_size//2, event.y + self.brush_size//2, 
                                 outline="red", tags="brush_preview")

    def reset_image(self):
        """Reload and reset path2 image."""
        self.mask = Image.open(path2).convert("L").resize(self.image_size_large)
        self.tk_img2 = ImageTk.PhotoImage(self.mask)
        self.canvas2.create_image(0, 0, anchor=tk.NW, image=self.tk_img2)
    
    def save_image(self):
        """Save the edited mask as path2_edit.png."""
        path2_edit = os.path.join(self.export_path,str(self.i) + '.png')
        self.mask.save(path2_edit)
        print(f"Mask saved as {path2_edit}")
    
    def next_image(self):
        """Destroy the window so the next one can be loaded"""
        self.root.destroy()

    def prev_image(self):
        """placeholder to do something"""
        print("GO BACKWARDS placeholder")

    def quit_app(self):
        """this end the program"""
        sys.exit()
        
if __name__ == "__main__":

    path_to_images = 'image_time_stacks'

    output_path = 'exported_masks'
    os.makedirs(output_path,exist_ok=True)

    # if platform.system() == 'Windows':
    #     subprocess.run(["explorer", os.path.realpath(output_path)], check=False)
    #     subprocess.run(["explorer", os.path.realpath(path_to_images)], check=False)

    unmodified_image_filter_name = '_img'
    modified_image_filter_name = '_mod'
    mask_filter_name = '_mask'

    unmod_imgs = natsorted(find_files(path_to_images, file_extension='.png', filter1=unmodified_image_filter_name))
    mod_imgs = natsorted(find_files(path_to_images, file_extension='.png', filter1=modified_image_filter_name))
    mask_imgs = natsorted(find_files(path_to_images, file_extension='.png', filter1=mask_filter_name))

    for i,this_imgs_paths in enumerate(zip(unmod_imgs,mask_imgs,mod_imgs)):
        # File paths (change accordingly)
        # path1 intial image
        path1 = this_imgs_paths[2]
        # masked image
        path2 = this_imgs_paths[1]
        # modified image that created the mask
        path3 = this_imgs_paths[0]

        root = tk.Tk()
        app = ImageEditor(root,path1=path1,path2=path2,path3=path3,i=i,export_path = output_path)
        root.mainloop()

        print('end loop')

    print('EOF')
