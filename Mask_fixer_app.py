import tkinter as tk
from tkinter import messagebox                      # [CHANGE C2] dialog for unsaved edits
from PIL import Image, ImageTk, ImageDraw
import numpy as np
import os, time,torch, glob, subprocess, platform, sys, cv2
from natsort import natsorted
from kornia.contrib import connected_components
from pathlib import Path

# Device configuration
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
if device.type == 'cpu' and torch.backends.mps.is_available():
    device = torch.device('mps')

# ---------------------------------------------------------------------------
# [CHANGE A5] Cursor-overlay look (safe to tweak). The brush footprint is drawn in the
# same colour on both the editable mask and the overlay panel so the two always match.
# ---------------------------------------------------------------------------
BRUSH_PREVIEW_COLOR = "red"     # circle = the footprint the brush will actually paint
CURSOR_CROSS_COLOR  = "cyan"    # thin crosshair = the exact pointer position
CURSOR_LINE_WIDTH   = 1         # crosshair thickness
CURSOR_MIN_RADIUS   = 3         # keep very small brushes visible on the shrunken panel

# ---------------------------------------------------------------------------
# [CHANGE D1] Keyboard shortcuts for the buttons: plain letters, no Ctrl needed.
# Delete a line to switch a shortcut off, or change the letter to re-map it.
# Note: 'q' is the black brush, not quit, as you asked - Quit deliberately has no letter key.
# ---------------------------------------------------------------------------
HOTKEYS = {
    'q': 'black',   # switch to the black (erase) brush
    'e': 'white',   # switch to the white (add) brush
    's': 'save',    # save this mask to the export folder
    'a': 'prev',    # previous image
    'd': 'next',    # next image ("Finish" on the last one)
    'r': 'reset',   # throw the edits away and reload the baseline mask
}
HOTKEY_GUARD = 0.20             # [CHANGE D5] seconds; swallows keyboard auto-repeat


def hotkey_hint(action):
    """[CHANGE D2] Build the " (Q)" style hint that goes on a button label, so the label
    always matches HOTKEYS instead of drifting away from it."""
    for key, value in HOTKEYS.items():
        if value == action:
            return " (%s)" % key.upper()
    return ""

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
    # [CHANGE C1/C3] new optional arguments:
    #   total          -> number of images in the run, only used for the window title / button state
    #   restored_mask  -> PIL mask to start from when coming back to an already-edited image
    def __init__(self, root, path1, path2, path3, i, export_path, total=None, restored_mask=None):

        # s = 275
        s = 290
        self.image_size_small = (s,s)
        n = 3.25
        self.image_size_large = (int(s*n),int(s*n))

        self.root = root
        self.root.focus_force()
        # [CHANGE C4] show position in the sequence, e.g. "Image 3 of 5" (1-based for the user)
        title = "Image Editor --- Image " + str(i + 1)
        if total:
            title += " of " + str(total)
        self.root.title(title)
        # self.root.geometry("1000x1000+50+1")  # Set an initial size dynamically fitting the screen
        self.root.geometry("+50+1")

        # set up the export 
        self.i = i
        self.total = total
        self.export_path = export_path
        # [CHANGE C1] keep the file paths on the instance instead of relying on the
        # module-level globals that the old main loop happened to leak into scope.
        self.path1 = path1
        self.path2 = path2
        self.path3 = path3
        self.export_name = Path(path2).stem
        # [CHANGE C1] what the user asked for when the window closed: 'next' | 'prev' | 'quit' | None
        self.action = None
        # [CHANGE C2] True as soon as the mask is touched and not yet saved
        self._dirty = False
        # [CHANGE A4] pointer position expressed in editable-mask (large canvas) pixels,
        # or None when the pointer is not over either image.
        self._cursor = None
        # [CHANGE A4] True when the pointer is over the overlay panel, which is when the
        # mirrored crosshair is drawn on the editable mask.
        self._cursor_from_panel = False
        # [CHANGE A3] geometry of the overlay panel, filled in by _render_overlay()
        self._ov_side = 0        # side (px) of the square overlay currently displayed
        self._ov_offx = 0        # left edge of the overlay image inside canvas4
        self._ov_offy = 0        # top edge of the overlay image inside canvas4
        self._overlay_item = None
        # [CHANGE A6] cache of the source image scaled to the current panel size
        self._src_cache = None
        # [CHANGE A2] cap the overlay resolution at the source resolution so the panel never
        # invents pixels that are not in the input images (the files are 512x512).
        self.source_side = 512
        
        # # Load and resize images
        # Modified image
        self.mod_full = Image.open(path1).convert("RGBA")          # [CHANGE A2] keep full-size copy
        self.mod_img = self.mod_full.resize(self.image_size_small)
        # Binary mask
        self.mask_img = Image.open(path2).convert("L").resize(self.image_size_large, resample=Image.Resampling.NEAREST)  
        # Unmodified image
        self.unmod_full = Image.open(path3).convert("RGBA")        # [CHANGE A2] keep full-size copy
        self.unmod_img = self.unmod_full.resize(self.image_size_small)
        # small mask
        self.small_mask_img = Image.open(path2).convert("L").resize(self.image_size_small, resample=Image.Resampling.NEAREST)  
        self.source_side = min(self.unmod_full.size)               # [CHANGE A2] real source resolution
        
        # [CHANGE C3] when navigating back to an image edited during this run, pick up the
        # work in progress instead of starting again from the baseline guess.
        if restored_mask is not None:
            self.mask = restored_mask.copy()
        else:
            self.mask = self.mask_img.copy() # for just the raw np values
        # [CHANGE B1] the overlay is drawn by _render_overlay() once canvas4 exists
        self.overlay_image = None
        self.tk_overlay = None
        
        # Convert images for display
        self.tk_img1 = ImageTk.PhotoImage(self.mod_img)
        self.tk_img2 = ImageTk.PhotoImage(self.mask)  # Display path2 as editable
        self.tk_img3 = ImageTk.PhotoImage(self.unmod_img)
        self.small_mask = ImageTk.PhotoImage(self.small_mask_img)
        
        # Create labels and canvas
        self.frame = tk.Frame(root)
        self.frame.pack(expand=True, fill=tk.BOTH)

        span = 5
        self.label2 = tk.Label(self.frame, text="Image 2 (Editable Mask)")
        self.label2.grid(row=0, column=1, sticky="nsew")
        self.canvas2 = tk.Canvas(self.frame, width=self.image_size_large[0], height=self.image_size_large[1])
        self.canvas2.grid(row=1, column=1, sticky="nsew",columnspan=span,rowspan=span)
        # [CHANGE B2] remember the single image item so refreshing the mask never stacks
        # a new copy on top of the old one
        self.mask_item = self.canvas2.create_image(0, 0, anchor=tk.NW, image=self.tk_img2)
        self.canvas2.bind("<Button-1>", self.paint)
        self.canvas2.bind("<B1-Motion>", self.paint)
        # [CHANGE A4] hovering the editable mask also drives the overlay-panel marker
        self.canvas2.bind("<Motion>", self.on_mask_motion)
        self.canvas2.bind("<Leave>", self.on_mask_leave)
        
        self.label1 = tk.Label(self.frame, text="Filtered Image")
        self.label1.grid(row=0, column=0, sticky="nsew")
        self.canvas1 = tk.Label(self.frame, image=self.tk_img1)
        self.canvas1.grid(row=1, column=0, sticky="nsew")
        
        self.label3 = tk.Label(self.frame, text="Original Image")
        self.label3.grid(row=2, column=0, sticky="nsew")
        self.canvas3 = tk.Label(self.frame, image=self.tk_img3)
        self.canvas3.grid(row=3, column=0, sticky="nsew")
        
        # --------------------------------------------------------------------
        # [CHANGE A1] the overlay panel is now a tk.Canvas (it used to be a tk.Label,
        # which cannot host drawn items), so the mouse marker can be painted on top of it.
        # --------------------------------------------------------------------
        self.label4 = tk.Label(self.frame, text="Overlay Image")
        self.label4.grid(row=4, column=0, sticky="nsew")
        self.canvas4 = tk.Canvas(self.frame,
                                 width=self.image_size_small[0],
                                 height=self.image_size_small[1],
                                 highlightthickness=0, bd=0)
        self.canvas4.grid(row=5, column=0, sticky="nsew")
        # [CHANGE A2/A4] panel reacts to resizing and to the mouse moving over it
        self.canvas4.bind("<Configure>", self.on_panel_resize)
        self.canvas4.bind("<Motion>", self.on_panel_motion)
        self.canvas4.bind("<Leave>", self.on_panel_leave)

        # [CHANGE B0] attribute-name fix: this block used to reuse self.label1 / self.canvas1,
        # silently overwriting the reference to the "Filtered Image" widgets.
        self.label_base = tk.Label(self.frame, text="Baseline mask")
        self.label_base.grid(row=0, column=span+1, sticky="nsew")
        self.canvas_base = tk.Label(self.frame, image=self.small_mask)
        self.canvas_base.grid(row=1, column=span+1, sticky="nsew")
        
        # Controls
        self.control_frame = tk.Frame(root)
        self.control_frame.pack(fill=tk.X)
        
        self.color = "black"
        self.brush_size = 25

        # # Buttons at the bottom of the frame
        # [CHANGE D2] the letter in brackets is the shortcut for that button (see HOTKEYS),
        # and the button is drawn sunken while that mode is the active one ([CHANGE D3]).
        # large black fill
        self.btn_large_black = tk.Button(self.control_frame, text="Large Black", command=lambda: self.set_large_black())
        self.btn_large_black.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # black fill
        self.btn_black = tk.Button(self.control_frame, text="Black" + hotkey_hint('black'), command=lambda: self.set_color("black",brush_size=self.brush_size))
        self.btn_black.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # white fill
        self.btn_white = tk.Button(self.control_frame, text="White" + hotkey_hint('white'), command=lambda: self.set_color("white",brush_size=self.brush_size))
        self.btn_white.pack(side=tk.LEFT, expand=True, fill=tk.X)
        #isolate only the largest blob
        self.btn_ISO = tk.Button(self.control_frame, text="Isolate Largest", command=self.isolate_large_blob)
        self.btn_ISO.pack(side=tk.LEFT, expand=True, fill=tk.X)

        # reset binary image
        self.btn_reset = tk.Button(self.control_frame, text="Reset" + hotkey_hint('reset'), command=self.reset_image)
        self.btn_reset.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # save the mask
        self.btn_save = tk.Button(self.control_frame, text="Save" + hotkey_hint('save'), command=self.save_image)
        self.btn_save.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # prev img
        self.btn_prev = tk.Button(self.control_frame, text="Prev" + hotkey_hint('prev'), command=self.prev_image)
        self.btn_prev.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # next img
        self.btn_next = tk.Button(self.control_frame, text="Next" + hotkey_hint('next'), command=self.next_image)
        self.btn_next.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # quit application
        self.btn_QUIT = tk.Button(self.control_frame, text="Quit", command=self.quit_app)
        self.btn_QUIT.pack(side=tk.LEFT, expand=True, fill=tk.X)

        # [CHANGE C4] there is nowhere to go before the first image
        if i == 0:
            self.btn_prev.config(state=tk.DISABLED)
        # [CHANGE C4] make the last step obvious
        if total and i == total - 1:
            self.btn_next.config(text="Finish" + hotkey_hint('next'))

        # [CHANGE D1] the letter shortcuts. Bound on the toplevel window, so they work
        # wherever the mouse happens to be (over the mask, over the panel, over a button).
        self._hotkey_last = {}     # [CHANGE D5] last accepted press per action
        self._keys_held = set()    # [CHANGE D5] keys currently held down
        for keysym, action in HOTKEYS.items():
            self.root.bind("<KeyPress-%s>" % keysym, self.make_hotkey(action))
            self.root.bind("<KeyRelease-%s>" % keysym, self.release_hotkey)
        # [CHANGE D4] the arrow keys and Ctrl+S from the previous round still work as well
        self.root.bind("<Left>", self.make_hotkey('prev'))
        self.root.bind("<KeyRelease-Left>", self.release_hotkey)
        self.root.bind("<Right>", self.make_hotkey('next'))
        self.root.bind("<KeyRelease-Right>", self.release_hotkey)
        self.root.bind("<Control-s>", self.make_hotkey('save'))
        self._sync_tool_buttons()  # [CHANGE D3] show which brush mode is currently active
        # [CHANGE C6] closing the window with the X / Alt-F4 now goes through the
        # unsaved-edit guard and then advances, exactly like the old destroy-on-close behaviour
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # first paint of the bottom-left overlay panel (needs canvas4 to exist)
        self.canvas4.after_idle(self._render_overlay)

    # ------------------------------------------------------------------
    # mask / overlay rendering
    # ------------------------------------------------------------------
    def _show_mask(self):
        """[CHANGE B2] Update the editable-mask image in place. The old code called
        create_image() on every brush stroke, so the canvas ended up holding a stack of
        dead image items (402 of them after 400 strokes in _dev/bench_paint.py) that
        Tk keeps track of forever."""
        self.tk_img2 = ImageTk.PhotoImage(self.mask)
        if self.mask_item is None:
            self.mask_item = self.canvas2.create_image(0, 0, anchor=tk.NW, image=self.tk_img2)
        else:
            self.canvas2.itemconfig(self.mask_item, image=self.tk_img2)

    def _overlay_side(self):
        """[CHANGE A2] Side length (px) the overlay panel can currently show: as big as the
        panel cell allows, but never bigger than the source images."""
        cw = self.canvas4.winfo_width()
        ch = self.canvas4.winfo_height()
        if cw <= 1 or ch <= 1:          # panel not mapped yet -> wait for <Configure>
            return 0
        return int(min(cw, ch, self.source_side))

    def _render_overlay(self):
        """[CHANGE B1] Rebuild the overlay from the current mask and show it fitted to
        canvas4. Called after every edit (paint / isolate / reset) and after a resize."""
        side = self._overlay_side()
        if side == 0:                   # not ready yet, <Configure> will call us again
            return
        self.overlay_image = self.create_overlay(size=(side, side))
        self.tk_overlay = ImageTk.PhotoImage(self.overlay_image)
        cw = self.canvas4.winfo_width()
        ch = self.canvas4.winfo_height()
        self._ov_side = side
        self._ov_offx = int((cw - side) // 2)
        self._ov_offy = int((ch - side) // 2)
        if self._overlay_item is None:
            self._overlay_item = self.canvas4.create_image(self._ov_offx, self._ov_offy,
                                                           anchor=tk.NW, image=self.tk_overlay)
        else:
            self.canvas4.itemconfig(self._overlay_item, image=self.tk_overlay)
            self.canvas4.coords(self._overlay_item, self._ov_offx, self._ov_offy)
        # keep the picture underneath the cursor marker
        self.canvas4.tag_lower(self._overlay_item)
        # the marker has to be redrawn because the panel image was replaced
        self.draw_cursor()

    def isolate_large_blob(self):

        temp_mask_np = (np.asarray(self.mask)/255).astype(np.uint8)
        temp_mask_torch = leave_only_largest_blob(temp_mask_np, device=device, num_iterations = 500)
        temp_mask_np = temp_mask_torch.cpu().numpy().astype(np.uint8)*255

        self.mask = Image.fromarray(temp_mask_np)

        self._show_mask()               # [CHANGE B2]
        self._dirty = True              # [CHANGE C2] this is an edit too
        self._render_overlay()          # [CHANGE B1] the overlay used to go stale here

        print('TEST')
    
    # ------------------------------------------------------------------
    # [CHANGE D1] keyboard shortcuts. Each one calls exactly the same method as its button,
    # so the guard for unsaved edits and the refresh of the overlay panel still happen.
    # ------------------------------------------------------------------
    def make_hotkey(self, action):
        """Build the callback for one shortcut (or arrow key)."""
        def on_key(event):
            # [CHANGE D5] Windows keeps firing KeyPress while you hold a key down. Without
            # this, holding 'd' would walk through every image in the plate (or holding 'r'
            # would reload the mask over and over).
            if event.keysym in self._keys_held:
                return "break"
            now = time.monotonic()
            if now - self._hotkey_last.get(action, -HOTKEY_GUARD) < HOTKEY_GUARD:
                return "break"
            self._hotkey_last[action] = now
            self._keys_held.add(event.keysym)
            self.run_hotkey(action)
            return "break"                     # stop the key reaching any other binding
        return on_key

    def release_hotkey(self, event):
        """[CHANGE D5] The key came back up, so the next press of it counts again."""
        self._keys_held.discard(event.keysym)
        return None

    def run_hotkey(self, action):
        """Do what the matching button would do."""
        if action == 'save':
            self.save_image()
        elif action == 'next':
            self.next_image()
        elif action == 'prev':
            self.prev_image()
        elif action == 'black':
            self.set_color("black", brush_size=self.brush_size)
        elif action == 'white':
            self.set_color("white", brush_size=self.brush_size)
        elif action == 'reset':
            self.reset_image()

    def _sync_tool_buttons(self):
        """[CHANGE D3] Sink the button of the brush mode you are in, so you can see the
        active tool without looking for it after using the keyboard."""
        if not hasattr(self, 'btn_black'):
            return
        if self.color == "black" and self.brush_size >= 200:
            active = self.btn_large_black
        elif self.color == "black":
            active = self.btn_black
        else:
            active = self.btn_white
        for btn in (self.btn_large_black, self.btn_black, self.btn_white):
            btn.config(relief=tk.SUNKEN if btn is active else tk.RAISED)

    def set_large_black(self):
        """Set large brush size for black color."""
        self.color = "black"
        self.brush_size = 200  # Set a larger brush size
        self.draw_cursor()     # [CHANGE A4] reflect the new brush size straight away
        self._sync_tool_buttons()   # [CHANGE D3]

    def set_color(self, color, brush_size = None):
        """Set drawing color."""
        self.color = color
        if brush_size is None:
            self.brush_size = 10 if color == "white" else 10
        else:
            self.brush_size = brush_size
        self.draw_cursor()     # [CHANGE A4] reflect the new brush size straight away
        self._sync_tool_buttons()  # [CHANGE D3]

    def create_overlay(self, size=None):
        """Create an overlay image based on img1 and the current mask.
        [CHANGE A2] `size` lets the overlay be rendered at the panel's real pixel size
        (defaults to the old small thumbnail size, so nothing changes unless the panel is bigger)."""

        if size is None:
            data = [self.mask.size,self.mod_img.size,self.mask_img.size]
            resize_size = min(data, key = lambda t: t[1])
        else:
            resize_size = tuple(size)
        overlay_color = np.array([0,255,0,255],dtype=np.uint8)
        alpha = 0.4

        # [CHANGE A2] start from the untouched source image and scale it to the target size,
        # so a bigger panel shows genuinely more detail instead of an upscaled thumbnail.
        # [CHANGE A6] the scaled source never changes while you paint, so cache it per size.
        if self._src_cache is not None and self._src_cache[0] == resize_size:
            img = self._src_cache[1]
        else:
            img = np.asarray(self.unmod_full.resize(resize_size)).copy()
            self._src_cache = (resize_size, img)
        mask = np.array(self.mask.resize(resize_size))>0
        out = img.copy()
        out[mask] = (1-alpha) * img[mask] + alpha * overlay_color
        # this should really be a green mask overlay on top of the filtered (mod) image
        return Image.fromarray(out)
    
    def paint(self, event):

        """Allow drawing on the mask by adding (white) or removing (black) parts."""
        draw = ImageDraw.Draw(self.mask)
        color = 255 if self.color == "white" else 0
        draw.ellipse((event.x - self.brush_size//2, event.y - self.brush_size//2, 
                      event.x + self.brush_size//2, event.y + self.brush_size//2), fill=color)
        
        self._dirty = True              # [CHANGE C2] remember that there is unsaved work
        # Update displayed mask
        self._show_mask()               # [CHANGE B2]

        # Update overlay image (this also redraws the panel marker via draw_cursor)
        self._cursor = (event.x, event.y)   # [CHANGE A4]
        self._cursor_from_panel = False
        self._render_overlay()              # [CHANGE B1]
        self.preview_brush(event)
    
    def preview_brush(self, event):
        """Show a preview of the brush size (colour kept in sync with the panel marker)."""
        self.canvas2.delete("brush_preview")
        self.canvas2.create_oval(event.x - self.brush_size//2, event.y - self.brush_size//2, 
                                 event.x + self.brush_size//2, event.y + self.brush_size//2, 
                                 outline=BRUSH_PREVIEW_COLOR, tags="brush_preview")

    # ------------------------------------------------------------------
    # [CHANGE A4] mouse tracking. The marker is made of canvas items only, so moving the
    # mouse never rebuilds an image: it is cheap and follows the pointer immediately.
    # ------------------------------------------------------------------
    def _mask_to_panel(self, x, y):
        """Convert editable-mask (large canvas) coordinates to overlay-panel coordinates."""
        f = self._ov_side / float(self.mask.size[0]) if self._ov_side else 0.0
        return self._ov_offx + x * f, self._ov_offy + y * f

    def _panel_to_mask(self, x, y):
        """Convert overlay-panel coordinates back to editable-mask (large canvas) coordinates."""
        f = self.mask.size[0] / float(self._ov_side) if self._ov_side else 0.0
        return (x - self._ov_offx) * f, (y - self._ov_offy) * f

    def draw_cursor(self):
        """Draw the pointer marker on the overlay panel, plus the mirrored crosshair on the
        editable mask when the pointer is sitting on the panel."""
        if not hasattr(self, 'canvas4'):
            return
        self.canvas4.delete("cursor")
        self.canvas2.delete("mirror_cursor")
        if self._cursor is None or self._ov_side == 0:
            return
        mx, my = self._cursor
        # ---- marker on the bottom-left overlay panel ----
        px, py = self._mask_to_panel(mx, my)
        f = self._ov_side / float(self.mask.size[0])
        r = max(CURSOR_MIN_RADIUS, self.brush_size * 0.5 * f)
        self.canvas4.create_oval(px - r, py - r, px + r, py + r,
                                 outline=BRUSH_PREVIEW_COLOR, tags="cursor")
        x0 = self._ov_offx
        y0 = self._ov_offy
        x1 = self._ov_offx + self._ov_side
        y1 = self._ov_offy + self._ov_side
        self.canvas4.create_line(x0, py, x1, py, width=CURSOR_LINE_WIDTH,
                                 fill=CURSOR_CROSS_COLOR, tags="cursor")
        self.canvas4.create_line(px, y0, px, y1, width=CURSOR_LINE_WIDTH,
                                 fill=CURSOR_CROSS_COLOR, tags="cursor")
        # ---- mirrored crosshair on the editable mask (pointer came from the panel) ----
        if self._cursor_from_panel:
            self.canvas2.create_line(0, my, self.image_size_large[0], my,
                                     width=CURSOR_LINE_WIDTH, fill=CURSOR_CROSS_COLOR,
                                     tags="mirror_cursor")
            self.canvas2.create_line(mx, 0, mx, self.image_size_large[1],
                                     width=CURSOR_LINE_WIDTH, fill=CURSOR_CROSS_COLOR,
                                     tags="mirror_cursor")
            rm = self.brush_size * 0.5
            self.canvas2.create_oval(mx - rm, my - rm, mx + rm, my + rm,
                                     outline=CURSOR_CROSS_COLOR, tags="mirror_cursor")

    def on_mask_motion(self, event):
        """Pointer moved over the editable mask: keep the red brush circle there and push
        the same position onto the overlay panel."""
        self._cursor = (event.x, event.y)
        self._cursor_from_panel = False
        self.preview_brush(event)
        self.draw_cursor()

    def on_mask_leave(self, event):
        self._cursor = None
        self.canvas2.delete("brush_preview")
        self.canvas2.delete("mirror_cursor")
        self.canvas4.delete("cursor")

    def on_panel_motion(self, event):
        """Pointer moved over the overlay panel: show where that lands on the editable mask."""
        if self._ov_side == 0:
            return
        mx, my = self._panel_to_mask(event.x, event.y)
        if 0 <= mx < self.mask.size[0] and 0 <= my < self.mask.size[1]:
            self._cursor = (mx, my)
            self._cursor_from_panel = True
        else:
            self._cursor = None
        self.draw_cursor()

    def on_panel_leave(self, event):
        self._cursor = None
        self.canvas4.delete("cursor")
        self.canvas2.delete("mirror_cursor")

    def on_panel_resize(self, event):
        """[CHANGE A2] The panel changed size, so re-render the overlay at the new size and
        recompute the coordinate mapping."""
        self._render_overlay()

    def reset_image(self):
        """Reload and reset path2 image."""
        # [CHANGE C5] use this image's own path (the old code read the global `path2`, which
        # only worked by accident) and resize with NEAREST, exactly like the initial load.
        self.mask = Image.open(self.path2).convert("L").resize(self.image_size_large, resample=Image.Resampling.NEAREST)
        self._dirty = False                 # [CHANGE C2]
        self._show_mask()                   # [CHANGE B2]
        self._render_overlay()              # [CHANGE B1] the old code re-computed the overlay
                                            # but never displayed it, so the panel stayed stale
    
    def save_image(self):
        """Save the edited mask as path2_edit.png."""
        path2_edit = os.path.join(self.export_path,self.export_name + '.png')
        self.mask.save(path2_edit)
        self._dirty = False                 # [CHANGE C2] the work is on disk now
        print(f"Mask saved as {path2_edit}")
    
    # ------------------------------------------------------------------
    # [CHANGE C1] navigation. prev/next no longer guess what the main loop should do:
    # they record the requested direction and close the window; the main loop then reopens
    # the editor for the image they asked for.
    # ------------------------------------------------------------------
    def _confirm_leave(self):
        """[CHANGE C2] Never lose work silently. Returns False when the user backs out."""
        if not self._dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved edits",
            "Image %d has edits that have not been saved yet.\n\n"
            "Yes    - save and continue\n"
            "No     - continue without saving\n"
            "Cancel - stay on this image" % (self.i + 1))
        if answer is None:
            return False
        if answer:
            self.save_image()
        return True

    def _leave(self, action):
        if not self._confirm_leave():
            return
        self.action = action
        self.root.destroy()

    def next_image(self):
        """Destroy the window so the next one can be loaded"""
        self._leave('next')

    def prev_image(self):
        """[CHANGE C1] Go back to the previous image (works, and keeps your edits in memory)."""
        # [CHANGE C9] there is no image before the first one; the button is disabled there but
        # the Left-arrow shortcut still reaches this method, so guard it too.
        if self.i == 0:
            return
        self._leave('prev')

    def on_close(self):
        """[CHANGE C6] Handle the window-manager close button like "Next", as before."""
        self._leave('next')

    def quit_app(self):
        """this end the program"""
        # [CHANGE C7] sys.exit() inside a Tk callback raises SystemExit in the middle of the
        # Tcl interpreter; set the action and close the window cleanly instead.
        # [CHANGE C2] Quit now asks about unsaved edits as well, instead of dropping them silently.
        self._leave('quit')
        
# ---------------------------------------------------------------------------
# [CHANGE C8] the block that used to live under "if __name__ == '__main__'" is now a
# function, so the editor can be started from a specific image and the navigation loop can
# be driven by the test harness without a human clicking through five windows.
# ---------------------------------------------------------------------------
def main(path_to_images='Fluorescent_test_010',
         output_path='exported_masks',
         start_index=0):

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

    # [CHANGE C1] the old code was a plain "for i, paths in enumerate(zip(...))", which could
    # only ever move forward. Build the list first and drive it with an index so Prev works.
    images = list(zip(unmod_imgs, mask_imgs, mod_imgs))
    # [CHANGE C3] masks edited during this run, kept in memory per index so going back and
    # forth does not throw away work that has not been saved yet.
    edited_masks = {}

    i = start_index
    while 0 <= i < len(images):
        this_imgs_paths = images[i]
        # File paths (change accordingly)
        # path1 intial image
        path1 = this_imgs_paths[2]
        # masked image
        path2 = this_imgs_paths[1]
        # modified image that created the mask
        path3 = this_imgs_paths[0]

        # if there is no mod image then it should be created on the spot

        root = tk.Tk()
        app = ImageEditor(root, path1=path1, path2=path2, path3=path3, i=i,
                          export_path=output_path, total=len(images),
                          restored_mask=edited_masks.get(i))
        root.mainloop()

        # [CHANGE C1/C3] remember the state of the image we are leaving and where the user
        # wanted to go. Closing the window without pressing a button behaves like Next.
        edited_masks[i] = app.mask
        action = app.action if app.action in ('next', 'prev') else 'next'
        if app.action == 'quit':
            print('Quit requested')
            break
        i += -1 if action == 'prev' else 1

        print('end loop')

    print('EOF')
    # [CHANGE C8] report where the run ended (useful for the harness and for resuming later)
    return i


if __name__ == "__main__":
    main()
