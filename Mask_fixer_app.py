import tkinter as tk
from tkinter import messagebox, ttk              # [CHANGE C2] dialog / [CHANGE G3] jump selector
from PIL import Image, ImageTk, ImageDraw
import numpy as np
import os, time, json, torch, glob, subprocess, platform, sys, cv2
from natsort import natsorted
from kornia.contrib import connected_components
from pathlib import Path
from torch import nn

# Device configuration
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
if device.type == 'cpu' and torch.backends.mps.is_available():
    device = torch.device('mps')

output_path = 'exported_masks'
path_to_images = 'Fluorescent_markers_006-1'

# ---------------------------------------------------------------------------
# [CHANGE A5] Cursor-overlay look (safe to tweak). The brush footprint is drawn in the
# same colour on both the editable mask and the overlay panel so the two always match.
# ---------------------------------------------------------------------------
BRUSH_PREVIEW_COLOR = "red"     # circle = the footprint the brush will actually paint
CURSOR_CROSS_COLOR  = "cyan"    # thin crosshair = the exact pointer position
CURSOR_LINE_WIDTH   = 1         # crosshair thickness
CURSOR_MIN_RADIUS   = 3         # keep very small brushes visible on the shrunken panel

# ---------------------------------------------------------------------------
# [CHANGE E1] The two live panels swapped roles, so these constants describe the
# green overlay that is now painted in the MIDDLE (large) panel:
#     middle  = original image with the live mask shown on it as a green wash;
#               this is where you paint/edit.
#     bottom-left = the live binary mask itself (what used to be in the middle).
# Change OVERLAY_BASE to "mod" to blend the mask over the filtered image instead
# of the original one (the old code had a TODO asking for exactly that switch).
# ---------------------------------------------------------------------------
OVERLAY_COLOR = (0, 255, 0, 255)   # the green blended over the base image
OVERLAY_ALPHA = 0.40               # 0.0 = image only, 1.0 = solid green mask
OVERLAY_BASE  = "unmod"            # "unmod" = Original Image, "mod" = Filtered Image

# ---------------------------------------------------------------------------
# [CHANGE E2] Responsive layout. The old hard-coded sizes (290 px thumbnails,
# 290*3.25 for the editable mask) are gone: the window is sized from the screen
# and every panel redraws itself to fit whatever cell the grid gives it.
# ---------------------------------------------------------------------------
MASK_NATIVE_SIDE = 942    # working resolution of the editable mask. This is exactly
                          # int(290 * 3.25) = 942, i.e. what the old version saved, so
                          # exported PNGs keep the same size as before.
MIN_BIG_SIDE     = 360    # preferred smallest size of the editable panel
MIN_SMALL_SIDE   = 150    # preferred smallest size of the side panels
                          # [CHANGE H1] both are a preference now: on a screen too small for
                          # them the panels go smaller anyway, because the button row must
                          # never be cut off.
MAX_UPSCALE      = 3      # never blow a 512 px source up by more than 3x
# [CHANGE H1] SCREEN_MARGIN is gone. It used to mean "guess how much screen the taskbar and
# the window frame eat"; now the taskbar area is read from Windows (_work_area) and the
# window frame is DECOR_H below, so a single guess is no longer needed.
CHROME_H         = 170    # title bar + the two label rows + the button row.
                          # [CHANGE H1] this is only the *first* estimate now: it is used
                          # before the widgets exist. Once they do, _fit_window() measures
                          # the real height of the labels + button row and re-plans.
DECOR_H          = 40     # [CHANGE H1] the space the window manager itself takes: the title
                          # bar plus borders. Measured on this machine: 31 px above the part
                          # Tk controls, so 40 leaves slack. Tk's geometry()/winfo_height()
                          # speak about the *client* area only, which is why the old code
                          # could put the whole button row under the taskbar.
EDGE             = 12     # [CHANGE H1] slack kept clear at the edges of the usable screen

# ---------------------------------------------------------------------------
# [CHANGE H2] The brush sizes are named constants now. "Large Black" used to leave
# self.brush_size at 200, and the Black / White buttons passed that same live value
# back in, so the big swatch stuck. They now always pass SMALL_BRUSH_SIZE.
# ---------------------------------------------------------------------------
SMALL_BRUSH_SIZE = 25     # the ordinary Black / White brush
LARGE_BRUSH_SIZE = 200    # "Large Black" (button, and the G shortcut - see [CHANGE H3])

# ---------------------------------------------------------------------------
# [CHANGE G1] Resume support. A tiny JSON file next to the program remembers which image of
# which folder you were last looking at, so you can close the program part way through a plate
# and open it again on the same well. Change this name (or delete the file) to reset it; the
# file is read-only-to-humans in the sense that nothing in it is needed to recover your work -
# your masks live in the export folder.
# ---------------------------------------------------------------------------
STATE_FILENAME = '.mask_fixer_state.json'
JUMP_LIST_HEIGHT = 18     # [CHANGE G3] rows shown in the jump-selector drop-down

# ---------------------------------------------------------------------------
# [CHANGE D1] Keyboard shortcuts for the buttons: plain letters, no Ctrl needed.
# Delete a line to switch a shortcut off, or change the letter to re-map it.
# Note: 'q' is the black brush, not quit, as you asked - Quit deliberately has no letter key.
# [CHANGE H3] 'g' added for the Large Black brush, which had no shortcut before.
# ---------------------------------------------------------------------------
HOTKEYS = {
    'q': 'black',        # switch to the black (erase) brush, small size
    'e': 'white',        # switch to the white (add) brush, small size
    'g': 'large_black',  # [CHANGE H3] switch to the Large Black brush, big size
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


# ---------------------------------------------------------------------------
# [CHANGE G2] Resume / jump helpers.
# The run is identified by its image folder, and each image inside it is identified by the
# name of its mask file without the "_mask.png" tail (e.g. "A1_123"), which is stable even if
# images are added or removed later - that is why the resume stores a NAME and not a number.
# ---------------------------------------------------------------------------
def image_names_from(images):
    """The label each image is known by in the jump selector."""
    return [Path(p[1]).stem for p in images]


def saved_names(output_path):
    """Which images already have an edited mask sitting in the export folder."""
    try:
        return {Path(f).stem for f in os.listdir(output_path)}
    except OSError:
        return set()


def load_state(state_path=STATE_FILENAME):
    """Read the resume file. Never raises: a missing, locked or corrupt file just means
    "no memory", which is the same as starting fresh."""
    try:
        with open(state_path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(folder, name, state_path=STATE_FILENAME):
    """Remember which image of which folder the user was last looking at.
    Written via a temporary file + os.replace so a crash mid-write cannot leave half a file."""
    try:
        state = load_state(state_path)
        state[str(folder)] = {'last': str(name),
                              'updated': time.strftime('%Y-%m-%d %H:%M:%S')}
        tmp = str(state_path) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
        os.replace(tmp, state_path)
        return True
    except OSError as exc:
        print('warning: could not write %s (%s)' % (state_path, exc))
        return False


def resolve_start_index(names, output_path, folder,
                        state_path=STATE_FILENAME, start_index=None):
    """Work out which image to open when the program starts:
      1. an explicit start_index always wins (that is what the test harness uses);
      2. otherwise the remembered image for this folder, if it still exists;
      3. otherwise the first image that has no saved mask yet;
      4. otherwise the first image."""
    if not names:
        return 0
    if start_index is not None:
        return max(0, min(int(start_index), len(names) - 1))
    remembered = load_state(state_path).get(str(folder), {}).get('last')
    if remembered in names:
        return names.index(remembered)
    done = saved_names(output_path)
    for k, name in enumerate(names):
        if name not in done:
            return k
    return 0


# ---------------------------------------------------------------------------
# [CHANGE E3] One tiny helper used by all five image slots in the window.
# A Panel is a tk.Canvas plus the bookkeeping needed to always show an image
# *fitted* (square, centred) inside whatever size the window currently gives
# that canvas. Because every image slot is a Panel, the whole window resizes:
# no panel is ever clipped and no panel is ever left at a stale fixed size.
# ---------------------------------------------------------------------------
class Panel:
    def __init__(self, canvas, cap=0, resample=Image.Resampling.NEAREST):
        self.canvas = canvas
        self.cap = int(cap)              # largest square this panel may ever draw
        self.resample = resample         # how the source is scaled to fit the cell
        self.side = 0                    # side (px) of the square actually displayed
        self.offx = 0                    # left edge of that square inside the canvas
        self.offy = 0                    # top edge of that square inside the canvas
        self.item = None                 # the single canvas image item (never stacked)
        self.tk = None                   # the PhotoImage, kept alive so Tk shows it
        self._region = None              # [CHANGE F1] scratch PhotoImage for partial updates

    def fit(self):
        """Work out the biggest square that fits the canvas as it is sized right now.
        Returns 0 when the canvas has not been mapped yet (a <Configure> will follow)."""
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            self.side = 0
            return 0
        side = min(cw, ch)
        if self.cap:
            side = min(side, self.cap)
        self.side = int(side)
        self.offx = int((cw - self.side) // 2)
        self.offy = int((ch - self.side) // 2)
        return self.side

    def show(self, img, already_sized=False):
        """Display `img` fitted to the canvas. `already_sized` means the caller built the
        image at exactly self.side, so it must not be rescaled a second time."""
        if self.fit() == 0:
            return False
        if not already_sized and img.size != (self.side, self.side):
            img = img.resize((self.side, self.side), resample=self.resample)
        if self.tk is not None and self.tk.width() == img.size[0] and self.tk.height() == img.size[1]:
            self.tk.paste(img)           # [CHANGE E3] in-place refresh: no new PhotoImage
        else:
            self.tk = ImageTk.PhotoImage(img)
        if self.item is None:
            self.item = self.canvas.create_image(self.offx, self.offy, anchor=tk.NW, image=self.tk)
        else:
            self.canvas.itemconfig(self.item, image=self.tk)
            self.canvas.coords(self.item, self.offx, self.offy)
        self.canvas.tag_lower(self.item)   # markers drawn on top always stay visible
        return True

    def refresh(self, arr):
        """Push a whole display-sized numpy buffer into the displayed PhotoImage.
        [CHANGE F1] only used for full rebuilds now; a brush dab uses put_region() instead."""
        if self.tk is None or self.side <= 0:
            return False
        self.tk.paste(Image.fromarray(arr))
        return True

    def put_region(self, img, x, y):
        """[CHANGE F1] Blit a small rectangle into the displayed photo *inside Tk*
        (photo copy -to), instead of handing Tk the whole image again.

        On this machine, at an 1102 px panel, pushing the whole photo costs ~10.7 ms per
        brush dab (a 4.8 MB Image.fromarray + paste), which is why painting felt laggy.
        Copying only the square the brush touched costs 0.8 ms for the 25 px brush,
        1.0 ms at 60 px and 1.5 ms for the 200 px "Large Black" brush - the size of the
        panel stops mattering, only the size of the brush does.
        Returns False if Tk refused, so the caller can fall back to a full refresh."""
        if self.tk is None or self.side <= 0:
            return False
        try:
            w, h = img.size
            if (self._region is None or self._region.width() != w
                    or self._region.height() != h):
                self._region = ImageTk.PhotoImage(img)
            else:
                self._region.paste(img)
            self.canvas.tk.call(str(self.tk), 'copy', str(self._region), '-to', int(x), int(y))
            # [CHANGE F2] Tk changes the photo but does NOT repaint it straight away: the
            # redisplay is queued as an idle task, and while the mouse button is held down the
            # event queue never goes idle - so the stroke only appeared once the drag ended.
            # (That is the bug you hit: the whole-image paste of the previous build happened to
            # flush the redraw itself, which is why the bottom-left panel always looked live.)
            # Forcing the idle tasks repaints just that rectangle, immediately, and it costs
            # about 0.7 ms per dab. Measured with an occlusion-proof capture of this window:
            # without this line the dab is invisible on screen mid-drag, with it 89% of the dab
            # square is green on screen, and the same for erasing.
            self.canvas.update_idletasks()
            return True
        except tk.TclError:
            return False

    # --- coordinate mapping, done through normalised 0..1 values so the caller never
    # --- has to care about the difference between screen px, mask px and source px.
    def to_norm(self, x, y):
        if self.side <= 0:
            return None
        return ((x - self.offx) / float(self.side), (y - self.offy) / float(self.side))

    def from_norm(self, u, v):
        return (self.offx + u * self.side, self.offy + v * self.side)


class Normalize(nn.Module):
    def __init__(self):
        """
        Initializes the Normalize module to normalize a tensor of any shape
        between 0 and 1 based on 3 standard deviations of the input data.
        """
        super(Normalize, self).__init__()

    def forward(self, tensor, std_bound = 3):
        """
        Normalizes a tensor of any shape between 0 and 1 using 3 standard deviations
        of the data's mean, then clips the values to the [0, 1] range.

        Args:
            tensor (torch.Tensor): An n-dimensional tensor to be normalized.

        Returns:
            torch.Tensor: The normalized and clipped tensor.
        """
        # Compute the mean and standard deviation of the input tensor
        mean = tensor.mean()
        std = tensor.std()

        # Define the lower and upper bounds based on 3 standard deviations
        lower_bound = mean - std_bound * std
        upper_bound = mean + std_bound * std

        if lower_bound < 0:
            lower_bound = 0

        # Normalize the tensor between 0 and 1
        normalized_tensor = (tensor - lower_bound) / (upper_bound - lower_bound)

        # Clip values to be between 0 and 1
        normalized_tensor = torch.clamp(normalized_tensor, min=0.0, max=1.0)

        return normalized_tensor

class ImageEditor:
    # [CHANGE C1/C3] new optional arguments:
    #   total          -> number of images in the run, only used for the window title / button state
    #   restored_mask  -> PIL mask to start from when coming back to an already-edited image
    # [CHANGE G3] new optional argument:
    #   image_names    -> the names of every image in this run, for the jump selector
    def __init__(self, root, path1, path2, path3, i, export_path, total=None, restored_mask=None,
                 image_names=None):

        # [CHANGE E2] the fixed sizes are gone (they were: s = 290 for the thumbnails and
        # 290 * 3.25 for the editable mask). Only the *working resolution* of the mask is
        # fixed now, and it is deliberately the same 942 px as before so saved masks are
        # unchanged. Everything the user sees is sized from the screen - see _plan_layout().
        self.image_size_small = (MIN_SMALL_SIDE, MIN_SMALL_SIDE)   # kept for reference only
        self.image_size_large = self.mask_size = (MASK_NATIVE_SIDE, MASK_NATIVE_SIDE)

        self.root = root
        self.root.focus_force()
        # [CHANGE C4] show position in the sequence, e.g. "Image 3 of 5" (1-based for the user)
        title = "Image Editor --- Image " + str(i + 1)
        if total:
            title += " of " + str(total)
        self.root.title(title)
        # [CHANGE E2] was: self.root.geometry("+50+1") which let Tk size the window from the
        # (fixed) widgets. Now the window is sized from the screen and the widgets follow it.
        self._plan_layout()

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
        # [CHANGE G3] every image in this run, by name, for the jump selector. When nothing is
        # passed (e.g. a hand-written call) the selector just offers this one image.
        self.image_names = list(image_names) if image_names else [self.export_name]
        # [CHANGE C1] what the user asked for when the window closed: 'next' | 'prev' | 'quit' | None
        self.action = None
        # [CHANGE G3] and, for a jump, which image they asked for (index into image_names)
        self.goto_index = None
        # [CHANGE C2] True as soon as the mask is touched and not yet saved
        self._dirty = False
        # [CHANGE A4] pointer position expressed in editable-mask (working mask) pixels,
        # or None when the pointer is not over either image.
        self._cursor = None
        # [CHANGE A4] True when the pointer is over the mask panel (bottom left), which is
        # when the mirrored crosshair is drawn on the editable overlay panel.
        self._cursor_from_panel = False
        # [CHANGE E3] the geometry of each live panel now lives inside its Panel object
        # (self.panel_big / self.panel_mask / ...), so the old _ov_side / _ov_offx /
        # _ov_offy / _overlay_item fields are gone.
        # [CHANGE E7] buffers behind the editable panel, all at *display* resolution:
        self.disp_src = None      # base image (Original or Filtered), scaled once per size
        self.disp_mask = None     # the live mask sampled at display resolution (0 / 255)
        self.disp_img = None      # what is actually on screen (base + green wash)
        self._stroke_open = False # True between Button-1 and ButtonRelease-1
        # [CHANGE A6] cache of the source image scaled to the current panel size
        self._src_cache = None
        # [CHANGE E5] one queued re-render per canvas, so dragging the window edge does not
        # re-render thousands of times
        self._pending_render = set()
        # [CHANGE A2] cap the overlay resolution at the source resolution so the panel never
        # invents pixels that are not in the input images (the files are 512x512).
        self.source_side = 512
        
        # # Load images.
        # [CHANGE E4] the pre-scaled thumbnails (self.mod_img, self.unmod_img,
        # self.small_mask_img) and the pre-made PhotoImages (self.tk_img1 / tk_img2 /
        # tk_img3 / small_mask) are gone. Every panel keeps the full-size source and scales
        # it on demand inside Panel.show(), which is what lets the panels resize with the
        # window instead of being frozen at 290 px.
        # Modified (filtered) image - candidate base for the overlay, see OVERLAY_BASE
        # load in the image and normalize it then push it to the PIL type
        temp = Normalize()(torch.tensor(cv2.imread(path3)).to(torch.float32),std_bound=3)
        temp = np.asarray(temp*255).astype(np.uint8)

        self.mod_full = Image.open(path1).convert("RGBA")
        # Binary mask: the baseline guess, resampled to the working resolution
        self.mask_img = Image.open(path2).convert("L").resize(self.mask_size, resample=Image.Resampling.NEAREST)
        # Unmodified (original) image - the default base for the overlay
        # self.unmod_full = Image.open(path3).convert("RGBA")
        self.unmod_full = Image.fromarray(temp).convert("RGBA")
        # baseline mask at native resolution, for the top-right "Baseline mask" panel
        self.base_full = Image.open(path2).convert("L")
        self.source_side = min(self.unmod_full.size)               # [CHANGE A2] real source resolution
        
        # [CHANGE C3] when navigating back to an image edited during this run, pick up the
        # work in progress instead of starting again from the baseline guess.
        if restored_mask is not None:
            self.mask = restored_mask.copy() # for just the raw np values
        else:
            self.mask = self.mask_img.copy() # for just the raw np values
        # [CHANGE B1] both live panels are drawn by _render_all() once the canvases exist
        self.overlay_image = None
        self.tk_overlay = None
        
        # Create labels and canvas
        self.frame = tk.Frame(root)
        self.frame.pack(expand=True, fill=tk.BOTH)

        span = 5
        # --------------------------------------------------------------------
        # [CHANGE E2] stretch factors, the other half of making the window responsive.
        # Rows 1, 3 and 5 (the three image rows in the left column) and columns 1..span
        # (the middle panel) carry all the slack, so when the window grows the editable
        # panel grows most and the thumbnails stay proportional instead of being stranded
        # at their old fixed size.
        # --------------------------------------------------------------------
        self.frame.grid_columnconfigure(0, weight=0)
        for c in range(1, span + 1):
            self.frame.grid_columnconfigure(c, weight=1)
        self.frame.grid_columnconfigure(span + 1, weight=0)
        self.frame.grid_rowconfigure(0, weight=0)
        for r in range(1, span + 1):
            self.frame.grid_rowconfigure(r, weight=1 if r % 2 else 0)
        self.frame.grid_rowconfigure(span + 1, weight=0)

        # --------------------------------------------------------------------
        # [CHANGE E1] *** THE SWAP - part 1 of 2: the MIDDLE (large) panel. ***
        # It used to show the bare editable binary mask. It now shows the base image with
        # the live mask painted over it in green, and it is still the panel you paint on.
        # [CHANGE E4] the label now spans the whole middle column (it used to sit in one
        # grid column and would have been squashed once the column grew).
        # --------------------------------------------------------------------
        self.label2 = tk.Label(self.frame, text="Editable Overlay (mask shown in green)")
        self.label2.grid(row=0, column=1, columnspan=span, sticky="nsew")
        self.canvas2 = tk.Canvas(self.frame, width=self.big_side, height=self.big_side,
                                 highlightthickness=0, bd=0)
        self.canvas2.grid(row=1, column=1, sticky="nsew",columnspan=span,rowspan=span)
        # [CHANGE E3] the big panel is a Panel; cap keeps a 512 px source from being
        # blown up to an unusable size if someone maximises the window on a huge screen.
        self.panel_big = Panel(self.canvas2, cap=int(self.source_side * MAX_UPSCALE))
        # [CHANGE E3] the image item and its PhotoImage now live on the Panel (panel.item /
        # panel.tk), so the old self.mask_item field is gone. [CHANGE B2] still just one item.
        self.canvas2.bind("<Button-1>", self.paint)
        self.canvas2.bind("<B1-Motion>", self.paint)
        self.canvas2.bind("<ButtonRelease-1>", self.on_stroke_end)   # [CHANGE E7]
        self.canvas2.bind("<Configure>", self.on_big_resize)         # [CHANGE E2]
        # [CHANGE A4] hovering the editable overlay panel also drives the mask-panel marker
        # [CHANGE E1] renamed from on_mask_motion/on_mask_leave: canvas2 is the overlay now
        self.canvas2.bind("<Motion>", self.on_big_motion)
        self.canvas2.bind("<Leave>", self.on_big_leave)
        
        self.label1 = tk.Label(self.frame, text="Filtered Image")
        self.label1.grid(row=0, column=0, sticky="nsew")
        # [CHANGE E4] tk.Label -> tk.Canvas: a Label can only show a PhotoImage at its own
        # size, so it could not rescale when the cell changed. A Panel-managed Canvas can.
        self.canvas1 = tk.Canvas(self.frame, width=self.small_side, height=self.small_side,
                                 highlightthickness=0, bd=0)
        self.canvas1.grid(row=1, column=0, sticky="nsew")
        self.panel_filtered = Panel(self.canvas1, cap=self.source_side,
                                    resample=Image.Resampling.LANCZOS)
        self.canvas1.bind("<Configure>", lambda e: self._schedule_render('filtered'))
        
        self.label3 = tk.Label(self.frame, text="Original Image")
        self.label3.grid(row=2, column=0, sticky="nsew")
        self.canvas3 = tk.Canvas(self.frame, width=self.small_side, height=self.small_side,
                                 highlightthickness=0, bd=0)
        self.canvas3.grid(row=3, column=0, sticky="nsew")
        self.panel_original = Panel(self.canvas3, cap=self.source_side,
                                    resample=Image.Resampling.LANCZOS)
        self.canvas3.bind("<Configure>", lambda e: self._schedule_render('original'))
        
        # --------------------------------------------------------------------
        # [CHANGE A1] the overlay panel is now a tk.Canvas (it used to be a tk.Label,
        # which cannot host drawn items), so the mouse marker can be painted on top of it.
        # [CHANGE E1] *** THE SWAP - part 2 of 2: this bottom-left panel. ***
        # It used to show the green-on-image overlay; it now shows the live binary mask
        # ("Updating Mask"), i.e. exactly what the middle panel showed before the swap.
        # It stays read-only (a view, not an editing surface) but still mirrors the cursor.
        # --------------------------------------------------------------------
        self.label4 = tk.Label(self.frame, text="Updating Mask")
        self.label4.grid(row=4, column=0, sticky="nsew")
        self.canvas4 = tk.Canvas(self.frame,
                                 width=self.small_side,
                                 height=self.small_side,
                                 highlightthickness=0, bd=0)
        self.canvas4.grid(row=5, column=0, sticky="nsew")
        self.panel_mask = Panel(self.canvas4, cap=self.source_side)
        # [CHANGE A2/A4] panel reacts to resizing and to the mouse moving over it
        self.canvas4.bind("<Configure>", self.on_panel_resize)
        self.canvas4.bind("<Motion>", self.on_panel_motion)
        self.canvas4.bind("<Leave>", self.on_panel_leave)

        # [CHANGE B0] attribute-name fix: this block used to reuse self.label1 / self.canvas1,
        # silently overwriting the reference to the "Filtered Image" widgets.
        self.label_base = tk.Label(self.frame, text="Baseline mask (initial guess)")
        self.label_base.grid(row=0, column=span+1, sticky="nsew")
        self.canvas_base = tk.Canvas(self.frame, width=self.small_side, height=self.small_side,
                                     highlightthickness=0, bd=0)
        self.canvas_base.grid(row=1, column=span+1, sticky="nsew")
        self.panel_base = Panel(self.canvas_base, cap=self.source_side)
        self.canvas_base.bind("<Configure>", lambda e: self._schedule_render('base'))

        # [CHANGE E2] keep the two side columns in proportion to the window. Without this,
        # the side canvases keep the 340 px they asked for and a narrow window squeezes the
        # *editable* panel instead of the thumbnails. The requested size of the thumbnails is
        # only changed when the derived value really moves, so this cannot oscillate.
        self._last_small_request = self.small_side
        self._last_big_request = self.big_side   # [CHANGE H1] same idea for the middle panel
        self._window_sync_pending = False
        self.root.bind("<Configure>", self.on_window_resize)
        
        # Controls
        self.control_frame = tk.Frame(root)
        self.control_frame.pack(fill=tk.X)

        # ------------------------------------------------------------------
        # [CHANGE G3] bottom-right: the jump-to-image selector, so you can put the job down
        # and come back to a particular well later.
        #   * it is packed with side=RIGHT *before* the buttons, because pack hands out space
        #     in order: if the LEFT buttons (which use expand=True) were packed first they
        #     would take the whole row and this would have nowhere to go;
        #   * it is a combobox, not an OptionMenu, because a real plate run has >1000 images -
        #     typing "A1_7" beats scrolling a 1000-entry menu;
        #   * names that already have a mask in the export folder are marked "[saved]".
        # ------------------------------------------------------------------
        self.jump_frame = tk.Frame(self.control_frame)
        self.jump_frame.pack(side=tk.RIGHT, padx=6)
        self.jump_label = tk.Label(self.jump_frame, text="Jump to image:")
        self.jump_label.pack(side=tk.LEFT)
        self.jump_var = tk.StringVar()
        self.jump_box = ttk.Combobox(self.jump_frame, textvariable=self.jump_var,
                                     width=24, height=JUMP_LIST_HEIGHT)
        self.jump_box.pack(side=tk.LEFT, padx=2)
        self.btn_jump = tk.Button(self.jump_frame, text="Go", width=4, command=self.on_jump)
        self.btn_jump.pack(side=tk.LEFT)
        self.jump_status = tk.Label(self.jump_frame, text='', width=9, anchor='w')
        self.jump_status.pack(side=tk.LEFT, padx=(4, 0))
        self.jump_box.bind("<Return>", lambda e: self.on_jump())
        self.jump_box.bind("<<ComboboxSelected>>", lambda e: self.on_jump())
        self._refresh_jump_values()

        self.color = "black"
        self.brush_size = SMALL_BRUSH_SIZE   # [CHANGE H2] named constant, not a magic number

        # # Buttons at the bottom of the frame
        # [CHANGE D2] the letter in brackets is the shortcut for that button (see HOTKEYS),
        # and the button is drawn sunken while that mode is the active one ([CHANGE D3]).
        # [CHANGE H2] Black and White now pass SMALL_BRUSH_SIZE explicitly instead of
        # `brush_size=self.brush_size`. The old version re-used whatever size was current,
        # so after one click on "Large Black" (200 px) the small buttons kept painting with
        # the 200 px swatch. The size a button asks for is now fixed by the button, not by
        # the last tool you happened to pick.
        # large black fill
        self.btn_large_black = tk.Button(self.control_frame,
                                         text="Large Black" + hotkey_hint('large_black'),
                                         command=self.set_large_black)
        self.btn_large_black.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # black fill
        self.btn_black = tk.Button(self.control_frame, text="Black" + hotkey_hint('black'),
                                   command=lambda: self.set_color("black", brush_size=SMALL_BRUSH_SIZE))
        self.btn_black.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # white fill
        self.btn_white = tk.Button(self.control_frame, text="White" + hotkey_hint('white'),
                                   command=lambda: self.set_color("white", brush_size=SMALL_BRUSH_SIZE))
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

        # [CHANGE H1] the second sizing pass. It replaces the old after_idle(_render_all) +
        # hard-coded minsize pair: the window is fitted inside the Windows work area using
        # the *measured* height of the label rows and the button row, the minimum size comes
        # from those same measurements (so the window can no longer be dragged short enough
        # to hide the buttons), and every panel is painted once at the fitted size.
        self._fit_window()
        # [CHANGE H1] F11 runs the fit again - useful if the window has been dragged below
        # the work area, or moved to a monitor with a different size.
        self.root.bind("<F11>", self.refit_window)

    # ------------------------------------------------------------------
    # [CHANGE E2] window / panel sizing
    # ------------------------------------------------------------------
    def _work_area(self):
        """[CHANGE H1] The part of the screen that is *not* taken by the taskbar.
        Why: winfo_screenheight() is the whole screen, and the old code sized the window
        "screen height - 20" and put it 20 px from the top - so the bottom of the window
        (the button row) landed underneath the taskbar and could not be clicked until you
        dragged the window up. Windows publishes the usable rectangle through
        SystemParametersInfo(SPI_GETWORKAREA); ctypes is in the standard library, so this
        adds no dependency. The two APIs can disagree about pixels when Windows scales the
        display, so the work area is re-scaled by comparing the full-screen size Windows
        reports with the one Tk reports. On a non-Windows system, or if the call fails for
        any reason, we just fall back to the whole screen."""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if platform.system() != 'Windows':
            return 0, 0, sw, sh
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            rect = ctypes.wintypes.RECT()
            if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                raise OSError('SystemParametersInfo(SPI_GETWORKAREA) failed')
            full_w = user32.GetSystemMetrics(0) or sw      # SM_CXSCREEN
            full_h = user32.GetSystemMetrics(1) or sh      # SM_CYSCREEN
            fx, fy = sw / float(full_w), sh / float(full_h)
            left, top = int(rect.left * fx), int(rect.top * fy)
            right, bottom = int(round(rect.right * fx)), int(round(rect.bottom * fy))
            if right - left < 400 or bottom - top < 400:
                raise ValueError('work area does not make sense: %r'
                                 % ((left, top, right, bottom),))
            return left, top, right, bottom
        except Exception as exc:          # never let the sizing maths stop the program
            print('warning: no work area from Windows (%s) - using the whole screen' % exc)
            return 0, 0, sw, sh

    def _plan_layout(self):
        """[CHANGE H1] now plans from the *work area* (the screen minus the taskbar) instead
        of the whole screen, and leaves room for the window decorations (DECOR_H).
        [CHANGE E2] Choose a starting window size from the screen, and derive the two
        requested sizes the widgets ask the grid for:
          * big_side   - the editable overlay square in the middle
          * small_side - each of the four side squares (3 stacked on the left + baseline)
        The middle square takes all the vertical room the screen can give it, and each
        thumbnail gets about a third of that, which is what keeps the left column aligned
        with the middle panel. The grid weights (set in __init__) then do the same thing
        whenever the user resizes the window.
        [CHANGE H1] this is only the *first* pass: it runs before the widgets exist, so the
        height of the label rows and the button row has to be guessed (CHROME_H). The second
        pass, _fit_window(), measures them and re-plans once the real widgets are there."""
        wl, wt, wr, wb = self._work_area()
        screen_w, screen_h = wr - wl, wb - wt      # usable, not the whole screen
        big = min(screen_h - DECOR_H - EDGE - CHROME_H,
                  screen_w - 2 * EDGE - 2 * (MIN_SMALL_SIDE + 20))
        small = (big - 40) // 3
        if small < MIN_SMALL_SIDE:       # very short screen: keep the thumbnails usable
            small = MIN_SMALL_SIDE
            big = small * 3 + 40
        self.big_side = max(int(big), MIN_BIG_SIDE)
        self.small_side = max(int(small), MIN_SMALL_SIDE)
        win_w = min(self.big_side + 2 * self.small_side + 40, screen_w - 2 * EDGE)
        win_h = min(self.big_side + CHROME_H, screen_h - DECOR_H - EDGE)
        # [CHANGE H1] top-left of the *usable* area, not of the whole screen: "+20+20" used
        # to mean 20 px below the top of the monitor, which on a scaled display pushed the
        # bottom of the window off the bottom of the work area.
        self.root.geometry("%dx%d+%d+%d" % (win_w, win_h, wl + EDGE, wt))


    def _fit_window(self):
        """[CHANGE H1] The second sizing pass, run once every widget really exists.

        What it fixes: the buttons at the bottom were cut off (and needed the window to be
        dragged up) because the old code guessed the height of everything except the big
        image panel (CHROME_H = 170) and measured against the *whole* screen height, which
        includes the area under the taskbar. Both guesses are now replaced with facts:
          * the usable height comes from the Windows work area (_work_area);
          * the space the label rows and the button row need is *measured* from the widgets
            themselves, so it is right whatever the font size and the display scaling are;
          * the window height is then set to exactly what the content asks for, which means
            the content can never be taller than the window and nothing can be clipped;
          * finally the window's real on-screen position is checked and, if the bottom edge
            still ends up below the work area, height is handed back until it is not.
        The middle panel simply takes whatever room is left, so the button row is always
        visible and always clickable."""
        wl, wt, wr, wb = self._work_area()
        budget_h = (wb - wt) - DECOR_H - EDGE      # client height we are allowed to use
        budget_w = (wr - wl) - 2 * EDGE            # client width we are allowed to use
        thumbs = (self.canvas1, self.canvas3, self.canvas4, self.canvas_base)
        self.root.update_idletasks()               # make Tk compute the requested sizes
        label_h = max(w.winfo_reqheight() for w in
                      (self.label1, self.label2, self.label3, self.label4, self.label_base))
        # [CHANGE H1] remembered so the resize watcher (_desired_small) can keep the same
        # budget when the user resizes the window later.
        self._label_h = int(label_h)
        self._ctrl_h = int(self.control_frame.winfo_reqheight())

        # [CHANGE H1] MIN_SMALL_SIDE / MIN_BIG_SIDE are a preference, not a law. The one
        # thing that must never be cut off is the button row, so on a screen too small for
        # the preferred minimums the pictures shrink further instead (second round of the
        # loop below). The first round is the one that normally succeeds.
        for floor_small, floor_big in ((MIN_SMALL_SIDE, MIN_BIG_SIDE), (60, 120)):
            for _ in range(4):
                # Everything but the middle square, measured: the label rows + the button row.
                chrome_h = self.root.winfo_reqheight() - self.canvas2.winfo_reqheight()
                room_h = budget_h - chrome_h          # rows 1..5 of the grid
                # rows 1,3,5 are thumbnails and rows 2,4 are their labels, so the left column
                # is 3 * small + 2 * label_h tall: keep it the same height as the middle
                # square, which is what keeps the two columns lined up and stops the grid
                # growing the window past what the screen has.
                small_by_h = (room_h - 2 * label_h) // 3
                # width budget: big + 2 thumbnails + their gaps, with big = 3*small + 2 labels
                small_by_w = (budget_w - 2 * label_h - 40) // 5
                small = max(floor_small, min(small_by_h, small_by_w))
                big = min(room_h, small * 3 + 2 * label_h,
                          budget_w - 2 * small - 40,
                          int(self.source_side * MAX_UPSCALE))
                big = max(floor_big, int(big))
                if (big == self.canvas2.winfo_reqheight()
                        and small == self.canvas1.winfo_reqheight()):
                    break                          # already fitted, stop re-asking Tk
                self.big_side, self.small_side = big, small
                self.canvas2.configure(width=big, height=big)
                for cv in thumbs:
                    cv.configure(width=small, height=small)
                self._last_small_request = small   # [CHANGE E2] keep the resize watcher honest
                self._last_big_request = big
                self.root.update_idletasks()
            if (self.root.winfo_reqheight() <= budget_h
                    and self.root.winfo_reqwidth() <= budget_w):
                break

        # [CHANGE H1] never narrower than the button row itself, or the row would be squeezed
        # from the right; never wider or taller than the work area allows.
        min_w = min(budget_w, max(MIN_SMALL_SIDE * 2 + MIN_BIG_SIDE + 40,
                                  self.control_frame.winfo_reqwidth() + 20))
        win_w = max(min_w, min(self.root.winfo_reqwidth(), budget_w))
        win_h = min(self.root.winfo_reqheight(), budget_h)
        gx, gy = wl + EDGE, wt
        self.root.geometry("%dx%d+%d%+d" % (win_w, win_h, gx, gy))
        self.root.update_idletasks()

        for _ in range(3):
            # [CHANGE H1] the window manager has the last word about decorations, so check
            # where the bottom of the window *actually* landed. Pull it up first; only hand
            # back height as a last resort (that would clip, so it should not happen).
            over = (self.root.winfo_rooty() + self.root.winfo_height()) - wb
            if over <= 0:
                break
            shift = min(over, max(0, self.root.winfo_rooty() - wt))
            if shift > 0:
                gy -= shift
                self.root.geometry("%dx%d+%d%+d" % (win_w, win_h, gx, gy))
            else:
                win_h = max(120 + label_h + self.control_frame.winfo_reqheight(),
                            self.root.winfo_height() - over)
                self.root.geometry("%dx%d" % (win_w, win_h))
            self.root.update_idletasks()

        # [CHANGE H1] the minimum size comes from the same measurements. Horizontally the
        # window may shrink to the width of the button row - as narrow as it can be without
        # squeezing the row. Vertically it may shrink to the preferred minimum of the middle
        # panel plus the real label rows and button row; below that the pictures stop being
        # usable, and it is allowed at all because the window is never shorter than its own
        # content any more (see _desired_big), so no amount of shrinking hides the buttons.
        min_h = min(win_h, MIN_BIG_SIDE + self._label_h + self._ctrl_h + label_h)
        self.root.minsize(min_w, min_h)
        # [CHANGE H1] and a maximum size, so the window cannot be dragged (or maximised) past
        # the work area in the first place. Without it, a user pulling the bottom edge down
        # can push the button row back out of the screen; with it the window simply stops at
        # the edge of the usable area.
        self.root.maxsize(budget_w, budget_h)
        self._render_all()                         # [CHANGE E5] repaint at the fitted sizes

    def refit_window(self, event=None):
        """[CHANGE H1] F11: run the fit pass again. If the window has been dragged down so
        that the button row is out of reach, or it has been moved onto a smaller monitor,
        one key press puts it back without restarting the program."""
        self._fit_window()
        return "break"

    def _desired_small(self):
        """[CHANGE E2] How big the four side squares should be *requested* right now: never
        more than the value planned from the screen, and no more than about a quarter of the
        window width so the editable panel keeps the rest.
        [CHANGE H1] it must now also fit *vertically*. The left column is three thumbnails
        plus two labels tall, and on top of that sit the top label row and the button row.
        The old version only ever grew the thumbnails towards MIN_SMALL_SIDE, so after a fit
        pass had shrunk them, the very next <Configure> could grow them back and push the
        button row out of the window again - the clipping came straight back. Now the height
        of the window sets the limit as well as the width."""
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        if w <= 1 or h <= 1:
            return self.small_side
        label_h = getattr(self, '_label_h', 16)
        ctrl_h = getattr(self, '_ctrl_h', 24)
        by_width = int((w - 60) / 4)
        by_height = (h - 3 * label_h - ctrl_h) // 3        # 3 thumbs + 2 labels + label row + row
        small = min(self.small_side, by_width, by_height)
        # the preferred minimum gives way to the screen: a small thumbnail is better than a
        # button row you cannot reach
        floor = 60 if by_height < MIN_SMALL_SIDE else MIN_SMALL_SIDE
        return max(floor, int(small))

    def _desired_big(self):
        """[CHANGE H1] How big the middle square should be *requested* right now.
        The window's height minus the measured label rows and button row is the limit. That
        is what keeps the content from ever being taller than the window: the old code left
        the middle square at whatever size the first pass had picked, so when the window got
        shorter the extra height had nowhere to go and the button row was pushed out of the
        window instead. The width and MAX_UPSCALE limit it too - asking for a square bigger
        than the pixels in the file buys nothing."""
        h = self.root.winfo_height()
        w = self.root.winfo_width()
        if h <= 1 or w <= 1:
            return self.big_side
        chrome_h = self.root.winfo_reqheight() - self.canvas2.winfo_reqheight()
        chrome_w = self.root.winfo_reqwidth() - self.canvas2.winfo_reqwidth()
        big = min(h - chrome_h, w - chrome_w, int(self.source_side * MAX_UPSCALE))
        floor = 120 if h - chrome_h < MIN_BIG_SIDE else MIN_BIG_SIDE
        return max(floor, int(big))

    def on_window_resize(self, event):
        """[CHANGE E2] React to the window (not a panel) changing size, by re-requesting the
        thumbnail size. [CHANGE H1] the middle square is re-requested from the new height as
        well, so the content always fits the window and the button row is never pushed out.
        Queued with after_idle and skipped entirely when the derived size did not change, so
        dragging a window edge does not thrash the layout."""
        if event.widget is not self.root or self._window_sync_pending:
            return
        self._window_sync_pending = True

        def run():
            self._window_sync_pending = False
            small = self._desired_small()
            big = self._desired_big()          # [CHANGE H1] the middle square follows too
            if small == self._last_small_request and big == self._last_big_request:
                return
            self._last_small_request = small
            self._last_big_request = big
            self.big_side, self.small_side = big, small
            for cv in (self.canvas1, self.canvas3, self.canvas4, self.canvas_base):
                cv.configure(width=small, height=small)
            self.canvas2.configure(width=big, height=big)   # [CHANGE H1]
            self._schedule_render('thumbs')
            self._schedule_render('mask')
            self._schedule_render('big')
        self.root.after_idle(run)

    def _schedule_render(self, which):
        """[CHANGE E5] Ask for one re-render of a panel at the next idle moment. Dragging a
        window edge fires <Configure> hundreds of times; this coalesces them into one
        re-render per idle cycle instead of re-blending a 1000x1000 image every time."""
        if which in self._pending_render:
            return
        self._pending_render.add(which)

        def run():
            self._pending_render.discard(which)
            if which == 'big':
                self._render_big()
            elif which == 'mask':
                self._render_mask_panel()
            elif which == 'filtered':
                self.panel_filtered.show(self.mod_full)
            elif which == 'original':
                self.panel_original.show(self.unmod_full)
            elif which == 'base':
                self.panel_base.show(self.base_full)
            elif which == 'thumbs':
                self._render_thumbs()
            self.draw_cursor()
        self.root.after_idle(run)

    def _render_thumbs(self):
        """[CHANGE E4] The three static-ish panels: Filtered Image, Original Image and the
        baseline mask. They only change when the window is resized."""
        self.panel_filtered.show(self.mod_full)
        self.panel_original.show(self.unmod_full)
        self.panel_base.show(self.base_full)

    def _render_all(self):
        """[CHANGE E5] Draw every panel in the window. Used once, after the widgets map."""
        self._render_big()
        self._render_mask_panel()
        self._render_thumbs()
        self.draw_cursor()

    # ------------------------------------------------------------------
    # [CHANGE E1/E7] the two live panels
    # ------------------------------------------------------------------
    def _scaled_source(self, size):
        """[CHANGE E7] Base image for the editable panel (see OVERLAY_BASE), scaled to the
        panel and cached, because it never changes while you paint."""
        if self._src_cache is not None and self._src_cache[0] == size:
            return self._src_cache[1]
        base = self.mod_full if OVERLAY_BASE == "mod" else self.unmod_full
        arr = np.asarray(base.resize(size, resample=Image.Resampling.LANCZOS)).copy()
        self._src_cache = (size, arr)
        return arr

    @staticmethod
    def _blend(src, mask_np):
        """Green wash of the mask over the base image (this is the old create_overlay maths)."""
        out = src.copy()
        m = mask_np > 0
        if m.any():
            out[m] = (1 - OVERLAY_ALPHA) * src[m] + OVERLAY_ALPHA * np.array(OVERLAY_COLOR, dtype=np.uint8)
        return out

    def _render_big(self):
        """[CHANGE E1] Redraw the middle panel from scratch: base image + the live mask in
        green. Called on start-up, after a resize, on Reset / Isolate, and at the end of
        every brush stroke (see on_stroke_end)."""
        p = self.panel_big
        if p.fit() == 0:                 # not mapped yet, <Configure> will call us again
            return
        size = (p.side, p.side)
        self.disp_src = self._scaled_source(size)
        # the mask is authoritative at its own working resolution; sample it at display size.
        # [CHANGE E7] np.array(..., copy=True) on purpose: an array taken straight from a PIL
        # image is read-only, and _blend_box() writes patches into this buffer while painting.
        self.disp_mask = np.array(self.mask.resize(size, resample=Image.Resampling.NEAREST),
                                  dtype=np.uint8, copy=True)
        self.disp_img = self._blend(self.disp_src, self.disp_mask)
        self.overlay_image = Image.fromarray(self.disp_img)
        p.show(self.overlay_image, already_sized=True)
        self.draw_cursor()

    def _render_mask_panel(self):
        """[CHANGE E1] Redraw the bottom-left panel: the live binary mask. This used to be
        what the middle panel showed."""
        self.panel_mask.show(self.mask)

    def _refresh_mask_views(self):
        """[CHANGE E5] Both live panels after a non-stroke change (Isolate / Reset / load)."""
        self._render_big()               # [CHANGE B2] replaces _show_mask()
        self._render_mask_panel()

    def _blend_box(self, cl, ct, cr, cb):
        """[CHANGE E7] Fast path for brush strokes: re-blend only the rectangle the brush
        just touched and copy that part of the authoritative mask into the display copy.
        A full 1000x1000 blend measures ~30 ms, which is far too slow to do on every
        <B1-Motion>; this costs a fraction of a millisecond.

        [CHANGE F3] The arguments are **canvas** coordinates (what a mouse event carries).
        The display buffers and Tk's photo work in **photo** coordinates, whose origin is the
        top-left of the displayed image, i.e. canvas (offx, offy). The two were conflated
        here, so whenever the panel was letterboxed (a non-square cell, which is the normal
        case) every mid-stroke patch landed one letterbox margin away from the brush: with the
        small brush nothing appeared at all, and with a big brush only part of it did.
        The closing full rebuild at ButtonRelease hid this, which is why it looked like the
        overlay only updated when the drag finished.
        """
        p = self.panel_big
        s = p.side
        if s <= 0 or self.disp_img is None or self.disp_src is None or self.disp_mask is None:
            return
        # canvas -> photo
        l = cl - p.offx
        t = ct - p.offy
        r = cr - p.offx
        b = cb - p.offy
        l = max(0, min(s, int(l))); t = max(0, min(s, int(t)))
        r = max(0, min(s, int(r))); b = max(0, min(s, int(b)))
        if r <= l or b <= t:
            return
        # map the display rectangle back to the working mask and re-sample just that patch
        f = float(self.mask.size[0]) / s
        ml = max(0, int(l * f)); mt = max(0, int(t * f))
        mr = min(self.mask.size[0], int(r * f) + 1); mb = min(self.mask.size[1], int(b * f) + 1)
        if mr <= ml or mb <= mt:
            return
        patch = np.asarray(self.mask.crop((ml, mt, mr, mb)).resize((r - l, b - t),
                                                                  resample=Image.Resampling.NEAREST),
                           dtype=np.uint8)
        self.disp_mask[t:b, l:r] = patch
        self.disp_img[t:b, l:r] = self._blend(self.disp_src[t:b, l:r], self.disp_mask[t:b, l:r])
        # [CHANGE F1] hand Tk only this rectangle (a Tk-side photo copy), not the whole image.
        region = Image.fromarray(np.ascontiguousarray(self.disp_img[t:b, l:r]))
        if not p.put_region(region, l, t):
            p.refresh(self.disp_img)         # fallback: something is better than nothing

    def isolate_large_blob(self):

        temp_mask_np = (np.asarray(self.mask)/255).astype(np.uint8)
        temp_mask_torch = leave_only_largest_blob(temp_mask_np, device=device, num_iterations = 500)
        temp_mask_np = temp_mask_torch.cpu().numpy().astype(np.uint8)*255

        self.mask = Image.fromarray(temp_mask_np)

        self._dirty = True              # [CHANGE C2] this is an edit too
        self._refresh_mask_views()      # [CHANGE E5] overlay + updating mask, both live

        print('TEST')
    
    # ------------------------------------------------------------------
    # [CHANGE D1] keyboard shortcuts. Each one calls exactly the same method as its button,
    # so the guard for unsaved edits and the refresh of the overlay panel still happen.
    # ------------------------------------------------------------------
    def _typing(self):
        """[CHANGE G4] True when the keyboard focus is in a text entry (the jump box).
        The single-letter shortcuts are bound on the whole window, so without this guard
        typing "d" or "a" into the jump selector would also page to another image, and the
        arrow keys would move the caret and change image at the same time."""
        w = self.root.focus_get()
        if w is getattr(self, 'jump_box', None):
            return True
        if isinstance(w, (tk.Entry, ttk.Entry, tk.Text)):
            return True
        # ttk keeps the editable part of a combobox in an internal entry that tkinter may
        # not hand back as a Python widget, so ask Tcl what class actually has the focus.
        try:
            shown = self.root.tk.call('winfo', 'class', self.root.focus_displayof())
        except (tk.TclError, RuntimeError):
            return False
        if isinstance(shown, bytes):
            shown = shown.decode()
        return shown in ('Entry', 'Text', 'Combobox')

    def make_hotkey(self, action):
        """Build the callback for one shortcut (or arrow key)."""
        def on_key(event):
            # [CHANGE G4] typing in the jump selector is not a shortcut
            if self._typing():
                return None
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
            # [CHANGE H2] the small brush, whatever size was in use before
            self.set_color("black", brush_size=SMALL_BRUSH_SIZE)
        elif action == 'white':
            self.set_color("white", brush_size=SMALL_BRUSH_SIZE)
        elif action == 'large_black':
            # [CHANGE H3] 'g' now does exactly what the Large Black button does
            self.set_large_black()
        elif action == 'reset':
            self.reset_image()

    def _sync_tool_buttons(self):
        """[CHANGE D3] Sink the button of the brush mode you are in, so you can see the
        active tool without looking for it after using the keyboard."""
        if not hasattr(self, 'btn_black'):
            return
        if self.color == "black" and self.brush_size >= LARGE_BRUSH_SIZE:
            active = self.btn_large_black
        elif self.color == "black":
            active = self.btn_black
        else:
            active = self.btn_white
        for btn in (self.btn_large_black, self.btn_black, self.btn_white):
            btn.config(relief=tk.SUNKEN if btn is active else tk.RAISED)

    def set_large_black(self, event=None):
        """[CHANGE H3] usable as a callback and as a shortcut target; [CHANGE H2] the size
        comes from LARGE_BRUSH_SIZE. Same as clicking "Large Black": black, big swatch."""
        self.set_color("black", brush_size=LARGE_BRUSH_SIZE)

    def set_color(self, color, brush_size=None):
        """Set drawing color.
        [CHANGE H2] `brush_size` is now always given by the caller (small buttons pass
        SMALL_BRUSH_SIZE, Large Black passes LARGE_BRUSH_SIZE). When it is left out the
        brush falls back to SMALL_BRUSH_SIZE - the old default of 10 was a leftover that
        made the size depend on who forgot to pass it."""
        self.color = color
        self.brush_size = SMALL_BRUSH_SIZE if brush_size is None else int(brush_size)
        self.draw_cursor()     # [CHANGE A4] reflect the new brush size straight away
        self._sync_tool_buttons()  # [CHANGE D3]

    def create_overlay(self, size=None):
        """[CHANGE E7] Kept as a thin wrapper over the new blend helpers so anything outside
        this file that still calls it keeps working. The editable panel itself uses
        _render_big() / _blend_box(), because those can redraw just the part of the image a
        brush stroke touched (a full rebuild at panel size measures ~30 ms).
        [CHANGE A2] `size` renders the overlay at the panel's real pixel size."""
        if size is None:
            side = self.panel_big.side or self.source_side
            size = (side, side)
        size = tuple(size)
        mask_np = np.asarray(self.mask.resize(size, resample=Image.Resampling.NEAREST))
        return Image.fromarray(self._blend(self._scaled_source(size), mask_np))
    
    # ------------------------------------------------------------------
    # [CHANGE E7] painting on the editable OVERLAY panel (the middle one, after the swap).
    # A click arrives in *display* pixels, which are no longer 1:1 with the mask's working
    # pixels because the panel now resizes with the window, so every coordinate goes through
    # _big_to_mask() first. While a stroke is in progress only the square the brush touched
    # is re-blended; the exact full re-render happens on button release.
    # ------------------------------------------------------------------
    def paint(self, event):

        """Allow drawing on the mask by adding (white) or removing (black) parts."""
        pos = self._big_to_mask(event.x, event.y)
        if pos is None:                 # click landed in the margin around the displayed image
            return
        mx, my = pos
        draw = ImageDraw.Draw(self.mask)
        color = 255 if self.color == "white" else 0
        r = self.brush_size // 2
        draw.ellipse((mx - r, my - r, mx + r, my + r), fill=color)
        
        self._dirty = True              # [CHANGE C2] remember that there is unsaved work
        self._stroke_open = True
        # [CHANGE E1] the bottom-left "Updating Mask" panel follows every dab
        self._render_mask_panel()

        # [CHANGE E1] and so does the editable overlay, dab by dab, in the cheap way
        self._cursor = (mx, my)         # [CHANGE A4]
        self._cursor_from_panel = False
        p = self.panel_big
        f = p.side / float(self.mask.size[0])
        dx, dy = p.offx + mx * f, p.offy + my * f
        dr = max(1, int(r * f)) + 2
        self._blend_box(dx - dr, dy - dr, dx + dr, dy + dr)   # [CHANGE E7]
        self.preview_brush(event)
        self.draw_cursor()

    def on_stroke_end(self, event):
        """[CHANGE E7] The button came up: rebuild the overlay exactly from the mask, so
        what is on screen is pixel-for-pixel what the mask really holds."""
        self._stroke_open = False
        self._render_big()
        self._render_mask_panel()
    
    def preview_brush(self, event):
        """Show a preview of the brush size (colour kept in sync with the panel marker).
        [CHANGE E7] the radius is scaled by the panel now that panel px != mask px."""
        self.canvas2.delete("brush_preview")
        r = self._big_brush_radius()
        if r <= 0:
            return
        self.canvas2.create_oval(event.x - r, event.y - r, event.x + r, event.y + r,
                                 outline=BRUSH_PREVIEW_COLOR, tags="brush_preview")

    # ------------------------------------------------------------------
    # [CHANGE A4] mouse tracking. The marker is made of canvas items only, so moving the
    # mouse never rebuilds an image: it is cheap and follows the pointer immediately.
    # [CHANGE E7] the conversions now go through the Panel objects and use normalised 0..1
    # coordinates, because after the swap BOTH live panels can be any size the window is.
    # ------------------------------------------------------------------
    def _big_to_mask(self, x, y):
        """Editable-overlay panel px -> working-mask px.
        Returns None when the pointer is in the letterbox margin next to the image."""
        n = self.panel_big.to_norm(x, y)
        if n is None or not (0.0 <= n[0] < 1.0 and 0.0 <= n[1] < 1.0):
            return None
        return (n[0] * self.mask.size[0], n[1] * self.mask.size[1])

    def _mask_to_big(self, mx, my):
        """working-mask px -> editable-overlay panel px."""
        return self.panel_big.from_norm(mx / float(self.mask.size[0]), my / float(self.mask.size[1]))

    def _mask_to_panel(self, mx, my):
        """[CHANGE E1] working-mask px -> bottom-left Updating Mask panel px."""
        p = self.panel_mask
        return p.from_norm(mx / float(self.mask.size[0]), my / float(self.mask.size[1]))

    def _panel_to_mask(self, x, y):
        """[CHANGE E1] bottom-left Updating Mask panel px -> working-mask px."""
        p = self.panel_mask
        if p.side <= 0:
            return (None, None)
        n = p.to_norm(x, y)
        return (n[0] * self.mask.size[0], n[1] * self.mask.size[1])

    def _big_brush_radius(self):
        """[CHANGE E7] the brush footprint radius in display px on the editable panel."""
        if self.panel_big.side <= 0:
            return 0
        return max(CURSOR_MIN_RADIUS,
                   self.brush_size * 0.5 * self.panel_big.side / float(self.mask.size[0]))

    def draw_cursor(self):
        """[CHANGE E1] Mirror of the old behaviour, with the two panels swapped round:
        the pointer marker (circle + crosshair) is now drawn on the bottom-left *Updating
        Mask* panel, and the mirrored crosshair appears on the editable overlay when the
        pointer is sitting on that mask panel."""
        if not hasattr(self, 'canvas4'):
            return
        self.canvas4.delete("cursor")
        self.canvas2.delete("mirror_cursor")
        if self._cursor is None:
            return
        mx, my = self._cursor
        # ---- marker on the bottom-left Updating Mask panel ----
        p = self.panel_mask
        if p.side > 0:
            px, py = self._mask_to_panel(mx, my)
            f = p.side / float(self.mask.size[0])
            r = max(CURSOR_MIN_RADIUS, self.brush_size * 0.5 * f)
            self.canvas4.create_oval(px - r, py - r, px + r, py + r,
                                     outline=BRUSH_PREVIEW_COLOR, tags="cursor")
            x0, y0 = p.offx, p.offy
            x1, y1 = p.offx + p.side, p.offy + p.side
            self.canvas4.create_line(x0, py, x1, py, width=CURSOR_LINE_WIDTH,
                                     fill=CURSOR_CROSS_COLOR, tags="cursor")
            self.canvas4.create_line(px, y0, px, y1, width=CURSOR_LINE_WIDTH,
                                     fill=CURSOR_CROSS_COLOR, tags="cursor")
        # ---- mirrored crosshair on the editable overlay panel ----
        b = self.panel_big
        if b.side > 0 and self._cursor_from_panel:
            bx, by = self._mask_to_big(mx, my)
            self.canvas2.create_line(b.offx, by, b.offx + b.side, by,
                                     width=CURSOR_LINE_WIDTH, fill=CURSOR_CROSS_COLOR,
                                     tags="mirror_cursor")
            self.canvas2.create_line(bx, b.offy, bx, b.offy + b.side,
                                     width=CURSOR_LINE_WIDTH, fill=CURSOR_CROSS_COLOR,
                                     tags="mirror_cursor")
            rb = self._big_brush_radius()
            self.canvas2.create_oval(bx - rb, by - rb, bx + rb, by + rb,
                                     outline=CURSOR_CROSS_COLOR, tags="mirror_cursor")

    def on_big_motion(self, event):
        """Pointer moved over the editable overlay: keep the red brush circle there and
        push the same position onto the Updating Mask panel."""
        self._cursor = self._big_to_mask(event.x, event.y)
        self._cursor_from_panel = False
        self.preview_brush(event)
        self.draw_cursor()

    def on_big_leave(self, event):
        self._cursor = None
        self.canvas2.delete("brush_preview")
        self.canvas2.delete("mirror_cursor")
        self.canvas4.delete("cursor")

    def on_panel_motion(self, event):
        """[CHANGE E1] Pointer moved over the Updating Mask panel: show where that lands on
        the editable overlay panel. This panel is a view, not an editing surface."""
        mx, my = self._panel_to_mask(event.x, event.y)
        if mx is not None and 0 <= mx < self.mask.size[0] and 0 <= my < self.mask.size[1]:
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
        """[CHANGE A2/E1] The Updating Mask panel changed size, so redraw it at the new size
        and recompute the coordinate mapping."""
        self._schedule_render('mask')

    def on_big_resize(self, event):
        """[CHANGE E2] The editable panel changed size with the window: re-fit and re-render
        the overlay (and, with it, the coordinate mapping used by the brush)."""
        self._schedule_render('big')

    def reset_image(self):
        """Reload and reset path2 image."""
        # [CHANGE C5] use this image's own path (the old code read the global `path2`, which
        # only worked by accident) and resize with NEAREST, exactly like the initial load.
        self.mask = Image.open(self.path2).convert("L").resize(self.mask_size, resample=Image.Resampling.NEAREST)
        self._dirty = False                 # [CHANGE C2]
        self._refresh_mask_views()          # [CHANGE E5] both live panels, in place of
                                            # _show_mask() + _render_overlay()
    
    def save_image(self):
        """Save the edited mask as path2_edit.png."""
        path2_edit = os.path.join(self.export_path,self.export_name + '.png')
        self.mask.save(path2_edit)
        self._dirty = False                 # [CHANGE C2] the work is on disk now
        self._refresh_jump_values()         # [CHANGE G3] so it now shows as [saved]
        print(f"Mask saved as {path2_edit}")

    # ------------------------------------------------------------------
    # [CHANGE G3] the jump-to-image selector (bottom right).
    # ------------------------------------------------------------------
    def jump_display_name(self, name):
        """[CHANGE G3] The files come in triplets (A1_123_img / _mod / _mask), so the selector
        shows the shared part - A1_123 - while the internal key stays the full mask-file stem,
        which is also the name the exported mask is saved under."""
        return name[:-5] if name.endswith('_mask') else name

    def _refresh_jump_values(self):
        """Fill the drop-down with every image name, marking the ones that already have a
        saved mask, and put the current image in the box."""
        if not hasattr(self, 'jump_box'):
            return
        done = saved_names(self.export_path)
        self.jump_box['values'] = [self.jump_display_name(n) + ('  [saved]' if n in done else '')
                                   for n in self.image_names]
        if 0 <= self.i < len(self.image_names):
            self.jump_var.set(self.jump_display_name(self.image_names[self.i]))

    def _jump_status(self, text):
        """Short note next to the box - quieter than a dialog for a typing slip."""
        if hasattr(self, 'jump_status'):
            self.jump_status.config(text=text)

    def _resolve_jump(self, text):
        """Turn what the user typed or picked into an index into self.image_names.
        Accepts, in this order:
          * an exact name                    A1_123  (or A1_123_mask)
          * a name carrying the marker       A1_123  [saved]
          * a number, 1-based like the title bar ("Image 444 of 1120"), or with a # 448, #448
          * a unique fragment of a name      1_12  -> A1_123
        Returns None (and says why in the status label) when it is ambiguous or unknown."""
        t = (text or '').strip()
        if not t:
            return None
        t = t.split('  [saved]')[0].strip()
        names = self.image_names
        if t in names:
            self._jump_status('')
            return names.index(t)
        exact = [k for k, nm in enumerate(names) if self.jump_display_name(nm) == t]
        if len(exact) == 1:
            self._jump_status('')
            return exact[0]
        digits = t[1:] if t.startswith('#') else (t if t.isdigit() else None)
        if digits is not None and digits.isdigit():
            n = int(digits)
            if 1 <= n <= len(names):
                self._jump_status('')
                return n - 1                 # 1-based, to match the window title
            self._jump_status('no. %d?' % n)
            return None
        hits = [k for k, nm in enumerate(names) if t.lower() in self.jump_display_name(nm).lower()]
        if len(hits) == 1:
            self._jump_status('')
            return hits[0]
        if len(hits) > 1:
            shown = ', '.join(self.jump_display_name(names[k]) for k in hits[:3])
            self._jump_status('several')
            print('jump: "%s" matches %d images (%s...) - be more specific'
                  % (t, len(hits), shown))
            return None
        self._jump_status('not found')
        return None

    def on_jump(self):
        """Jump straight to the chosen image. Goes through the same unsaved-edits guard as
        Prev/Next, and the run loop picks up the requested index."""
        k = self._resolve_jump(self.jump_var.get())
        if k is None:
            return
        if k == self.i:
            self._jump_status('current')
            return
        self.goto_index = k
        # [CHANGE G5] if the unsaved-edits prompt was cancelled, undo the request as well
        if not self._leave('goto'):
            self.goto_index = None
    
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
        """Close the window for the run loop, unless the user backs out of unsaved edits.
        [CHANGE G5] Returns whether it actually left, so a cancelled jump can undo whatever
        state it had prepared rather than leaving a half-made request behind."""
        if not self._confirm_leave():
            return False
        self.action = action
        self.root.destroy()
        return True

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
def main(path_to_images=path_to_images,
         output_path=output_path,
         start_index=None,
         state_path=STATE_FILENAME):
    # [CHANGE G2] start_index=None now means "wherever you left off": the remembered image for
    # this folder, or failing that the first image that has no saved mask yet. Pass a number to
    # override that.

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
    # [CHANGE G3] the names the jump selector offers
    names = image_names_from(images)
    if not images:
        print('no _img / _mask / _mod image triplets found in %s' % path_to_images)
        return 0
    # [CHANGE G2] where to start - and say it out loud, so resuming is never a mystery
    i = resolve_start_index(names, output_path, path_to_images, state_path, start_index)
    done = saved_names(output_path)
    print('folder %s: %d images, %d already saved; starting at image %d of %d (%s)'
          % (path_to_images, len(images), len([n for n in names if n in done]),
             i + 1, len(images), names[i]))
    # [CHANGE C3] masks edited during this run, kept in memory per index so going back and
    # forth does not throw away work that has not been saved yet.
    edited_masks = {}

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
                          restored_mask=edited_masks.get(i), image_names=names)
        root.mainloop()

        # [CHANGE C1/C3] remember the state of the image we are leaving and where the user
        # wanted to go. Closing the window without pressing a button behaves like Next.
        edited_masks[i] = app.mask
        action = app.action if app.action in ('next', 'prev', 'goto') else 'next'
        if app.action == 'quit':
            print('Quit requested')
            save_state(path_to_images, names[i], state_path)    # [CHANGE G2] resume here
            return i
        # [CHANGE G3] a jump goes to the index the selector asked for
        if action == 'goto' and app.goto_index is not None and 0 <= int(app.goto_index) < len(images):
            i = int(app.goto_index)
        else:
            i += -1 if action == 'prev' else 1

        # [CHANGE G2] remember where we are, every time we move
        if 0 <= i < len(images):
            save_state(path_to_images, names[i], state_path)

        print('end loop')

    print('EOF')
    # [CHANGE C8] report where the run ended (useful for the harness and for resuming later)
    return i


if __name__ == "__main__":
    main()
