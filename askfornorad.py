import tkinter as tk
from tkinter import simpledialog, messagebox

def ask_for_norad_ids_and_days():
    root = tk.Tk()
    root.title("Satellite Observation Configuration")
    root.focus_force()  # Force the window to take focus

    # Check if the user wants to run the script
    run_script = messagebox.askyesno("Run Script", "Do you want to run the script?", parent=root)
    if not run_script:
        print("Script execution cancelled by the user.")
        root.destroy()
        return None, None, None  # Return None values to indicate script cancellation

    class CustomDialog(simpledialog.Dialog):
        def body(self, master):
            tk.Label(master, text="NORAD IDs (comma-separated):").grid(row=0, columnspan=2)
            self.norad_ids_text = tk.Text(master, height=5, width=40)
            self.norad_ids_text.grid(row=1, columnspan=2)

            tk.Label(master, text="Days ahead for observation (max 10):").grid(row=2, column=0)
            self.days_entry = tk.Entry(master)
            self.days_entry.grid(row=2, column=1)

            tk.Label(master, text="Observation window in minutes:").grid(row=3, column=0)
            self.observation_window_entry = tk.Entry(master)
            self.observation_window_entry.grid(row=3, column=1)

            return self.norad_ids_text  # Initial focus

        def apply(self):
            norad_ids_str = self.norad_ids_text.get("1.0", tk.END)
            days_str = self.days_entry.get()
            observation_window_str = self.observation_window_entry.get()

            self.result = (norad_ids_str, days_str, observation_window_str)

    root = tk.Tk()
    root.withdraw()  # Hide the main window

    dialog = CustomDialog(root)
    if dialog.result:
        norad_ids_str, days_str, observation_window_str = dialog.result

        norad_ids = [id.strip() for id in norad_ids_str.split(',')] if norad_ids_str.strip() else []
        days = min(max(int(days_str), 1), 10) if days_str.isdigit() else 1
        observation_window = int(observation_window_str) if observation_window_str.isdigit() else 2
        if observation_window_str.lower() == 'full':
            observation_window = 'full'

        return norad_ids, days, observation_window
    else:
        return None, None, None