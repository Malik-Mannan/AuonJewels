from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from functools import wraps
import mysql.connector
import os
from werkzeug.utils import secure_filename
from flask_dance.contrib.google import make_google_blueprint, google
from flask_mail import Mail, Message
from dotenv import load_dotenv
import traceback

load_dotenv()

app = Flask(__name__)
app.jinja_env.globals['enumerate'] = enumerate
app.secret_key = os.environ.get('SECRET_KEY')

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

UPLOAD_FOLDER = 'static/images'
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')

app.config['MAIL_SERVER']         = 'smtp.gmail.com'
app.config['MAIL_PORT']           = 587
app.config['MAIL_USE_TLS']        = True
app.config['MAIL_USERNAME']       = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD']       = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME')
mail = Mail(app)

google_bp = make_google_blueprint(
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    scope=["openid",
           "https://www.googleapis.com/auth/userinfo.email",
           "https://www.googleapis.com/auth/userinfo.profile"],
    redirect_to="google_callback"
)
app.register_blueprint(google_bp, url_prefix="/login")

import os
from urllib.parse import urlparse

def get_db_connection():
    try:
        mysql_url = os.getenv('mysql://root:nvubQoCrNXwICifprnragcsENtivcbJR@mysql.railway.internal:3306/malikstore')
        
        if mysql_url:
            url = urlparse(mysql_url)
            conn = mysql.connector.connect(
                host=url.hostname,
                port=url.port,
                user=url.username,
                password=url.password,
                database=url.path.strip('/'),
                connection_timeout=30
            )
        else:
            # Fallback to individual variables
            conn = mysql.connector.connect(
                host=os.getenv('mysql.railway.internal'),
                port=int(os.getenv('3306', 3306)),
                user=os.getenv('root'),
                password=os.getenv('nvubQoCrNXwICifprnragcsENtivcbJR'),
                database=os.getenv('malikstore', 'malikstore'),
                connection_timeout=30
            )
        return conn
    except Exception as e:
        print("Database Connection Error:", e)
        raise

# ══════════════════════════════════════════════
#  DECORATORS
# ══════════════════════════════════════════════
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash("Please login to access admin panel.")
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

def customer_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('customer_id'):
            flash("Please login to continue shopping.")
            return redirect(url_for('customer_login_page'))
        return f(*args, **kwargs)
    return decorated

# ══════════════════════════════════════════════
#  CUSTOMER AUTH
# ══════════════════════════════════════════════
@app.route("/customer-login")
def customer_login_page():
    if session.get('customer_id'):
        return redirect(url_for('home'))
    return render_template("customer/login.html")

@app.route("/google-callback")
def google_callback():
    if not google.authorized:
        return redirect(url_for('google.login'))
    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        flash("Failed to get info from Google. Try again.")
        return redirect(url_for('customer_login_page'))
    info      = resp.json()
    email     = info['email']
    full_name = info.get('name', '')
    google_id = info['id']
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Customers WHERE Email = %s", (email,))
    customer = cursor.fetchone()
    if not customer:
        cursor.execute("""
            INSERT INTO Customers (Full_Name, Email, Google_ID)
            VALUES (%s, %s, %s)
        """, (full_name, email, google_id))
        db.commit()
        cursor.execute("SELECT * FROM Customers WHERE Email = %s", (email,))
        customer = cursor.fetchone()
    db.close()
    session['customer_id']    = customer['ID']
    session['customer_name']  = customer['Full_Name']
    session['customer_email'] = customer['Email']
    return redirect(url_for('home'))

@app.route("/customer-logout")
def customer_logout():
    session.pop('customer_id', None)
    session.pop('customer_name', None)
    session.pop('customer_email', None)
    if 'google_oauth_token' in session:
        del session['google_oauth_token']
    return redirect(url_for('customer_login_page'))

# ══════════════════════════════════════════════
#  ADMIN AUTH
# ══════════════════════════════════════════════
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))
    error = None
    if request.method == "POST":
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            session.permanent = True
            return redirect(url_for('admin_dashboard'))
        else:
            error = "Wrong username or password."
    return render_template("admin/login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

# ══════════════════════════════════════════════
#  PUBLIC ROUTES
# ══════════════════════════════════════════════
@app.route("/")
def home():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Products")
    products = cursor.fetchall()
    db.close()
    return render_template("index.html", products=products)

@app.route("/product/<int:id>")
def product_detail(id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Products WHERE ID = %s", (id,))
    product = cursor.fetchone()
    if not product:
        db.close()
        return redirect(url_for('home'))
    cursor.execute("SELECT * FROM Products WHERE category = %s AND ID != %s LIMIT 4",
                   (product['category'], id))
    related = cursor.fetchall()
    # ── Fetch gallery images ──
    cursor.execute("SELECT * FROM product_images WHERE product_id = %s ORDER BY sort_order", (id,))
    gallery = cursor.fetchall()
    db.close()
    return render_template("product_detail.html", product=product, related=related, gallery=gallery)

@app.route("/my-orders")
@customer_login_required
def my_orders():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT o.ID, o.Total, o.Status, o.Ordered_at
        FROM orders o
        WHERE o.Customer_ID = %s
        ORDER BY o.Ordered_at DESC
    """, (session['customer_id'],))
    orders = cursor.fetchall()
    for order in orders:
        cursor.execute("""
            SELECT oi.quantity, oi.price, p.Name, p.image
            FROM order_items oi
            JOIN Products p ON oi.product_id = p.ID
            WHERE oi.order_id = %s
        """, (order['ID'],))
        order['order_items'] = cursor.fetchall()
    db.close()
    return render_template("my_orders.html", orders=orders)

# ══════════════════════════════════════════════
#  TEST EMAIL
# ══════════════════════════════════════════════
@app.route("/test-email")
def test_email():
    try:
        msg = Message(
            subject="Test — Malikstore",
            recipients=["ma.abmananaus@gmail.com"],
            body="Email is working!"
        )
        mail.send(msg)
        return "Email sent successfully!"
    except Exception as e:
        return f"Email failed: {str(e)}"

# ══════════════════════════════════════════════
#  STOCK ALERT SYSTEM
# ══════════════════════════════════════════════
def send_low_stock_alert(db, product_id, product_name, stock):
    try:
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM stock_alerts_sent WHERE product_id = %s", (product_id,))
        already_sent = cursor.fetchone()
        if already_sent:
            return

        if stock == 0:
            subject      = f"🚨 Out of Stock — {product_name}"
            badge_color  = "#e08888"
            badge_text   = "OUT OF STOCK"
            stock_display = "0 — Sold Out!"
        else:
            subject      = f"⚠ Low Stock Alert — {product_name} ({stock} left)"
            badge_color  = "#e8a84c"
            badge_text   = "LOW STOCK WARNING"
            stock_display = f"{stock} remaining"

        html_body = f"""
        <div style="background:#0a0602;padding:40px 32px;font-family:Georgia,serif;max-width:500px;margin:0 auto;">
          <div style="text-align:center;padding-bottom:20px;margin-bottom:28px;border-bottom:1px solid #c9a84c;">
            <h1 style="font-size:22px;font-weight:300;letter-spacing:6px;color:#c9a84c;text-transform:uppercase;margin:0;">Auon Store</h1>
            <p style="font-size:10px;letter-spacing:3px;color:#8a7e6a;text-transform:uppercase;margin:6px 0 0;">Admin Alert</p>
          </div>
          <p style="font-size:11px;letter-spacing:3px;color:{badge_color};text-transform:uppercase;margin-bottom:8px;">⚠ {badge_text}</p>
          <h2 style="font-size:22px;font-weight:300;color:#e8d08a;margin:0 0 20px;">Action Required!</h2>
          <div style="background:#120d04;border:1px solid #2a1f0a;padding:20px;margin-bottom:24px;">
            <table style="width:100%;border-collapse:collapse;">
              <tr>
                <td style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#8a7e6a;padding:8px 0;">Product</td>
                <td style="font-size:14px;color:#d4c9b0;text-align:right;">{product_name}</td>
              </tr>
              <tr>
                <td style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#8a7e6a;padding:8px 0;">Stock Status</td>
                <td style="font-size:20px;color:{badge_color};font-weight:300;text-align:right;">{stock_display}</td>
              </tr>
            </table>
          </div>
          <p style="font-size:13px;color:#8a7e6a;line-height:1.8;">Please restock this item soon to avoid missing orders.</p>
          <div style="text-align:center;margin-top:24px;">
            <a href="http://localhost:5000/admin/products/edit/{product_id}"
               style="display:inline-block;padding:.7rem 2rem;background:#c9a84c;color:#0a0602;font-size:.68rem;font-weight:500;letter-spacing:.15em;text-transform:uppercase;text-decoration:none;">
              Update Stock Now
            </a>
          </div>
          <p style="font-size:11px;color:#4a3e2a;text-align:center;margin-top:20px;letter-spacing:1px;">© 2026 Auon Store · Karachi</p>
        </div>
        """

        msg = Message(
            subject=subject,
            recipients=[app.config['MAIL_USERNAME']],
            html=html_body
        )
        mail.send(msg)

        cursor2 = db.cursor()
        cursor2.execute(
            "INSERT INTO stock_alerts_sent (product_id) VALUES (%s) ON DUPLICATE KEY UPDATE sent_at=NOW()",
            (product_id,)
        )
        db.commit()
        print(f"[STOCK ALERT] Sent for {product_name} — {stock} left")

    except Exception as e:
        print(f"[STOCK ALERT ERROR] {e}")

# ══════════════════════════════════════════════
#  ORDER SYSTEM
# ══════════════════════════════════════════════
@app.route("/place-order", methods=["POST"])
def place_order():
    db = None
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"success": False, "message": "No data received."}), 400

        name    = str(data.get('name',    '')).strip()
        phone   = str(data.get('phone',   '')).strip()
        email   = str(data.get('email',   '')).strip()
        address = str(data.get('address', '')).strip()
        cart    = data.get('cart', [])
        total   = data.get('total', 0)

        if not name:
            return jsonify({"success": False, "message": "Please enter your name."}), 400
        if not phone:
            return jsonify({"success": False, "message": "Please enter your phone number."}), 400
        if not email:
            return jsonify({"success": False, "message": "Please enter your email."}), 400
        if not cart:
            return jsonify({"success": False, "message": "Your cart is empty."}), 400

        db      = get_db()
        cursor  = db.cursor(dictionary=True)
        cursor2 = db.cursor()

        cursor.execute(
            "SELECT ID FROM Customers WHERE Phone=%s OR Email=%s LIMIT 1",
            (phone, email)
        )
        existing_customer = cursor.fetchone()

        if existing_customer:
            customer_id = existing_customer['ID']
            cursor2.execute(
                "UPDATE Customers SET Email=%s, Address=%s, Full_Name=%s, Phone=%s WHERE ID=%s",
                (email, address, name, phone, customer_id)
            )
            db.commit()
        else:
            cursor2.execute("""
                INSERT INTO Customers (Full_Name, Email, Phone, Address)
                VALUES (%s, %s, %s, %s)
            """, (name, email, phone, address))
            db.commit()
            customer_id = cursor2.lastrowid

        cursor2.execute("""
            INSERT INTO orders (Customer_ID, Total, Status)
            VALUES (%s, %s, 'pending')
        """, (customer_id, total))
        db.commit()
        order_id = cursor2.lastrowid

        order_items_for_email = []
        for item in cart:
            item_name = str(item.get('name', '')).strip()
            if not item_name:
                continue
            cursor.execute("SELECT ID, price FROM Products WHERE Name = %s", (item_name,))
            product = cursor.fetchone()
            if product:
                qty = int(item.get('qty', 1))
                cursor2.execute("""
                    INSERT INTO order_items (order_id, product_id, quantity, price)
                    VALUES (%s, %s, %s, %s)
                """, (order_id, product['ID'], qty, product['price']))

                # ── Auto-update stock ──
                cursor2.execute("""
                    UPDATE Products SET Stock = GREATEST(0, Stock - %s)
                    WHERE ID = %s
                """, (qty, product['ID']))
                db.commit()

                # ── Check & send low stock / out of stock alert ──
                cursor.execute("SELECT Stock, Name FROM Products WHERE ID = %s", (product['ID'],))
                updated = cursor.fetchone()
                if updated and updated['Stock'] <= 5:
                    send_low_stock_alert(db, product['ID'], updated['Name'], updated['Stock'])

                order_items_for_email.append({
                    'name':  item_name,
                    'qty':   qty,
                    'price': float(product['price'])
                })
            else:
                print(f"WARNING: Product not found in DB: '{item_name}'")

        db.commit()

        try:
            send_order_email(email, name, order_id, order_items_for_email, total, address)
        except Exception as mail_err:
            print(f"[EMAIL ERROR] Order #{order_id} saved but email failed: {mail_err}")

        return jsonify({"success": True, "order_id": order_id})

    except mysql.connector.Error as db_err:
        print(f"[DB ERROR] {db_err}")
        traceback.print_exc()
        return jsonify({"success": False,
                        "message": f"Database error: {str(db_err)}"}), 500

    except Exception as e:
        print(f"[ORDER ERROR] {e}")
        traceback.print_exc()
        return jsonify({"success": False,
                        "message": f"Server error: {str(e)}"}), 500

    finally:
        if db and db.is_connected():
            db.close()


def send_order_email(to_email, name, order_id, items, total, address):
    rows = ""
    for item in items:
        subtotal = item['qty'] * item['price']
        rows += f"""
        <tr>
          <td style="padding:12px 16px;border-bottom:1px solid #1e1508;color:#d4c9b0;font-size:14px;">{item['name']}</td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e1508;color:#d4c9b0;font-size:14px;text-align:center;">{item['qty']}</td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e1508;color:#c9a84c;font-size:14px;text-align:right;">PKR {subtotal:,.0f}</td>
        </tr>"""

    html_body = f"""
    <div style="background:#0a0602;padding:48px 32px;font-family:Georgia,serif;max-width:600px;margin:0 auto;">
      <div style="text-align:center;padding-bottom:28px;margin-bottom:36px;border-bottom:1px solid #c9a84c;">
        <h1 style="font-size:26px;font-weight:300;letter-spacing:8px;color:#c9a84c;text-transform:uppercase;margin:0;">Auon Store</h1>
        <p style="font-size:10px;letter-spacing:4px;color:#8a7e6a;text-transform:uppercase;margin:8px 0 0;">Artificial Jewellery · Karachi</p>
      </div>
      <p style="font-size:11px;letter-spacing:3px;color:#8a7e6a;text-transform:uppercase;margin-bottom:6px;">Order Confirmed ✓</p>
      <h2 style="font-size:28px;font-weight:300;color:#e8d08a;margin:0 0 12px;">Thank you, {name}!</h2>
      <p style="font-size:14px;color:#8a7e6a;line-height:1.8;margin-bottom:32px;">
        Your order <strong style="color:#c9a84c;">#{order_id}</strong> has been placed successfully.
        We will contact you shortly on your provided number to confirm delivery.
      </p>
      <div style="background:#120d04;border:1px solid #2a1f0a;margin-bottom:24px;">
        <div style="padding:14px 16px;border-bottom:1px solid #2a1f0a;">
          <p style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#8a7e6a;margin:0;">Order Summary — #{order_id}</p>
        </div>
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="background:#0a0602;">
              <th style="padding:10px 16px;font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#8a7e6a;text-align:left;font-weight:400;">Product</th>
              <th style="padding:10px 16px;font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#8a7e6a;text-align:center;font-weight:400;">Qty</th>
              <th style="padding:10px 16px;font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#8a7e6a;text-align:right;font-weight:400;">Price</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        <div style="padding:16px;border-top:1px solid #c9a84c;display:flex;justify-content:space-between;align-items:center;">
          <span style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#8a7e6a;">Total Amount</span>
          <span style="font-size:22px;font-weight:300;color:#e8d08a;">PKR {total:,.0f}</span>
        </div>
      </div>
      <div style="background:#120d04;border:1px solid #2a1f0a;padding:16px;margin-bottom:32px;">
        <p style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#8a7e6a;margin:0 0 8px;">Delivery Address</p>
        <p style="font-size:14px;color:#d4c9b0;margin:0;">{address or 'Not provided'}</p>
      </div>
      <div style="text-align:center;border-top:1px solid #1e1508;padding-top:24px;">
        <p style="font-size:12px;color:#8a7e6a;margin:0;">Questions? Contact us on WhatsApp</p>
        <p style="font-size:11px;color:#4a3e2a;margin:8px 0 0;letter-spacing:1px;">© 2026 Auon Store · Karachi</p>
      </div>
    </div>
    """

    msg = Message(
        subject=f"Order Confirmed #{order_id} — Auon Store",
        recipients=[to_email],
        html=html_body
    )
    mail.send(msg)


# ══════════════════════════════════════════════
#  ADMIN ROUTES
# ══════════════════════════════════════════════
@app.route("/admin")
@login_required
def admin_dashboard():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as total FROM Products")
    total_products = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) as total FROM Customers")
    total_customers = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) as total FROM orders")
    total_orders = cursor.fetchone()['total']
    cursor.execute("SELECT SUM(Total) as revenue FROM orders WHERE Status='delivered'")
    revenue = cursor.fetchone()['revenue'] or 0
    cursor.execute("""
        SELECT o.*, c.Full_Name, c.Phone
        FROM orders o JOIN Customers c ON o.Customer_ID = c.ID
        ORDER BY o.Ordered_at DESC LIMIT 10
    """)
    recent_orders = cursor.fetchall()
    db.close()
    return render_template("admin/dashboard.html",
        total_products=total_products,
        total_customers=total_customers,
        total_orders=total_orders,
        revenue=revenue,
        recent_orders=recent_orders)

@app.route("/admin/products")
@login_required
def admin_products():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Products ORDER BY created_at DESC")
    products = cursor.fetchall()
    db.close()
    return render_template("admin/products.html", products=products)

@app.route("/admin/products/add", methods=["GET", "POST"])
@login_required
def add_product():
    if request.method == "POST":
        image_filename = ""
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                image_filename = filename
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO Products (Name, Description, material, category, Stock, price, image)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            request.form.get('name', ''),
            request.form.get('description', ''),
            request.form.get('material', ''),
            request.form.get('category', ''),
            request.form.get('stock', 0),
            request.form.get('price', 0),
            image_filename
        ))
        db.commit()
        db.close()
        flash("Product added successfully!")
        return redirect(url_for('admin_products'))
    return render_template("admin/add_product.html")

@app.route("/admin/products/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_product(id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Products WHERE ID = %s", (id,))
    product = cursor.fetchone()
    if not product:
        db.close()
        flash("Product not found.")
        return redirect(url_for('admin_products'))

    # ── Fetch existing gallery images ──
    cursor.execute("SELECT * FROM product_images WHERE product_id = %s ORDER BY sort_order", (id,))
    gallery = cursor.fetchall()

    if request.method == "POST":
        image_filename = product['image']
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                image_filename = filename

        cursor2 = db.cursor()
        new_stock = int(request.form.get('stock', 0))
        cursor2.execute("""
            UPDATE Products
            SET Name=%s, Description=%s, material=%s, category=%s, Stock=%s, price=%s, image=%s
            WHERE ID=%s
        """, (
            request.form.get('name', ''),
            request.form.get('description', ''),
            request.form.get('material', ''),
            request.form.get('category', ''),
            new_stock,
            request.form.get('price', 0),
            image_filename,
            id
        ))

        # ── Auto-reset stock alert if restocked above 5 ──
        if new_stock > 5:
            cursor2.execute("DELETE FROM stock_alerts_sent WHERE product_id = %s", (id,))

        # ── Save gallery images (up to 3) ──
        for i in range(1, 4):
            key = f'gallery_{i}'
            if key in request.files:
                file = request.files[key]
                if file and file.filename != '':
                    filename = secure_filename(file.filename)
                    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                    file.save(os.path.join(UPLOAD_FOLDER, filename))
                    cursor.execute(
                        "SELECT ID FROM product_images WHERE product_id=%s AND sort_order=%s",
                        (id, i)
                    )
                    existing = cursor.fetchone()
                    if existing:
                        cursor2.execute(
                            "UPDATE product_images SET image=%s WHERE product_id=%s AND sort_order=%s",
                            (filename, id, i)
                        )
                    else:
                        cursor2.execute(
                            "INSERT INTO product_images (product_id, image, sort_order) VALUES (%s, %s, %s)",
                            (id, filename, i)
                        )

        db.commit()
        db.close()
        flash("Product updated successfully!")
        return redirect(url_for('admin_products'))

    db.close()
    return render_template("admin/edit_product.html", product=product, gallery=gallery)

@app.route("/admin/products/delete/<int:id>")
@login_required
def delete_product(id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM Products WHERE ID = %s", (id,))
    db.commit()
    db.close()
    flash("Product deleted!")
    return redirect(url_for('admin_products'))

@app.route("/admin/orders")
@login_required
def admin_orders():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT o.*, c.Full_Name, c.Phone, c.Email
        FROM orders o JOIN Customers c ON o.Customer_ID = c.ID
        ORDER BY o.Ordered_at DESC
    """)
    orders = cursor.fetchall()
    db.close()
    return render_template("admin/orders.html", orders=orders)

@app.route("/admin/orders/status/<int:id>", methods=["POST"])
@login_required
def update_order_status(id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE orders SET Status=%s WHERE ID=%s",
                   (request.form['status'], id))
    db.commit()
    db.close()
    return redirect(url_for('admin_orders'))

@app.route("/admin/customers")
@login_required
def admin_customers():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Customers ORDER BY created_at DESC")
    customers = cursor.fetchall()
    db.close()
    return render_template("admin/customers.html", customers=customers)

@app.route("/admin/story-images", methods=["GET", "POST"])
@login_required
def story_images():
    if request.method == "POST":
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        for section in ['earrings', 'necklaces', 'bracelets']:
            if section in request.files:
                file = request.files[section]
                if file and file.filename != '':
                    ext = file.filename.rsplit('.', 1)[-1].lower()
                    filename = f"{section}-story.{ext}"
                    file.save(os.path.join(UPLOAD_FOLDER, filename))
        flash("Story images updated!")
        return redirect(url_for('story_images'))
    return render_template("admin/story_images.html")

# ══════════════════════════════════════════════
import os

if __name__ == '__main__':
    # Railway will provide the port dynamically. If it's not there, fallback to 5000.
    port = int(os.environ.get("PORT", 5000))
    # host MUST be set to '0.0.0.0' to accept external cloud traffic
    app.run(host='0.0.0.0', port=port)