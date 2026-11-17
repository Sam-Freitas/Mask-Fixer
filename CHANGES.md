# Mask_fixer — change log

Everything in this file is a change I made, with **what** changed, **why**, and **how** it is
implemented in `Mask_fixer_app.py`. Every code change also carries the matching
`[CHANGE Ex]` tag at the exact place in the file where it was made, so the comment and this
document always say the same thing.

Older work in the file is tagged `[CHANGE A…]` (cursor overlay), `[CHANGE B…]` (render
hygiene), `[CHANGE C…]` (navigation / unsaved-edits guard), `[CHANGE D…]` (keyboard shortcuts),
`[CHANGE E…]`/`[CHANGE F…]` (the panel swap, responsive sizing, painting speed) and
`[CHANGE G…]` (jump selector, resume). The newest round is `[CHANGE H1]`–`[CHANGE H3]` at the
bottom of this file: the window is fitted to the screen so the button row is never cut off, a
`G` shortcut for Large Black, and the fix for Large Black not going back to the small brush.

---

## The objective

Swap the two live panels:

| Slot | Before | After |
|---|---|---|
| middle (large) | the bare editable binary mask | **the image with the mask painted on it in green — and you still edit here** |
| bottom-left | the green-on-image overlay | **the live binary mask (the "updating mask")** |
| top-left | Filtered Image | unchanged |
| mid-left | Original Image | unchanged |
| top-right | Baseline mask (initial guess) | unchanged |

plus: make both panels responsive and properly sized for the window.

---

## [CHANGE E1] The swap itself

**What.** The middle canvas (`canvas2`) now displays the base image with the current mask
blended over it in green; the bottom-left canvas (`canvas4`) displays the raw black/white
mask, and it refreshes on every brush dab. Labels renamed to
`Editable Overlay (mask shown in green)` and `Updating Mask`.

**Why.** That is the requested swap: the user paints on a picture of the worm, not on an
abstract black-and-white square, and the small panel keeps showing the mask as it is being
built.

**How.**
* `create_overlay()` used to be the only blend routine, and it was pointed at the *small*
  panel. Its maths (green colour, `alpha = 0.4`) was lifted out into two named pieces:
  `OVERLAY_COLOR`, `OVERLAY_ALPHA`, `OVERLAY_BASE` (module constants at the top) and the
  helpers `_scaled_source()` and `_blend()`.
* `_render_big()` draws the middle panel; `_render_mask_panel()` draws the bottom-left one.
  `_refresh_mask_views()` calls both after a non-stroke edit (Isolate Largest / Reset).
* `create_overlay(size=None)` is kept as a thin wrapper over the new helpers so any outside
  call still works.
* Painting still happens only on the middle canvas (same bindings as before); the bottom-left
  panel is a live *view*. Mouse-over on it still mirrors a crosshair onto the middle panel,
  exactly as the old bottom-left panel did — the roles just changed places.
* The green is blended over the **Original** image (`OVERLAY_BASE = "unmod"`), which is what
  the old overlay did. The old code had a comment saying it "should really be" the *filtered*
  image; set `OVERLAY_BASE = "mod"` at the top of the file to flip it — one line, no other
  change needed.

## [CHANGE E2] Responsive sizing

**What.** The window is sized from the screen; every one of the five image slots re-renders
itself to fit the cell the window gives it. Nothing is clipped and nothing stays at a stale
fixed size when you resize.

**Why.** The old layout hard-coded `s = 290` thumbnails and `s * 3.25 = 942` for the editable
mask, and the grid had no stretch factors, so resizing the window did nothing useful: the
`tk.Label` panels were frozen at 290 px and the mask was frozen at 942 px.

**How.**
* New module constants: `MIN_BIG_SIDE`, `MIN_SMALL_SIDE`, `MAX_UPSCALE`, `SCREEN_MARGIN`,
  `CHROME_H`, `MASK_NATIVE_SIDE`.
* `_plan_layout()` reads `winfo_screenwidth/height` and works out `big_side` (the middle
  square) and `small_side` (each side square, about a third of the middle one so the left
  column lines up with it), then sets the window geometry from those.
* `grid_columnconfigure` / `grid_rowconfigure` weights: the middle columns and the three
  image rows carry all the slack, so the editable panel grows first.
* `root.minsize(...)` stops the window being shrunk past usable size.
* `on_window_resize` + `_desired_small()` also re-request the *thumbnail* size when the
  window gets narrow, so the side columns give up width too instead of squeezing the middle
  panel. It only re-layouts when that derived value actually changes, and it is queued with
  `after_idle`, so dragging a window edge cannot thrash the layout or oscillate.
* Measured on this machine (screen 2333×1312): default window 1782×1232, middle panel 1102 px,
  side panels 340 px. Shrunk to 1100×760 the middle panel became 580 px and the thumbs 232–260
  px; grown to 2000×1200 the middle became 1153 px (its cap is `512 × MAX_UPSCALE = 1536`).

## [CHANGE E3] One `Panel` helper class

**What.** A small class (`Panel`) that owns one canvas and always shows an image fitted —
square, centred — inside whatever size that canvas currently is. All five slots use one.

**Why.** Five panels × (resize, centre, scale, keep the PhotoImage alive, map coordinates)
is the same job five times over. Putting it in one place is what makes the responsiveness
possible without repeating (and drifting) the code.

**How.** `Panel.fit()` computes the biggest square that fits the canvas (respecting `cap`),
`Panel.show(img)` resizes/re-displays it, `Panel.refresh(arr)` pushes a numpy buffer into the
existing PhotoImage, and `to_norm`/`from_norm` convert canvas pixels to a normalised 0…1
position. The per-panel geometry fields the old code carried on `ImageEditor`
(`_ov_side`, `_ov_offx`, `_ov_offy`, `_overlay_item`) are gone — they live on the `Panel`.
`Panel.show()` reuses the existing PhotoImage with `paste()` when the size has not changed,
which is also why a stroke no longer allocates a new image per dab.

## [CHANGE E4] Widgets and loading

**What.** `canvas1` (Filtered Image) and `canvas3` (Original Image) became `tk.Canvas`
instead of `tk.Label`; the pre-made thumbnails and PhotoImages (`mod_img`, `unmod_img`,
`small_mask_img`, `tk_img1/2/3`, `small_mask`) were deleted; `base_full` was added. The
middle label now spans the whole middle grid column.

**Why.** A `tk.Label` cannot host drawn items and cannot scale its picture, so it could not
be responsive. The pre-scaled thumbnails were the other half of the fixed-size problem — the
panels were built around a size chosen at load time. `label2` sitting in one grid column
would have been squashed as soon as the middle column grew.

**How.** Everything now keeps the full-resolution source (`mod_full`, `unmod_full`,
`base_full`, `mask_img`) and each `Panel` scales on demand at draw time (photos use LANCZOS,
masks use NEAREST so their edges stay crisp). The legacy names `image_size_small` /
`image_size_large` are still set (aliases) in case anything of yours reads them, but the
layout no longer uses them.

## [CHANGE E5] Render scheduling

**What.** `_render_all()`, `_schedule_render(name)` and `_pending_render`.

**Why.** `<Configure>` fires hundreds of times while a window edge is dragged, and a full
blend at 1100 px measures ~30 ms — that would freeze the UI during a resize. Also, the panels
have no real size until Tk maps them, so the first render cannot happen inside `__init__`.

**How.** Each resize handler asks for one re-render at the next idle moment, coalesced by a
`_pending_render` set. The first paint of every panel is queued with `after_idle`.

## [CHANGE E6] Bottom-left = "Updating Mask"

**What.** `self.label4` text changed from `Overlay Image` to `Updating Mask`, and `canvas4`
is driven by `_render_mask_panel()`, which shows `self.mask`.

**Why.** Naming: after the swap, the old label would have been wrong.

## [CHANGE E7] Painting on a panel that is no longer 1:1

**What.** `paint()` now converts the click position to mask coordinates before drawing, and
during a stroke only the rectangle the brush touched is re-blended. `on_stroke_end()` does an
exact full rebuild when the button is released. New helpers: `_big_to_mask`, `_mask_to_big`,
`_mask_to_panel`, `_panel_to_mask`, `_big_brush_radius`, `_blend_box`, `on_stroke_end`.
`on_mask_motion`/`on_mask_leave` were renamed `on_big_motion`/`on_big_leave` (canvas2 is the
overlay now).

**Why.** This is the part the swap really needed: the mask is kept at a fixed *working*
resolution (`MASK_NATIVE_SIDE = 942`, exactly the old `290 × 3.25`) while the panel showing it
can now be any size the window happens to be. Without the conversion the brush would land in
the wrong place as soon as the window was resized, and the brush preview circle would be the
wrong size.

**How.**
* Coordinates travel as normalised 0…1 values through `Panel`, then get multiplied by
  `mask.size` — so display pixels, mask pixels and source pixels never get mixed up. Clicks
  in the letterbox margin beside the image are ignored instead of painting at the edge.
* The brush keeps its meaning in **mask pixels** (25, 200 = "Large Black" are unchanged);
  only its on-screen circle is scaled.
* Speed: three buffers sit behind the middle panel at display resolution — `disp_src` (base
  image, cached per size), `disp_mask` (mask sampled at display size), `disp_img` (what is on
  screen). `_blend_box()` re-samples just the touched patch of the authoritative mask,
  re-blends just that rectangle and pastes the result into the existing PhotoImage. Measured:
  **~10 ms per dab** with a 1102 px panel (a full rebuild is ~30 ms), so dragging stays smooth.
* Correctness is not traded away: the authoritative mask is always updated exactly, and
  `on_stroke_end()` rebuilds the display from it, verified in the harness by comparing the
  display buffer to a clean rebuild (`np.array_equal` → identical).

## [CHANGE E8] Test harness

**What.** `_dev/smoke_layout.py` (development only, not imported by the app).

**Why.** To prove the swap and the responsiveness instead of asserting it.

**How.** It opens the real editor window and runs 55 checks:
* geometry of all five panels, that each fits its cell, and that the button row is not
  clipped;
* what each panel **actually displays**, by reading the Tk image back through its Tcl name
  (`image get`) — middle: has green + a visible image; bottom-left: green = 0.0000, black and
  white only; top-right: still the untouched baseline;
* painting: the dab lands at the right mask pixel, both live panels change, the unsaved flag
  is set, the margin is ignored, and after release the display equals an exact rebuild;
* speed: one dab < 20 ms;
* resizing: panels shrink and regrow, stay inside their cells, and a dab still lands in the
  right place afterwards;
* tools: Reset, Isolate Largest, the Q/E/R/S shortcuts and Save all still work, and the saved
  PNG is still **942×942** — identical to the old version's output;
* cursor markers on both panels and their cleanup on mouse-leave.

Run it with `python _dev/smoke_layout.py` from the `Mask_fixer` folder. It also writes
`screenshot shot_default.png` and `tkpanel_*.png` (a loss-free dump of what each panel holds)
for a human to eyeball; no check depends on the screen grabs, because another window can sit
in front of the test window.

---

# Round 2 — painting was laggy

You reported that painting in the green overlay felt slow and laggy. It was, and I measured
why before changing anything (`_dev/bench_paint.py`, `_dev/bench_region.py`).

## [CHANGE F1] A brush dab now updates only the square it touched

**The measurement** (your screen, 1102 px editable panel, 25 px brush, 80 back-to-back dabs
timed including Tk repainting the window):

| what happens per mouse-move dab | before | after |
|---|---|---|
| ellipse written into the working mask | 0.01 ms | 0.01 ms |
| bottom-left "Updating Mask" panel redrawn | 0.9 ms | 0.9 ms |
| **pushing the picture to the screen** | **10.1 ms** | **0.8–1.5 ms** |
| **total per dab** | **13.4 ms** | **1.7–2.3 ms** |
| a whole 80-dab stroke | ~1.07 s | ~0.15 s |

**Diagnosis.** It was not Tk drawing and it was not the mask: Tk's own redraw of the big
photo measured only 1.45 ms. The cost was me handing Tk the **entire** 1102×1102 image on
every single mouse-move — `Image.fromarray` of a 4.8 MB buffer plus a `paste` into the Tk
photo image, 10 ms each time, and Tk delivers 60–120 mouse-move events a second during a
drag. So the picture you saw trailed your cursor by about a second. That is exactly the lag
you felt, and it got worse the bigger the window was, because the photo grew with it.

**How it is fixed.** `Panel.put_region()`: the touched rectangle is put into a small reusable
scratch PhotoImage and copied into the displayed image **inside Tk**
(`image copy … -to x y`). Tk then only repaints that little square. Cost now follows the
*brush*, not the panel: 0.8 ms for the 25 px brush, 1.0 ms at 60 px, 1.5 ms for the 200 px
"Large Black" brush, on a 1102 px panel. `Panel.refresh()` (whole-image push) is kept and is
used only for genuine full rebuilds — start-up, window resize, Reset, Isolate Largest and the
end of each stroke — where 16 ms once is invisible.

`_blend_box()` (the partial re-blend added in `[CHANGE E7]`) now ends with `put_region()`
instead of pushing the whole buffer, and falls back to a full refresh if Tk refuses
(the `try/except tk.TclError` in `put_region`). Nothing about correctness changed: the
authoritative mask is still stamped exactly, and the closing full rebuild at
`<ButtonRelease-1>` is still there, verified by comparing the display buffer to a clean
rebuild with `np.array_equal`.

**New checks** in `_dev/smoke_layout.py` (now 57, all passing) so this cannot quietly regress:
* a dab must stay under 6 ms (measured 1.7 ms),
* a 200 px "Large Black" dab under 8 ms (measured 2.3 ms),
* 20 big dabs plus the closing rebuild under 0.5 s (measured 46 ms).

**Benchmark scripts kept**: `python _dev/bench_paint.py` (compares the whole-image paste, a
colour-text region put, and a vector-stroke approach) and `python _dev/bench_region.py`
(times region copies at different brush sizes). They open a real window and print numbers.

## What I tried and did not use

* **Colour-text region update** (`photo.put "#rrggbb …"`): 2.4–2.7 ms per dab, fine for small
  brushes but the cost grows with the brush area — the 200 px brush would have been ~10× worse
  than the Tk-side copy. Superseded by `put_region`.
* **A vector "live stroke"** (a thick stippled canvas line that follows the pointer, with the
  bitmap only baked on button release): 1.5 ms per dab — barely faster than the region copy,
  but the green would have been a stipple pattern rather than the real 40% blend, and it would
  have needed extra bookkeeping to avoid a visual jump on release. Not worth the loss of
  accuracy, so I kept the pixel-accurate path.

## If it still feels slow on your machine

Say so and tell me which window size you use. The remaining costs scale with the panel: the
closing rebuild and any resize re-render are ~16 ms at a 1102 px panel and roughly double that
on a much larger one. The one-line lever is `MAX_UPSCALE` at the top of the file (currently
`3`, i.e. the picture is never drawn bigger than 1536 px even if the window is larger):
dropping it to `2` halves the panel's pixel count. Note the input images are 512×512, so
anything above about 1024 px is only enlarging pixels that are already there.

---

# Round 3 — the green overlay did not update while you dragged

You reported: *"the green overlay does not update until after a click and drag has been
completed. The 'updating mask' works perfectly… I need the same for the green overlay."*
Exactly right, and it was my `[CHANGE F1]` fix that caused it.

## [CHANGE F2] Flush Tk's pending repaint after a partial update

**Why it happened.** My earlier checks only read the Tk *image object* — and that was being
updated correctly, which is why I believed the panel was live. What was not happening was the
**repaint**: Tk's `image copy … -to x y` changes the photo and then queues the redisplay as an
idle task. While a mouse button is held down, Tk's event queue never goes idle, so all those
pending repaints only flushed when you let go. The bottom-left mask panel kept working because
it goes through Pillow's `paste`, which damages the window directly — and before `[CHANGE F1]`
the middle panel also used a whole-image `paste`, which is (accidentally) why it looked live but
was slow.

**Why my checks missed it, and what I changed about testing.** A screen grab cannot be trusted
on this desktop: other windows (including an older copy of the editor) sit on top of the test
window, so a "screenshot" can measure somebody else's pixels — that already misled me once in
round 1. So the tests now capture the window with Win32 `PrintWindow`, which renders *our*
window into a bitmap whether it is covered or not (`_dev/wincap.py`), and the check does **not**
pump the event loop between the dab and the capture — that is what makes it a test of "live"
rather than "eventually".

**The fix** (`Panel.put_region`, one line): after copying the rectangle into the displayed
photo, call `self.canvas.update_idletasks()` so Tk repaints that rectangle straight away. It
costs about 0.7 ms per dab.

**Measured** (an 80-dab drag on a 1102 px panel):

| | before F1 | F1 alone | F1 + F2 |
|---|---|---|---|
| per dab | 13.4 ms | 1.7–2.3 ms | 2.3–2.9 ms |
| visible on screen during the drag | yes (but ~1 s behind) | **no** | yes, immediately |

**Proof it is fixed, and proof the test is real** (`_dev/smoke_layout.py`, now 60 checks):
* dab at a fresh spot, capture immediately: green in the dab square **0.000 before → 0.891
  after**, on screen, mid-drag;
* the same spot in the bottom-left mask panel: white **0.000 → 0.978** mid-drag;
* erasing with the black brush mid-drag: green back to **0.000**;
* **negative control**: with the `update_idletasks()` line commented out, the harness fails
  exactly those two live checks (0.000 → 0.000), reproducing your bug. So the check genuinely
  detects this class of problem instead of just agreeing with the code.

**New dev files**: `_dev/wincap.py` (occlusion-proof capture of our own window) and
`_dev/diag_live_refresh.py` (the diagnosis: six ways of nudging Tk, only the ones that flush
idle tasks actually repaint mid-drag).

---

# Round 4 — still not live, and only half the green appeared on a click

Both symptoms you reported were real, and they had one cause. `[CHANGE F2]` was necessary but
not sufficient: the repaint flush fixed a genuine problem, but the partial update was also
painting **in the wrong place**.

## [CHANGE F3] Canvas coordinates vs photo coordinates in the partial update

**The bug.** `paint()` works in *canvas* coordinates — that is what a mouse event gives you.
`_blend_box()` then used those numbers as *photo* coordinates, i.e. coordinates inside the
displayed image, whose origin is the canvas point `(offx, offy)`. Whenever the panel is
letterboxed — which is the normal case, because the cell is rectangular and the image is
square — those two spaces differ. In your window that margin was 41 px vertically at the default
size, 79 px at a smaller one, and 190 px horizontally in a short wide window.

So each dab repainted a rectangle that was offset from where the brush actually was, with the
correct content for that offset area (which was already correct) — visually a no-op:

* with the **25 px brush** the offset box did not overlap the real change at all → *nothing
  appeared while dragging*, exactly what you saw;
* with the **140–200 px brush** the offset box still overlapped the real change by 50–60% →
  *only part of the green appeared*;
* and because the closing full rebuild at `<ButtonRelease-1>` always repaints everything
  correctly, the overlay snapped into place the moment you let go — the "it only updates after
  the drag" behaviour.

The bottom-left mask panel never had this problem: it re-renders the whole small image from the
mask every time, so there is no second coordinate space to mix up.

**How it was found.** Measuring *where the update lands*, instead of whether one happened: one
dab, then a before/after capture of the window, then the bounding box of the pixels that
actually changed. Before the fix (with the `[CHANGE F2]` flush still in place):

```
brush  25  -> NOTHING changed on screen at all
brush 140  -> changed centre (826,343), expected (826,330)   displaced dy=+13
brush 200  -> changed centre (826,342), expected (826,330)   displaced dy=+12
```

After the fix (`_blend_box` converts canvas → photo before touching anything):

```
default window,      letterbox offset (0,41):  brush 25  centre (826,331) vs (826,330)
                                             brush 200 centre (826,330) vs (826,330)
short/wide window,   letterbox offset (190,0): brush 25  centre (404,161) vs (404,161)
                                             brush 200 centre (404,161) vs (404,161)
```

**Why my round-3 tests did not catch this.** They asked "is there green roughly where I drew",
and a displaced patch with a large brush still puts green roughly in the right place; and the
one strict check I added compared the capture against the buffer using canvas indices where the
capture needed photo indices — my own test had the same off-by-the-letterbox mistake, which
cancelled the app's error out. That is the lesson: an approximate check on the wrong coordinate
space is worse than no check, because it passes. The tests now (a) compare *where the change
landed*, (b) run at two window shapes, one letterboxed vertically and one horizontally, and (c)
compare the whole photo area, screen versus buffer, after a 25-dab stroke with the button still
held down.

**Proof the new checks are real (negative control).** With the canvas→photo conversion removed
again, the harness fails exactly the new checks, reproducing your two symptoms:

```
brush 25  … [default size]    nothing changed on screen at all
brush 200 … [default size]    centre (826,342) vs expected (826,330)
brush 25  … [short/wide]      nothing changed on screen at all
brush 200 … [short/wide]      nothing changed on screen at all
```

**Current status** — `_dev/smoke_layout.py`, 67 checks, all passing, including:
* `brush 25 repaints the middle panel live, in the right place` (default and short/wide),
* `brush 200 repaints the middle panel live, in the right place` (both),
* `a whole stroke is on screen before the button is released`: green 0.0513 on screen vs 0.0506
  in the buffer, after 25 dabs with no event pumping,
* `what is on screen matches the overlay buffer exactly mid-stroke`: mean channel difference 0.90,
* erasing visible mid-drag, and the speed guardrails (2.3–2.9 ms per dab).

**New dev file**: `_dev/diag_patch_placement.py` (the measurement above; run it to see where a
dab lands for any window size).

---

# Round 5 — jump-to-image selector + resume where you left off

You asked for *"a file menu selector on the bottom right that allows you to select which img
file to start with (if you put down and pick up later)"*.

## [CHANGE G1] Resume file

**What.** `.mask_fixer_state.json` next to the program, one entry per image folder:
```json
{ "Fluorescent_test_010": { "last": "A1_123_mask", "updated": "2026-11-12 14:32:09" } }
```
**Why.** "Put it down and pick it up later" needs the program to know where you were, across
restarts.
**How.** `load_state()` / `save_state()` at the top of the file. It stores a **name, not an
index**, so adding or removing images cannot silently point you at the wrong well. Writes go
through a `.tmp` file + `os.replace`, so a crash mid-write cannot leave a half-written file.
`load_state` never raises — a missing or corrupt file just means "no memory". The name of the
file is the constant `STATE_FILENAME`; delete it to forget everything. It holds no work of
yours: your masks stay in the export folder.

## [CHANGE G2] Where a run starts

**What.** `main()` now starts with `start_index=None`, meaning "wherever you left off", and
`resolve_start_index()` decides: explicit `start_index` → remembered image for this folder →
first image with no saved mask → first image. It also prints what it chose:
`folder Fluorescent_test_010: 5 images, 0 already saved; starting at image 1 of 5 (A1_0_mask)`.
**How.** The state is written every time the run moves to another image, and when you press
Quit, so it is accurate whenever the program is closed however you closed it.

## [CHANGE G3] The selector itself (bottom right)

**What.** At the right end of the bottom row: `Jump to image: [A1_1 ▼] Go` plus a small status
label. All images in the run are listed; ones that already have a mask in the export folder are
marked `[saved]`.
**How.**
* A `ttk.Combobox` rather than an `OptionMenu`: your plate runs are 1120 images, and scrolling
  a 1000-entry menu is hopeless — you can type instead. `JUMP_LIST_HEIGHT` sets how many rows
  the drop-down shows.
* Names are shown **without** the `_mask` tail (the files come as `A1_0_img / _mod / _mask`, so
  the selector shows `A1_0`); the internal key stays the full stem, which is also the name the
  exported mask is saved under.
* It is packed `side=tk.RIGHT` **before** the buttons, because `pack` hands out space in order:
  packing the `expand=True` LEFT buttons first would leave no room at the right.
* What you can type, handled by `_resolve_jump`: an exact name (`A1_123`), a unique fragment
  (`1_12` → `A1_123`), or a **number matching the title bar** (`448` or `#448` jumps to "Image
  448 of 1120"). Unknown input says `not found`, ambiguous input says `several` and lists the
  first few candidates in the console. Choosing from the drop-down or pressing Enter jumps.
* Jumping goes through the same unsaved-edits guard as Prev/Next.

## [CHANGE G4] Shortcuts must not fire while you type

**What.** `_typing()` guard at the top of the hotkey handler.
**Why.** The one-letter shortcuts (`a`, `d`, `q`, `e`, `s`, `r`) and the arrow keys are bound on
the whole window. Without this, typing `d` into the jump box would also page to another image,
and the arrow keys would move the caret *and* change image.
**How.** `focus_get()` plus, because ttk keeps a combobox's text in an internal entry that
tkinter may not hand back as a Python object, a `winfo class` query on `focus_displayof()`.

## [CHANGE G5] `_leave` now reports whether it actually left

**What.** `_leave(action)` returns True/False.
**Why.** `on_jump` sets `goto_index` before closing the window, so if the user cancels the
unsaved-edits prompt, that half-made request is now cleared instead of lingering. (A harness
check caught this: it left `goto_index = 3` behind after a cancelled jump.)

## Verification

`_dev/smoke_layout.py` grew from 67 to **100 checks**, all passing. The new ones confirm:
the selector exists (label, combobox, Go button, status label); it is **inside the window**,
**below the image grid** and **at the right edge** (right side 1804 of 1810), with the Quit
button still ending before it (1428 vs 1434); it lists every image and pre-fills the current
one; `[saved]` appears only for images with an export; name resolution in ten cases
(`A1_2`, `A1_2_mask`, `A1_2  [saved]`, `3`, `#4`, a fragment, and four bad inputs); focus in
the box is detected and pressing `d` there does **not** change image while focus on the image
does; the resume file's remembered image wins, an explicit start index wins over it, each
folder keeps its own place, and a corrupt state file does not crash start-up; and a jump
saves-and-continues when asked, and stays put when cancelled.

New: `_dev/test_resume_loop.py` (**6 checks**) runs `main()` for real with `Tk.mainloop`
stubbed, so the actual run loop is exercised without clicking: a normal run visits every image;
the resume file remembers the last one; **restarting opens the remembered image**
(`starting at image 5 of 5 (A1_4_mask)`); a jump goes straight there (`[0, 2, 3, 4]`); an
out-of-range jump falls back to Next; and jumping backwards then forwards works
(`[0, 1, 0, 1, 2, 3, 4]`).

The bottom row is shown in `_dev/cap_bottom_row.png`, captured with `PrintWindow` (the
occlusion-proof method from round 4) rather than a screen grab.

## Behaviour to know about

* Starting the program now **opens the image you were last on**, not the first one. To force a
  specific start, call `main(start_index=0)`, or use the selector, or delete
  `.mask_fixer_state.json`.
* The state file is written into the folder the program is run from. If you launch it from
  different working directories it will not find its memory — the file lives beside the current
  directory, not beside the script.
* Typing in the box deliberately suppresses the one-letter shortcuts; click back on the image
  (or Tab) to get them back.

---

## Deliberately unchanged

* **Exported mask files are still 942×942.** The saved mask's resolution is the mask's
  *working* resolution, which I kept at exactly the old value, so nothing downstream that
  consumes `exported_masks` is affected. (Your input images are 512×512, so if you would
  rather the exported masks match the input size, change `MASK_NATIVE_SIDE = 512` — one line.
  I did not do it because it changes your output files.)
* Buttons, hotkeys, unsaved-edits guard, Prev/Next/Quit behaviour, the export folder and the
  image-discovery loop in `main()` are untouched.
* The green colour, 0.4 alpha and the "paint only on the big panel" rule are the same as before.

## Things you may want to tune

| Constant (top of `Mask_fixer_app.py`) | Meaning | Current |
|---|---|---|
| `OVERLAY_BASE` | base image under the green mask: `"unmod"` or `"mod"` | `"unmod"` |
| `OVERLAY_COLOR` / `OVERLAY_ALPHA` | the green wash | `(0,255,0,255)` / `0.40` |
| `MASK_NATIVE_SIDE` | working + exported mask resolution | `942` |
| `MAX_UPSCALE` | how far a 512 px source may be blown up in the middle panel | `3` |
| `MIN_BIG_SIDE`, `MIN_SMALL_SIDE` | the smallest the panels may get (a preference, not a law - see [CHANGE H1]) | `360`, `150` |
| `CHROME_H` | first-pass guess for everything except the middle panel, used only until `_fit_window()` measures it | `170` |
| `DECOR_H`, `EDGE` | [CHANGE H1] room for the title bar + borders, and slack at the screen edges | `40`, `12` |
| `SMALL_BRUSH_SIZE`, `LARGE_BRUSH_SIZE` | [CHANGE H2] the two brush sizes | `25`, `200` |

---

# Round 6 - the clipped button row, the G shortcut, and the Large Black size bug

You asked for three things:

1. *"full screen or move the window so that there isn't clipping of the buttons when started
   (or going to next image)"*
2. *"add a shortcut for large Black at the button"*
3. *"fix the size bug"* - after Large Black, the White / small Black buttons kept the big swatch

New tags: `[CHANGE H1]` (window fits the screen), `[CHANGE H2]` (brush size), `[CHANGE H3]` (the
G key). Nothing else in the program was touched: the panels, the painting, the export size
(942x942), the other shortcuts and the run loop all behave as before.

## Both problems reproduced first, before changing anything

`_dev/probe_layout.py` builds the real window and prints where every button ends up. Before
the change, on this machine (screen 2333x1312; the taskbar leaves a work area that ends at
**1266**):

```
geometry 1782x1232+20+20   client 20,20 -> bottom 1283
btn_large_black  y=1257 h=26 bottom=1283  CLIPPED by 17 px
btn_QUIT         y=1257 h=26 bottom=1283  CLIPPED by 17 px
jump_box         y=1259 h=21 bottom=1280  CLIPPED by 14 px
... all 12 widgets in the bottom row, clipped by the same 14-17 px
brush after start 25 -> after Large Black 200 -> after White 200 -> after Black 200
```
(the brush line came from the buttons as they were wired *then*; the same probe now reads
`25 -> 200 -> 25 -> 200 -> 25`, and `after the G key 200`, printed at the end of the run)

17 px missing off a 26 px button: enough that you could neither see nor click them until you
dragged the window up, which is exactly what you described.

## [CHANGE H1] The window is fitted to the screen instead of guessed

**What.** The window now opens as large as the usable screen allows, with the whole button row
on screen, at any display size and any display scaling. Two rewritten helpers and four new ones:

| place in `Mask_fixer_app.py` | role |
|---|---|
| `_work_area()` (new) | the part of the screen that is not the taskbar |
| `_plan_layout()` (rewritten) | first pass, before the widgets exist |
| `_fit_window()` (new) | second pass, once they do - this is the one that fixes the clipping |
| `_desired_small()` (fixed) | thumbnail size on resize, now limited by height as well as width |
| `_desired_big()` (new) | middle panel size on resize |
| `refit_window()` (new, bound to F11) | do the fit again without restarting |

**Why.** The old size came from three guesses that were all wrong at once:

* `winfo_screenheight()` (1312) is the **whole** screen; the taskbar is not space a window may
  sit in, and the usable area here stops at 1266;
* `CHROME_H = 170` was a guess for "the label rows + the button row". Measured, it is 47 px
  (one 21 px label row + one 26 px button row), so the guess made the *panel* smaller than it
  could be while saying nothing useful about the thing that mattered;
* Tk's `geometry()` and `winfo_height()` describe the **client area**, i.e. the window *below*
  the title bar. The title bar and borders add 31 px above it. Nothing accounted for that.

So: 20 (top offset) + 31 (title bar) + 1232 (client) = 1283, and the work area stops at 1266.
Every image got the same treatment, which is why it happened again each time you pressed Next -
each image is a brand-new window.

**How.**

1. `_work_area()` asks Windows for the real usable rectangle with
   `SystemParametersInfo(SPI_GETWORKAREA)` through `ctypes` (standard library: no new
   dependency). Because Windows display scaling can make the two APIs speak different units,
   the rectangle is rescaled by comparing the full-screen size Windows reports with the one Tk
   reports (on this machine they agree). If the call fails, or you are not on Windows, it falls
   back to the whole screen and says so in the console - the program never dies over a sizing
   question.
2. `_plan_layout()` (it still has to run before the widgets exist, so it still uses the
   `CHROME_H` estimate) now works from the work area, keeps `DECOR_H` (40 px for title bar and
   borders; measured 31) and `EDGE` (12 px) clear, and places the window at the top-left of the
   *usable* area instead of a hard-coded `+20+20`.
3. `_fit_window()` runs at the end of `__init__`, once every widget exists, and replaces the
   guess with a measurement:
   * `chrome_h = root.winfo_reqheight() - canvas2.winfo_reqheight()` - the height of the label
     rows and the button row, **measured**, so it is right whatever font size and whatever
     display scaling you use;
   * the thumbnails are sized from the same budget (`(room_h - 2 * label_h) // 3`, capped by
     the width) so the left column ends up exactly as tall as the middle panel;
   * the middle square is the largest that fits, capped at `source_side * MAX_UPSCALE` - there
     is no point asking for more pixels than the 512 px files hold;
   * the loop runs up to four times, re-measuring after each change, because the sizes depend on
     each other; if even `MIN_SMALL_SIDE` / `MIN_BIG_SIDE` do not fit it repeats with soft floors
     (60 / 120) - **the button row always wins**, the pictures give way;
   * the window height is then set to *exactly* what the content asks for, which makes it
     impossible for the content to be taller than the window - and that is what clipping *is*;
   * then the real position is checked with `winfo_rooty() + winfo_height()`: if the window
     manager still put the bottom edge past the work area, the window is pulled up first, and
     height is only given back as a last resort;
   * `minsize` / `maxsize` come from the same measurements. No narrower than the button row
     itself (that would squeeze it) and never taller than the work area - a window you maximise
     now stops above the taskbar instead of under it.
4. `_desired_small()` had a bug that would have undone all of this: it only ever grew the
   thumbnails towards `MIN_SMALL_SIDE`, from the window *width*, so the very next `<Configure>`
   after a fit pass could grow them back taller than the window and push the row out again. It
   now takes the smaller of the width limit and the height limit
   `(h - 3 * label_h - ctrl_h) // 3`. This is the check that failed first on a simulated
   1024x600 screen, and the reason the result is a guarantee rather than a lucky number.
5. `_desired_big()` does the same for the middle square: it is re-requested from the window
   height, so when you resize the window the panel follows instead of leaving the button row
   nowhere to go. `on_window_resize` now re-requests both sizes and does nothing when neither
   changed (dragging an edge stays cheap).
6. `refit_window()` is bound to **F11**. If you ever drag the window below the work area, or
   move it to a different monitor, one key press puts it back without restarting.
7. In `__init__` the old `after_idle(self._render_all)` + fixed `minsize(...)` pair was replaced
   by `self._fit_window()`, which ends with `self._render_all()` - so every panel is painted
   once at its **fitted** size rather than at the guessed one.

**Result on this machine** (same probe script, after the change):

```
geometry 1917x1214+12+0   client bottom 1245   work-area bottom 1266   21 px to spare
all 12 bottom-row widgets VISIBLE
window on screen 1933x1253, 13 px of clear space below it
```

The middle panel is a **1167 px** square (it was about 1102 before) and the thumbnails are 375
(were 340), so the window is not merely shorter: there is more image to work on, which is the
"full screen" half of what you asked for.

## [CHANGE H2] The brush size belongs to the button, not to the last tool you used

**What.** Two named constants at the top of the file - `SMALL_BRUSH_SIZE = 25` and
`LARGE_BRUSH_SIZE = 200` - used by the buttons, the shortcuts, the start-up size and the
"which tool is active" shading.

**Why.** The size bug was a one-token mistake:

```python
command=lambda: self.set_color("white", brush_size=self.brush_size)
```

A `lambda` does not capture the value when it is created - it reads `self.brush_size` **when you
click**. So the small buttons asked for whatever size happened to be current, and one click on
"Large Black" (200 px) left them painting with the 200 px swatch for the rest of the session.
There was no way back short of restarting. That is the `25 -> 200 -> 200 -> 200` line above.

**How.**

* `btn_black` / `btn_white` and the `q` / `e` shortcuts pass `SMALL_BRUSH_SIZE` explicitly,
  which pins the size to the button rather than to history;
* `set_large_black()` is now just `set_color("black", brush_size=LARGE_BRUSH_SIZE)`, so a brush
  size is decided in exactly one place; it also takes an optional `event` argument so it can be
  used directly as a callback (that is what the button now uses: `command=self.set_large_black`,
  no lambda needed);
* `set_color()`'s default when no size is given is `SMALL_BRUSH_SIZE`. The old default was
  `10 if color == "white" else 10` - both branches 10, i.e. a leftover that made the size depend
  on which caller happened to forget the argument;
* `_sync_tool_buttons()` decides which button looks pressed by comparing against
  `LARGE_BRUSH_SIZE` instead of the hard-coded `200`, so changing a constant changes the button
  shading and the shortcut together.

## [CHANGE H3] G is the Large Black shortcut

**What.** The button reads `Large Black (G)` and `g` does exactly what clicking it does.

**How.** one line in `HOTKEYS`: `'g': 'large_black'`, plus the matching branch in `run_hotkey`.
Everything else came free: the label picks its letter up from `HOTKEYS` through `hotkey_hint()`,
so a label can never drift away from the binding; `make_hotkey` handles the auto-repeat guard;
the "do not fire while you are typing in the jump box" guard ([CHANGE G4]) applies to it like any
other letter; and `_sync_tool_buttons()` sinks the button so you can see the big brush is armed
without looking for it.

## Verification

New `_dev/smoke_round6.py` - **74 checks, all passing**:

* the window is built at **five** screen sizes (this monitor, plus faked 1366x768, 1280x720,
  1024x600 and 1920x1080 work areas). For each one: the window is inside the work area; all 13
  widgets of the bottom row are fully inside the window *and* on screen; none is squashed to
  nothing; the client is at least as tall as the content it holds; the min and max sizes stay
  inside the screen;
* deliberately pushing the window 200 px below the work area and pressing F11 brings the row
  back (`bottom now 1245, work-area bottom 1266`);
* the size bug, through the real buttons (`.invoke()`, the same code path a click takes):
  Large Black -> 200, White -> 25, Black -> 25, and 200/25 across repeated switching, with the
  pressed-button shading following. The **footprint on the mask** is measured as well, not just
  the number: 489 px^2 with the small brush, 31689 px^2 with the large one, 489 px^2 again after
  the small button;
* the G shortcut: present in `HOTKEYS`, bound on the window, printed on the label, and a real
  generated key press switches to 200 px black and sinks the button; G does **not** fire while
  the caret is in the jump box; `E` and `Q` after `G` go back to 25;
* resizing after start-up: minimum size, short-and-wide (1600x480), tall-and-narrow (1000x1000),
  very short (1400x380) and bigger-than-fitted - the row stays reachable in all five, and the
  middle panel tracks the window (canvas2 381 in a window with room for 381; 433/433; 953/953;
  1167/1167);
* the working mask is still 942x942 whatever the window does, so your exports are unaffected.

New `_dev/smoke_run_round6.py` runs **the real `main()` loop** over the five test images and
checks each window 60 ms after it opens: all five are 1917x1214 with **0 clipped widgets**.
That is the "or going to next image" half of your report.

New `_dev/negative_control_round6.py` puts the old sizing code back and shows the new checks are
not decoration: with the old code the deepest button is **17 px below the work area** and the
small buttons stay at **200 px** after Large Black - both of your symptoms, on demand.

New `_dev/wincap_round6.py` captures the live window with `PrintWindow` (works even when another
program is in front of it): `_dev/window_round6.png` and `_dev/bottom_row_round6.png` show the
whole row - `Large Black (G) | Black (Q) | White (E) | Isolate Largest | Reset (R) | Save (S) |
Prev (A) | Next (D) | Quit | Jump to image: [A1_0] Go` - with clear space under it.

`_dev/probe_screen.py` and `_dev/probe_panels.py` are the measuring sticks behind the numbers
(how Tk's screen size relates to the Windows work area and the title bar, and whether every
panel really was drawn after the fit).

## Behaviour to know about

* The window opens **as large as the screen allows** and never hangs off the bottom. The middle
  panel is bigger than before (1167 px here, about 1102 before), thumbnails 375 (was 340).
* You can still make the window **smaller** (down to 946x428 here) but not bigger than the
  usable screen - that ceiling is what stops the row being pushed out again.
* **F11** re-fits the window. The key list is now: `Q` black, `E` white, **`G` large black**,
  `S` save, `A` previous, `D` next, `R` reset, plus the arrows, Ctrl+S and F11.
* On a screen too small for the preferred panel sizes the panels shrink further rather than the
  buttons disappearing.
* Unchanged, deliberately: the baseline mask panel still sits at the top of the right-hand
  column with empty space below it - that was already true before this round (that column's cell
  is a single grid row). Say the word and I will stretch it to the full height like the middle
  panel.

## Deliberately unchanged (round 6)

* Exported masks are still 942x942 (`MASK_NATIVE_SIDE`), and painting still happens only on the
  middle panel.
* The other shortcuts, the unsaved-edits guard, Prev/Next/Quit, the jump selector, the resume
  file, the green overlay and the brush preview colours are untouched.
* No new dependency: `ctypes` ships with Python.

