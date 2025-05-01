from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from mysql.connector import connect
from google.cloud import storage
import os

# Load environment variables
load_dotenv()
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Google Cloud Storage client
GCS_BUCKET = os.getenv("GCS_BUCKET_NAME")
storage_client = storage.Client()

# Database configuration
db_kwargs = {
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "database": os.getenv("DB_NAME")
}

def get_db():
    return connect(**db_kwargs)

@app.route('/')
def index():
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, name FROM Sections")
    sections = cur.fetchall()
    cur.close(); conn.close()
    return render_template('index.html', sections=sections)

@app.route('/section/<int:section_id>')
def section(section_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, name FROM Categories WHERE section_id=%s", (section_id,))
    categories = cur.fetchall()
    cur.close(); conn.close()
    return render_template('section.html', section_id=section_id, categories=categories)

@app.route('/category/<int:category_id>')
def category(category_id):
    conn = get_db(); cur = conn.cursor(dictionary=True)
    # grab the category name AND its section_id
    cur.execute("SELECT name, section_id FROM Categories WHERE id=%s", (category_id,))
    cat = cur.fetchone()
    table = cat['name'].lower().replace(' ', '_')
    cur.execute(f"SELECT * FROM {table} WHERE category_id=%s", (category_id,))
    rows = cur.fetchall()
    # Generate signed URLs for images
    for row in rows:
        blob = storage_client.bucket(GCS_BUCKET).blob(row['image_url'])
        row['image_url'] = blob.generate_signed_url(version='v4', expiration=3600, method='GET')
    cur.close(); conn.close()
    return render_template('category.html', category=cat['name'], listings=rows, section_id=cat['section_id'])

@app.route('/create/<int:category_id>', methods=['GET', 'POST'])
def create_listing(category_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT name FROM Categories WHERE id=%s", (category_id,))
    cat_name = cur.fetchone()[0]
    table = cat_name.lower().replace(' ', '_')

    if request.method == 'POST':
        # Handle image file
        image = request.files.get('image')
        if not image or image.filename == '':
            flash('Image is required.', 'error')
            return redirect(request.url)
        filename = secure_filename(image.filename)
        bucket = storage_client.bucket(GCS_BUCKET)
        blob = bucket.blob(filename)
        blob.upload_from_file(image)
        # Collect form fields
        data = request.form.to_dict()
        if any(v.strip() == '' for v in data.values()):
            flash('All fields are required.', 'error')
            return redirect(request.url)
        cols = ', '.join(['category_id', 'image_url'] + list(data.keys()))
        vals = [category_id, filename] + list(data.values())
        placeholders = ', '.join(['%s'] * len(vals))
        cur.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", vals)
        conn.commit(); cur.close(); conn.close()
        flash('Listing created!', 'success')
        return redirect(url_for('category', category_id=category_id))

    # GET: render form
    cur.execute(f"SHOW COLUMNS FROM {table}")
    raw_cols = cur.fetchall()  
# raw_cols is a list of tuples: (Field, Type, Null, Key, Default, Extra)
    columns = [
        {"name": row[0], "type": row[1]} 
        for row in raw_cols 
        if row[0] not in ('id','category_id','image_url')
    ]
    return render_template('create_listing.html', category=cat_name, columns=columns )

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user = request.form['username']; pwd = request.form['password']
        hashed = generate_password_hash(pwd)
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO Users(username,password) VALUES(%s,%s)", (user, hashed))
        conn.commit(); c.close(); conn.close()
        flash('Registered! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form['username']; pwd = request.form['password']
        conn = get_db(); c = conn.cursor(dictionary=True)
        c.execute("SELECT id,password FROM Users WHERE username=%s", (user,))
        row = c.fetchone(); c.close(); conn.close()
        if row and check_password_hash(row['password'], pwd):
            session['user_id'] = row['id']
            flash('Welcome back!', 'success')
            return redirect(url_for('index'))
        flash('Invalid credentials.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)