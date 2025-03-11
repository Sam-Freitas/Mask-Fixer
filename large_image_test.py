import tkinter as tk
from PIL import Image, ImageTk
import numpy as np

root = tk.Tk()
root.geometry("1300x800+50+1")

small_img_size = (256,256)
n = 3.1
big_img_size = (int(256*n),int(256*n))

# Load the image
image = Image.open("path1.png").resize(big_img_size)
image2 = Image.open("path2.png").resize(small_img_size)
image3 = Image.open("path3.png").resize(small_img_size)

image4 = Image.fromarray(np.random.rand(small_img_size[0],small_img_size[1]))

photo = ImageTk.PhotoImage(image)
photo2 = ImageTk.PhotoImage(image2)
photo3 = ImageTk.PhotoImage(image3)
photo4 = ImageTk.PhotoImage(image4)

# Create a Label widget to display the image
image_label = tk.Label(root, image=photo)
image_label.grid(row=0, column=0, columnspan=3, rowspan=3) 
# columnspan=3 makes the image span 3 columns
# rowspan=2 makes the image span 2 rows

image_label2 = tk.Label(root, image=photo2)
image_label2.grid(row=0, column=4)

image_label3 = tk.Label(root, image=photo3)
image_label3.grid(row=1, column=4)

image_label4 = tk.Label(root, image=photo4)
image_label4.grid(row=2, column=4)

button = tk.Button(root, text="Click me")
button.grid(row=0, column=5)


# Add other widgets (optional)
# text_label = tk.Label(root, text="Some text")
# text_label.grid(row=4, column=3)

root.mainloop()