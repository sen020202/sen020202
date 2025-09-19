import tkinter as tk
from tkinter import filedialog, messagebox
import pikepdf
import os

def unlock_pdf():
    input_pdf = filedialog.askopenfilename(
        title="Select Locked PDF",
        filetypes=[("PDF Files", "*.pdf")]
    )
    
    if not input_pdf:
        return
    
    password = password_entry.get().strip()
    if not password:
        messagebox.showerror("Error", "Please enter the password!")
        return
    
    output_pdf = filedialog.asksaveasfilename(
        title="Save Unlocked PDF As",
        defaultextension=".pdf",
        filetypes=[("PDF Files", "*.pdf")],
        initialfile=f"unlocked_{os.path.basename(input_pdf)}"
    )
    
    if not output_pdf:
        return
    
    try:
        pdf = pikepdf.open(input_pdf, password=password)
        pdf.save(output_pdf)
        pdf.close()
        messagebox.showinfo("Success", f"✅ Password removed!\nFile saved as:\n{output_pdf}")
    except pikepdf.PasswordError:
        messagebox.showerror("ALERT ❌", "The supplied password is incorrect!\nPlease try again.")
        password_entry.delete(0, tk.END)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to unlock PDF:\n{e}")

# Toggle password visibility
def toggle_password():
    if password_entry.cget("show") == "":
        password_entry.config(show="*")
        toggle_btn.config(text="🔓")  # closed eye
    else:
        password_entry.config(show="")
        toggle_btn.config(text="👁️")  # open eye

# GUI setup
root = tk.Tk()
root.title("PDF Password Remover")
root.geometry("420x280")
root.resizable(False, False)

# Disclaimer
disclaimer = ("⚠️ Disclaimer:\n"
              "This tool is NOT a password cracker.\n"
              "You must already know the PDF password.\n"
              "It only removes the password from files you have access to.")

tk.Label(root, text=disclaimer, font=("Arial", 9), fg="red", justify="center", wraplength=400).pack(pady=10)

tk.Label(root, text="Enter PDF Password:", font=("Arial", 12)).pack(pady=5)

frame = tk.Frame(root)
frame.pack(pady=5)

password_entry = tk.Entry(frame, show="*", width=25, font=("Arial", 12))
password_entry.pack(side="left", padx=5)

toggle_btn = tk.Button(frame, text="🔓", width=3, command=toggle_password, font=("Arial", 10))
toggle_btn.pack(side="left")

unlock_button = tk.Button(root, text="Select PDF & Remove Password", command=unlock_pdf, font=("Arial", 12), bg="#4CAF50", fg="white")
unlock_button.pack(pady=20)

root.mainloop()
