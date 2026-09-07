import tkinter as tk
import sqlite3
from datetime import date, timedelta
from tkinter import ttk, messagebox

# Connect to database
conn = sqlite3.connect("database.db")
cursor = conn.cursor()

# Create tables
cursor.execute("""
CREATE TABLE IF NOT EXISTS passengers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    age INTEGER NOT NULL

)
""")


def migrate_old_tickets_table_if_needed():
    """
    If a 'tickets' table already exists from an older version of this app
    (missing the new columns), rename it out of the way instead of deleting
    it, then create a fresh 'tickets' table with the current schema.
    """
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tickets'")
    exists = cursor.fetchone() is not None

    if not exists:
        return

    cursor.execute("PRAGMA table_info(tickets)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    required_columns = {
        "passenger_id", "destination", "seat_number",
        "travel_date", "base_price", "discount_applied", "final_price",
        "attendant"
    }

    if required_columns.issubset(existing_columns):
        return  # schema already up to date

    # Old schema detected -> rename it out of the way (backup, not deleted)
    backup_name = "tickets_old"
    cursor.execute(f"DROP TABLE IF EXISTS {backup_name}")
    cursor.execute(f"ALTER TABLE tickets RENAME TO {backup_name}")
    conn.commit()
    print(f"Old 'tickets' table found with outdated schema. "
          f"Renamed to '{backup_name}' and created a new 'tickets' table.")


migrate_old_tickets_table_if_needed()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    passenger_id INTEGER NOT NULL,
    destination TEXT NOT NULL,
    seat_number INTEGER NOT NULL,
    travel_date TEXT NOT NULL,
    base_price REAL NOT NULL,
    discount_applied TEXT NOT NULL,
    final_price REAL NOT NULL,
    attendant TEXT NOT NULL,
    FOREIGN KEY (passenger_id) REFERENCES passengers (id)
)
""")
conn.commit()

# ------------------- Fixed config -------------------
DISCOUNT_RATE = 0.20       # 20% discount for minors, students, or PWD
MINOR_AGE_CUTOFF = 18
SEATS_PER_TRIP = 40        # seats 1..40 available per destination/date
DAYS_AHEAD = 14            # how many upcoming days show up as bookable

ROUTES = {
    "Dagupan": 50.00,
    "Urdaneta": 60.00,
    "Tarlac": 180.00,
    "San Fernando": 280.00,
    "Manila": 350.00,
}

CURRENT_ATTENDANT = ""  # set at login, before the main window opens


def generate_dates():
    today = date.today()
    return [(today + timedelta(days=i)).isoformat() for i in range(1, DAYS_AHEAD + 1)]


def find_next_available_seat(destination, travel_date):
    cursor.execute(
        "SELECT seat_number FROM tickets WHERE destination = ? AND travel_date = ?",
        (destination, travel_date)
    )
    taken = {row[0] for row in cursor.fetchall()}
    for seat in range(1, SEATS_PER_TRIP + 1):
        if seat not in taken:
            return seat
    return None


# ------------------- Passenger functions -------------------
def refresh_list():
    for row in tree.get_children():
        tree.delete(row)
    cursor.execute("SELECT id, name, age FROM passengers")
    rows = cursor.fetchall()
    for row in rows:
        tree.insert("", tk.END, values=row)
    refresh_passenger_dropdown(rows)


def refresh_passenger_dropdown(rows=None):
    if rows is None:
        cursor.execute("SELECT id, name, age FROM passengers")
        rows = cursor.fetchall()
    values = [f"{r[0]} - {r[1]}" for r in rows]
    passenger_dropdown["values"] = values
    if values and not passenger_var.get():
        passenger_var.set(values[0])
    elif not values:
        passenger_var.set("")


def add_passenger():
    name = name_entry.get()
    age_raw = age_entry.get()

    if not name or not age_raw:
        messagebox.showwarning("Warning", "Please fill in all fields.")
        return

    if not age_raw.isdigit():
        messagebox.showwarning("Warning", "Age must be a whole number.")
        return

    age = int(age_raw)

    cursor.execute(
        "INSERT INTO passengers (name, age) VALUES (?, ?)",
        (name, age)
    )
    conn.commit()

    messagebox.showinfo("Success", "Passenger added!")

    name_entry.delete(0, tk.END)
    age_entry.delete(0, tk.END)

    refresh_list()


def delete_passenger():
    selected_item = tree.selection()
    if not selected_item:
        messagebox.showwarning("Warning", "Please select a passenger to delete.")
        return

    values = tree.item(selected_item[0], 'values')
    passenger_id = values[0]
    passenger_name = values[1]

    confirm = messagebox.askyesno(
        "Confirm Delete",
        f"Are you sure you want to delete passenger '{passenger_name}'?\n"
        "This will also delete all of their tickets."
    )

    if not confirm:
        return

    cursor.execute("DELETE FROM tickets WHERE passenger_id = ?", (passenger_id,))
    cursor.execute("DELETE FROM passengers WHERE id = ?", (passenger_id,))
    conn.commit()

    messagebox.showinfo("Success", "Passenger deleted!")

    refresh_list()
    refresh_ticket_list()


# ------------------- Ticket functions -------------------
def refresh_ticket_list():
    for row in ticket_tree.get_children():
        ticket_tree.delete(row)
    cursor.execute("""
        SELECT tickets.id, passengers.name, tickets.destination,
               tickets.seat_number, tickets.travel_date,
               tickets.base_price, tickets.discount_applied, tickets.final_price,
               tickets.attendant
        FROM tickets
        JOIN passengers ON tickets.passenger_id = passengers.id
    """)
    for row in cursor.fetchall():
        ticket_tree.insert("", tk.END, values=row)


def get_discount_reasons():
    selection = passenger_var.get()
    reasons = []

    if selection:
        passenger_id = selection.split(" - ")[0]
        cursor.execute("SELECT age FROM passengers WHERE id = ?", (passenger_id,))
        result = cursor.fetchone()
        age = result[0] if result else None
        if age is not None and age < MINOR_AGE_CUTOFF:
            reasons.append("Minor")

    if student_var.get():
        reasons.append("Student")
    if pwd_var.get():
        reasons.append("PWD")

    return reasons


def compute_price(base_price, reasons):
    if reasons:
        return round(base_price * (1 - DISCOUNT_RATE), 2)
    return base_price


def update_auto_fields(*_args):
    destination = destination_var.get()
    travel_date = date_var.get()

    if not destination or not travel_date:
        seat_value_label.config(text="--")
        price_value_label.config(text="--")
        return

    seat = find_next_available_seat(destination, travel_date)
    base_price = ROUTES.get(destination, 0)
    reasons = get_discount_reasons()
    final_price = compute_price(base_price, reasons)

    if seat is None:
        seat_value_label.config(text="FULL (no seats left)")
    else:
        seat_value_label.config(text=f"Seat {seat} (auto-assigned)")

    if reasons:
        price_value_label.config(
            text=f"P{base_price:.2f} -> P{final_price:.2f} ({' + '.join(reasons)} -20%)"
        )
    else:
        price_value_label.config(text=f"P{base_price:.2f}")


def add_ticket():
    selection = passenger_var.get()
    destination = destination_var.get()
    travel_date = date_var.get()

    if not selection:
        messagebox.showwarning("Warning", "Please add a passenger first.")
        return

    if not destination or not travel_date:
        messagebox.showwarning("Warning", "Please select a destination and travel date.")
        return

    seat = find_next_available_seat(destination, travel_date)
    if seat is None:
        messagebox.showerror(
            "Fully Booked",
            f"All {SEATS_PER_TRIP} seats for {destination} on {travel_date} are taken.\n"
            "Please choose a different date."
        )
        return

    passenger_id = selection.split(" - ")[0]
    base_price = ROUTES.get(destination, 0)
    reasons = get_discount_reasons()
    final_price = compute_price(base_price, reasons)
    discount_label = " + ".join(reasons) if reasons else "None"

    cursor.execute(
        "INSERT INTO tickets "
        "(passenger_id, destination, seat_number, travel_date, base_price, discount_applied, final_price, attendant) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (passenger_id, destination, seat, travel_date, base_price, discount_label, final_price, CURRENT_ATTENDANT)
    )
    conn.commit()

    messagebox.showinfo(
        "Success",
        f"Ticket booked by {CURRENT_ATTENDANT}!\nSeat: {seat}\nDiscount: {discount_label}\nFinal Price: P{final_price:.2f}"
    )

    student_var.set(False)
    pwd_var.set(False)
    update_auto_fields()
    refresh_ticket_list()


def delete_ticket():
    selected_item = ticket_tree.selection()
    if not selected_item:
        messagebox.showwarning("Warning", "Please select a ticket to delete.")
        return

    values = ticket_tree.item(selected_item[0], 'values')
    ticket_id = values[0]
    passenger_name = values[1]
    destination = values[2]

    confirm = messagebox.askyesno(
        "Confirm Delete",
        f"Delete ticket for '{passenger_name}' to '{destination}'?"
    )

    if not confirm:
        return

    cursor.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
    conn.commit()

    messagebox.showinfo("Success", "Ticket deleted!")

    refresh_ticket_list()
    update_auto_fields()


# ------------------- Login screen -------------------
def show_login_screen():
    login_win = tk.Tk()
    login_win.title("Attendant Login")
    login_win.geometry("320x180")
    login_win.resizable(False, False)

    tk.Label(
        login_win, text="Passenger & Attendant Ticketing System",
        font=("Arial", 10, "bold"), wraplength=280, justify="center"
    ).pack(pady=(15, 5))

    tk.Label(login_win, text="Enter your name to log in as attendant:").pack(pady=(10, 0))

    attendant_entry = tk.Entry(login_win, justify="center")
    attendant_entry.pack(pady=5)
    attendant_entry.focus()

    def submit_login(event=None):
        global CURRENT_ATTENDANT
        name = attendant_entry.get().strip()
        if not name:
            messagebox.showwarning("Warning", "Please enter your name to continue.", parent=login_win)
            return
        CURRENT_ATTENDANT = name
        login_win.destroy()
        build_main_window()

    attendant_entry.bind("<Return>", submit_login)

    tk.Button(login_win, text="Login", command=submit_login).pack(pady=15)

    login_win.mainloop()


# ------------------- Main window -------------------
def build_main_window():
    global window, tree, right_frame, name_entry, age_entry
    global ticket_tree, passenger_var, passenger_dropdown
    global destination_var, date_var, seat_value_label, price_value_label
    global student_var, pwd_var

    window = tk.Tk()
    window.title("Passenger & Attendant Ticketing System")

    try:
        logo_icon = tk.PhotoImage(file="logo.png")
        window.iconphoto(True, logo_icon)
    except tk.TclError:
        pass

    window.geometry("1300x420")

    tk.Label(
        window, text=f"Logged in as: {CURRENT_ATTENDANT}",
        font=("Arial", 9, "italic"), anchor="e"
    ).pack(fill=tk.X, padx=10, pady=(5, 0))

    notebook = ttk.Notebook(window)
    notebook.pack(fill=tk.BOTH, expand=True)

    # ===================== Passengers Tab =====================
    passenger_tab = tk.Frame(notebook)
    notebook.add(passenger_tab, text="Passengers")

    left_frame = tk.Frame(passenger_tab)
    left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

    tk.Label(left_frame, text="Passenger List", font=("Arial", 12, "bold")).pack()

    columns = ("id", "name", "age")
    tree = ttk.Treeview(left_frame, columns=columns, show="headings")
    tree.heading("id", text="ID")
    tree.heading("name", text="Name")
    tree.heading("age", text="Age")
    tree.column("id", width=40)
    tree.column("name", width=150)
    tree.column("age", width=60)
    tree.pack(fill=tk.BOTH, expand=True)

    tk.Button(
        left_frame,
        text="Delete Selected",
        command=delete_passenger,
        bg="#d69b95",
        fg="white"
    ).pack(pady=10)

    right_frame = tk.Frame(passenger_tab)
    right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=20, pady=10)

    tk.Label(right_frame, text="Passenger Name").pack()
    name_entry = tk.Entry(right_frame)
    name_entry.pack()

    tk.Label(right_frame, text="Age").pack()
    age_entry = tk.Entry(right_frame)
    age_entry.pack()

    tk.Button(
        right_frame,
        text="Add Passenger",
        command=add_passenger
    ).pack(pady=20)

    # ===================== Tickets Tab =====================
    ticket_tab = tk.Frame(notebook)
    notebook.add(ticket_tab, text="Tickets")

    ticket_left_frame = tk.Frame(ticket_tab)
    ticket_left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

    tk.Label(ticket_left_frame, text="Ticket List", font=("Arial", 12, "bold")).pack()

    ticket_columns = ("id", "passenger", "destination", "seat", "date", "base_price", "discount", "final_price", "attendant")
    ticket_tree = ttk.Treeview(ticket_left_frame, columns=ticket_columns, show="headings")
    ticket_tree.heading("id", text="Ticket ID")
    ticket_tree.heading("passenger", text="Passenger")
    ticket_tree.heading("destination", text="Destination")
    ticket_tree.heading("seat", text="Seat")
    ticket_tree.heading("date", text="Date")
    ticket_tree.heading("base_price", text="Base Price")
    ticket_tree.heading("discount", text="Discount")
    ticket_tree.heading("final_price", text="Final Price")
    ticket_tree.heading("attendant", text="Booked By")
    ticket_tree.column("id", width=55)
    ticket_tree.column("passenger", width=100)
    ticket_tree.column("destination", width=90)
    ticket_tree.column("seat", width=45)
    ticket_tree.column("date", width=80)
    ticket_tree.column("base_price", width=70)
    ticket_tree.column("discount", width=100)
    ticket_tree.column("final_price", width=70)
    ticket_tree.column("attendant", width=100)
    ticket_tree.pack(fill=tk.BOTH, expand=True)

    tk.Button(
        ticket_left_frame,
        text="Delete Selected",
        command=delete_ticket,
        bg="#d69b95",
        fg="white"
    ).pack(pady=10)

    ticket_right_frame = tk.Frame(ticket_tab)
    ticket_right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=20, pady=10)

    tk.Label(ticket_right_frame, text="Passenger").pack()
    passenger_var = tk.StringVar()
    passenger_dropdown = ttk.Combobox(ticket_right_frame, textvariable=passenger_var, state="readonly")
    passenger_dropdown.pack()

    tk.Label(ticket_right_frame, text="Destination").pack()
    destination_var = tk.StringVar()
    destination_dropdown = ttk.Combobox(
        ticket_right_frame, textvariable=destination_var,
        values=list(ROUTES.keys()), state="readonly"
    )
    destination_dropdown.pack()

    tk.Label(ticket_right_frame, text="Travel Date").pack()
    date_var = tk.StringVar()
    date_dropdown = ttk.Combobox(
        ticket_right_frame, textvariable=date_var,
        values=generate_dates(), state="readonly"
    )
    date_dropdown.pack()

    tk.Label(ticket_right_frame, text="Seat (auto-assigned)").pack(pady=(10, 0))
    seat_value_label = tk.Label(ticket_right_frame, text="--", font=("Arial", 10, "bold"))
    seat_value_label.pack()

    tk.Label(ticket_right_frame, text="Price").pack(pady=(10, 0))
    price_value_label = tk.Label(ticket_right_frame, text="--", font=("Arial", 10, "bold"))
    price_value_label.pack()

    student_var = tk.BooleanVar()
    pwd_var = tk.BooleanVar()

    tk.Checkbutton(
        ticket_right_frame, text="Student", variable=student_var, command=update_auto_fields
    ).pack(pady=(15, 0))

    tk.Checkbutton(
        ticket_right_frame, text="PWD", variable=pwd_var, command=update_auto_fields
    ).pack()

    tk.Label(
        ticket_right_frame,
        text="(Minors under 18 get the discount\nautomatically based on age on file)",
        font=("Arial", 8), fg="gray"
    ).pack(pady=(5, 0))

    tk.Button(
        ticket_right_frame,
        text="Book Ticket",
        command=add_ticket
    ).pack(pady=20)

    # React to dropdown/passenger changes to recompute seat + price
    passenger_var.trace_add("write", update_auto_fields)
    destination_var.trace_add("write", update_auto_fields)
    date_var.trace_add("write", update_auto_fields)

    refresh_list()
    refresh_ticket_list()
    window.mainloop()

    # Close database when the main window closes
    conn.close()


# ------------------- App entry point -------------------
show_login_screen()
