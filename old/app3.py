import tkinter as tk
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
        self.root.geometry("1000x1000")  # Set an initial size dynamically fitting the screen
        
        # Load and resize images
        self.img1 = Image.open(path1).convert("RGBA").resize((400, 400))
        self.img2 = Image.open(path2).convert("L").resize((400, 400))  # Ensure path2 is loaded as grayscale (binary mask)
        self.img3 = Image.open(path3).convert("RGBA").resize((400, 400))
        
        self.mask = self.img2.copy()  # Use path2 directly as the mask
        self.overlay_image = self.create_overlay()
        
        # Convert images for display
        self.tk_img1 = ImageTk.PhotoImage(self.img1)
        self.tk_img2 = ImageTk.PhotoImage(self.mask)  # Display path2 as editable
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
        self.canvas2 = tk.Canvas(self.frame, width=400, height=400)
        self.canvas2.grid(row=1, column=1, sticky="nsew")
        self.canvas2.create_image(0, 0, anchor=tk.NW, image=self.tk_img2)
        self.canvas2.bind("<B1-Motion>", self.paint)
        self.canvas2.bind("<Motion>", self.preview_brush)
        
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
        
        self.color = "black"
        self.brush_size = 10
        
        self.btn_black = tk.Button(self.control_frame, text="Black", command=lambda: self.set_color("black"))
        self.btn_black.pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        self.btn_white = tk.Button(self.control_frame, text="White", command=lambda: self.set_color("white"))
        self.btn_white.pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        self.btn_large_black = tk.Button(self.control_frame, text="Large Black", command=lambda: self.set_large_black())
        self.btn_large_black.pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        self.btn_save = tk.Button(self.control_frame, text="Save", command=self.save_image)
        self.btn_save.pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        self.btn_next = tk.Button(self.control_frame, text="Next", command=self.next_image)
        self.btn_next.pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        # Make grid layout responsive
        for i in range(4):
            self.frame.rowconfigure(i, weight=1)
        for i in range(2):
            self.frame.columnconfigure(i, weight=1)
    
    def set_large_black(self):
        """Set large brush size for black color."""
        self.color = "black"
        self.brush_size = 50  # Set a larger brush size
    
    def create_overlay(self):
        """Create an overlay image based on img1 and the current mask."""
        mask_np = np.array(self.mask) / 255.0
        img1_np = np.array(self.img1, dtype=np.float32)
        img2_np = np.array(self.img2.convert("RGBA"), dtype=np.float32)
        overlay_np = img1_np * (1 - mask_np[..., None]) + img2_np * mask_np[..., None]
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
    
    def preview_brush(self, event):
        """Show a preview of the brush size."""
        self.canvas2.delete("brush_preview")
        self.canvas2.create_oval(event.x - self.brush_size//2, event.y - self.brush_size//2, 
                                 event.x + self.brush_size//2, event.y + self.brush_size//2, 
                                 outline="red", tags="brush_preview")
    
    def set_color(self, color):
        """Set drawing color."""
        self.color = color
        self.brush_size = 10 if color == "white" else 10
    
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
