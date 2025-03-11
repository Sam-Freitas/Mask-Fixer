import tkinter as tk

class ListNavigator:
    def __init__(self, master, data_list):
        self.master = master
        self.data_list = data_list
        self.index = 0

        self.label = tk.Label(master, text=self.data_list[self.index])
        self.label.pack()

        self.prev_button = tk.Button(master, text="Previous", command=self.show_previous)
        self.prev_button.pack()

        self.next_button = tk.Button(master, text="Next", command=self.show_next)
        self.next_button.pack()

    def show_previous(self):
        self.index = (self.index - 1) % len(self.data_list)
        self.label.config(text=self.data_list[self.index])

    def show_next(self):
        self.index = (self.index + 1) % len(self.data_list)
        self.label.config(text=self.data_list[self.index])

if __name__ == "__main__":
    root = tk.Tk()
    data = ["apple", "banana", "cherry", "date", "elderberry"]
    navigator = ListNavigator(root, data)
    root.mainloop()