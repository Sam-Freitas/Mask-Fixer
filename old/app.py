import tkinter as tk
from tkinter import filedialog
from PIL import Image, ImageTk, ImageDraw
import numpy as np

# File paths (change accordingly)
path1 = "path1.png"
path2 = "path2.png"
path3 = "path3.png"
path2_edit = "path2_edit.png"

class ImageEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Image Editor")
        self.root.geometry("800x900")  # Set an initial size
        
        # Load and resize images
        self.img1 = Image.open(path1).convert("RGBA").resize((400, 400))
        self.img2 = Image.open(path2).convert("RGBA").resize((400, 400))
        self.img3 = Image.open(path3).convert("RGBA").resize((400, 400))
        
        self.mask = Image.new("L", self.img2.size, 0)  # Mask for drawing
        self.overlay_image = self.create_overlay()
        
        # Convert images for display
        self.tk_img1 = ImageTk.PhotoImage(self.img1)
        self.tk_img2 = ImageTk.PhotoImage(self.img2)
        self.tk_img3 = ImageTk.PhotoImage(self.img3)
        self.tk_overlay = ImageTk.PhotoImage(self.overlay_image)
        
        # Create labels and canvas
        self.frame = tk.Frame(root)
        self.frame.pack(expand=True, fill=tk.BOTH)
        
        self.label1 = tk.Label(self.frame, text="Image 1")
        self.label1.grid(row=0, column=0, sticky="nsew")
        self.canvas1 = tk.Label(self.frame, image=self.tk_img1)
        self.canvas1.grid(row=1, column=0, sticky="nsew")
        
        self.label2 = tk.Label(self.frame, text="Image 2 (Editable Mask)")
        self.label2.grid(row=0, column=1, sticky="nsew")
        self.canvas2 = tk.Canvas(self.frame, width=224, height=224)
        self.canvas2.grid(row=1, column=1, sticky="nsew")
        self.canvas2.create_image(0, 0, anchor=tk.NW, image=self.tk_img2)
        self.canvas2.bind("<B1-Motion>", self.paint)
        
        self.label3 = tk.Label(self.frame, text="Image 3")
        self.label3.grid(row=2, column=0, sticky="nsew")
        self.canvas3 = tk.Label(self.frame, image=self.tk_img3)
        self.canvas3.grid(row=3, column=0, sticky="nsew")
        
        self.label4 = tk.Label(self.frame, text="Overlay Image")
        self.label4.grid(row=2, column=1, sticky="nsew")
        self.canvas4 = tk.Label(self.frame, image=self.tk_overlay)
        self.canvas4.grid(row=3, column=1, sticky="nsew")
        
        # Controls
        self.control_frame = tk.Frame(root)
        self.control_frame.pack(fill=tk.X)
        
        self.color = "black"  # Default drawing color
        self.btn_black = tk.Button(self.control_frame, text="Black", command=lambda: self.set_color("black"))
        self.btn_black.pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        self.btn_white = tk.Button(self.control_frame, text="White", command=lambda: self.set_color("white"))
        self.btn_white.pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        self.btn_save = tk.Button(self.control_frame, text="Save", command=self.save_image)
        self.btn_save.pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        self.btn_next = tk.Button(self.control_frame, text="Next", command=self.next_image)
        self.btn_next.pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        # Make grid layout responsive
        for i in range(4):
            self.frame.rowconfigure(i, weight=1)
        for i in range(2):
            self.frame.columnconfigure(i, weight=1)
    
    def create_overlay(self):
        """Create an overlay image based on img1 and img2."""
        mask_np = np.array(self.mask) / 255.0
        img1_np = np.array(self.img1, dtype=np.float32)
        img2_np = np.array(self.img2, dtype=np.float32)
        overlay_np = img1_np * (1 - mask_np[..., None]) + img2_np * mask_np[..., None]
        return Image.fromarray(overlay_np.astype(np.uint8))
    
    def paint(self, event):
        """Allow drawing on the mask."""
        draw = ImageDraw.Draw(self.mask)
        color = 255 if self.color == "white" else 0
        draw.ellipse((event.x - 5, event.y - 5, event.x + 5, event.y + 5), fill=color)
        
        # Update mask image
        img_with_mask = self.img2.copy()
        img_with_mask.putalpha(self.mask)
        self.tk_img2 = ImageTk.PhotoImage(img_with_mask)
        self.canvas2.create_image(0, 0, anchor=tk.NW, image=self.tk_img2)
        
        # Update overlay image
        self.overlay_image = self.create_overlay()
        self.tk_overlay = ImageTk.PhotoImage(self.overlay_image)
        self.canvas4.config(image=self.tk_overlay)
    
    def set_color(self, color):
        """Set drawing color."""
        self.color = color
    
    def save_image(self):
        """Save the edited mask as path2_edit.png."""
        self.mask.save(path2_edit)
        print(f"Mask saved as {path2_edit}")
    
    def next_image(self):
        """Placeholder for next image functionality."""
        print("Next image placeholder")
        
if __name__ == "__main__":
    root = tk.Tk()
    app = ImageEditor(root)
    root.mainloop()
