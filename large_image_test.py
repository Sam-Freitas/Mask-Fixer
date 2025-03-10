import tkinter as tk
from PIL import Image, ImageTk

root = tk.Tk()

# Load the image
image = Image.open("path3.png")
image2 = Image.open("path1.png")
photo = ImageTk.PhotoImage(image)
photo2 = ImageTk.PhotoImage(image2)

# Create a Label widget to display the image
image_label = tk.Label(root, image=photo)
image_label.grid(row=0, column=0, columnspan=3, rowspan=2) 
# columnspan=3 makes the image span 3 columns
# rowspan=2 makes the image span 2 rows

# Add other widgets (optional)
text_label = tk.Label(root, text="Some text")
text_label.grid(row=2, column=1)

image_label = tk.Label(root, image=photo2)
image_label.grid(row=3, column=1)#, columnspan=1, rowspan=1) 

button = tk.Button(root, text="Click me")
button.grid(row=0, column=3)


root.mainloop()