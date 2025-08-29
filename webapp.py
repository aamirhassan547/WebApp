from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, flash
import pyodbc
from azure.storage.blob import BlobServiceClient
import os
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import json
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from textblob import TextBlob
import cv2
import tempfile

app = Flask(__name__)
app.secret_key = 'b9e4f7a1c02d8e93f67a4c5d2e8ab91ff4763a6d85c24550'

AZURE_SQL_SERVER = "aamir.database.windows.net"
AZURE_SQL_DATABASE = "data123"
AZURE_SQL_USERNAME = "aamir12345"
AZURE_SQL_PASSWORD = "aamir@20072"

AZURE_STORAGE_CONNECTION_STRING = "DefaultEndpointsProtocol=https;AccountName=aamir12345;AccountKey=5lqeDkF5M0rotcjPMLXPPD6ZCzV/5Li98b9W2LHR1Flup+6OCnCAxosnWN3M6py5RjgYe2ctv/PQ+AStCl+m+A==;EndpointSuffix=core.windows.net"
AZURE_STORAGE_CONTAINER = "storage"


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, user_type):
        self.id = id
        self.username = username
        self.user_type = user_type

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, user_type FROM users WHERE id = ?", user_id)
    user_data = cursor.fetchone()
    conn.close()
    if user_data:
        return User(user_data[0], user_data[1], user_data[2])
    return None

def get_db_connection():
    connection_string = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={AZURE_SQL_SERVER};DATABASE={AZURE_SQL_DATABASE};UID={AZURE_SQL_USERNAME};PWD={AZURE_SQL_PASSWORD}'
    return pyodbc.connect(connection_string)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='users' AND xtype='U')
        CREATE TABLE users (
            id INT IDENTITY(1,1) PRIMARY KEY,
            username NVARCHAR(50) UNIQUE NOT NULL,
            email NVARCHAR(100) UNIQUE NOT NULL,
            password_hash NVARCHAR(255) NOT NULL,
            user_type NVARCHAR(10) NOT NULL,
            created_at DATETIME DEFAULT GETDATE()
        )
    ''')

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='videos' AND xtype='U')
        CREATE TABLE videos (
            id INT IDENTITY(1,1) PRIMARY KEY,
            title NVARCHAR(200) NOT NULL,
            publisher NVARCHAR(100) NOT NULL,
            producer NVARCHAR(100) NOT NULL,
            genre NVARCHAR(50) NOT NULL,
            age_rating NVARCHAR(10) NOT NULL,
            video_url NVARCHAR(500) NOT NULL,
            thumbnail_url NVARCHAR(500),
            creator_id INT NOT NULL,
            created_at DATETIME DEFAULT GETDATE(),
            FOREIGN KEY (creator_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ratings' AND xtype='U')
        CREATE TABLE ratings (
            id INT IDENTITY(1,1) PRIMARY KEY,
            video_id INT NOT NULL,
            user_id INT NOT NULL,
            rating INT NOT NULL,
            created_at DATETIME DEFAULT GETDATE(),
            FOREIGN KEY (video_id) REFERENCES videos(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='comments' AND xtype='U')
        CREATE TABLE comments (
            id INT IDENTITY(1,1) PRIMARY KEY,
            video_id INT NOT NULL,
            user_id INT NOT NULL,
            comment NVARCHAR(500) NOT NULL,
            sentiment NVARCHAR(10),
            created_at DATETIME DEFAULT GETDATE(),
            FOREIGN KEY (video_id) REFERENCES videos(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    conn.commit()
    conn.close()

blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)

@app.route('/')
def home():
    return render_template_string(HOME_TEMPLATE)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        user_type = request.form['user_type']

        password_hash = generate_password_hash(password)

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, user_type) VALUES (?, ?, ?, ?)",
                username, email, password_hash, user_type
            )
            conn.commit()
            conn.close()
            flash('Registration successful!', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Username or email already exists!', 'error')

    return render_template_string(REGISTER_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password_hash, user_type FROM users WHERE username = ?", username)
        user_data = cursor.fetchone()
        conn.close()

        if user_data and check_password_hash(user_data[2], password):
            user = User(user_data[0], user_data[1], user_data[3])
            login_user(user)
            if user.user_type == 'creator':
                return redirect(url_for('creator_dashboard'))
            else:
                return redirect(url_for('consumer_dashboard'))
        else:
            flash('Invalid credentials!', 'error')

    return render_template_string(LOGIN_TEMPLATE)

@app.route('/creator-dashboard')
@login_required
def creator_dashboard():
    if current_user.user_type != 'creator':
        return redirect(url_for('login'))
    return render_template_string(CREATOR_DASHBOARD_TEMPLATE)

@app.route('/consumer-dashboard')
@login_required
def consumer_dashboard():
    if current_user.user_type != 'consumer':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT v.id,
                          v.title,
                          v.publisher,
                          v.producer,
                          v.genre,
                          v.age_rating,
                          v.video_url,
                          AVG(CAST(r.rating AS FLOAT)) as avg_rating,
                          v.thumbnail_url
                   FROM videos v
                   LEFT JOIN ratings r ON v.id = r.video_id
                   GROUP BY v.id, v.title, v.publisher, v.producer, v.genre, v.age_rating, v.video_url, v.created_at, v.thumbnail_url
                   ORDER BY v.created_at DESC
                   ''')
    videos = cursor.fetchall()

    # Fetch user ratings
    user_ratings = {}
    cursor.execute('''
        SELECT video_id, rating
        FROM ratings
        WHERE user_id = ?
    ''', current_user.id)
    for row in cursor.fetchall():
        user_ratings[row[0]] = row[1]

    # Fetch comments
    comments_dict = {}
    cursor.execute('''
        SELECT c.video_id, u.username, c.comment, c.created_at, c.sentiment
        FROM comments c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.created_at DESC
    ''')
    all_comments = cursor.fetchall()
    for comment in all_comments:
        vid = comment[0]
        if vid not in comments_dict:
            comments_dict[vid] = []
        comments_dict[vid].append({
            'username': comment[1],
            'comment': comment[2],
            'created_at': comment[3].strftime('%Y-%m-%d %H:%M:%S'),
            'sentiment': comment[4]
        })

    conn.close()

    return render_template_string(CONSUMER_DASHBOARD_TEMPLATE, videos=videos, user_ratings=user_ratings, comments=comments_dict)

@app.route('/upload-video', methods=['POST'])
@login_required
def upload_video():
    if current_user.user_type != 'creator':
        return redirect(url_for('login'))

    title = request.form['title']
    publisher = request.form['publisher']
    producer = request.form['producer']
    genre = request.form['genre']
    age_rating = request.form['age_rating']
    video_file = request.files['video']

    if video_file:
        filename = secure_filename(video_file.filename)
        blob_name = f"{uuid.uuid4()}_{filename}"

        try:
            # Save video to temp file
            with tempfile.NamedTemporaryFile(delete=False) as temp_video:
                video_file.save(temp_video.name)
                temp_video_path = temp_video.name

            # Upload video
            blob_client = blob_service_client.get_blob_client(
                container=AZURE_STORAGE_CONTAINER,
                blob=blob_name
            )
            with open(temp_video_path, "rb") as f:
                blob_client.upload_blob(f, overwrite=True)
            video_url = blob_client.url

            # Generate thumbnail
            thumbnail_url = None
            cap = cv2.VideoCapture(temp_video_path)
            success, frame = cap.read()
            if success:
                thumbnail_blob_name = f"{uuid.uuid4()}_thumb.jpg"
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_thumb:
                    cv2.imwrite(temp_thumb.name, frame)
                    temp_thumb_path = temp_thumb.name

                blob_client_thumb = blob_service_client.get_blob_client(
                    container=AZURE_STORAGE_CONTAINER,
                    blob=thumbnail_blob_name
                )
                with open(temp_thumb_path, "rb") as f:
                    blob_client_thumb.upload_blob(f, overwrite=True)
                thumbnail_url = blob_client_thumb.url

                os.unlink(temp_thumb_path)

            cap.release()
            os.unlink(temp_video_path)

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO videos (title, publisher, producer, genre, age_rating, video_url, thumbnail_url, creator_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                title, publisher, producer, genre, age_rating, video_url, thumbnail_url, current_user.id
            )
            conn.commit()
            conn.close()

            flash('Video uploaded successfully!', 'success')
        except Exception as e:
            flash(f'Upload failed: {str(e)}', 'error')

    return redirect(url_for('creator_dashboard'))

@app.route('/rate-video', methods=['POST'])
@login_required
def rate_video():
    if current_user.user_type != 'consumer':
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    video_id = data['video_id']
    rating = data['rating']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM ratings WHERE video_id = ? AND user_id = ?", video_id, current_user.id)
    existing = cursor.fetchone()

    if existing:
        cursor.execute("UPDATE ratings SET rating = ? WHERE video_id = ? AND user_id = ?",
                       rating, video_id, current_user.id)
    else:
        cursor.execute("INSERT INTO ratings (video_id, user_id, rating) VALUES (?, ?, ?)",
                       video_id, current_user.id, rating)

    conn.commit()

    # Fetch new average
    cursor.execute("SELECT AVG(CAST(rating AS FLOAT)) FROM ratings WHERE video_id = ?", video_id)
    new_avg = cursor.fetchone()[0]

    conn.close()

    return jsonify({'success': True, 'avg_rating': new_avg})

@app.route('/add-comment', methods=['POST'])
@login_required
def add_comment():
    if current_user.user_type != 'consumer':
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    video_id = data['video_id']
    comment_text = data['comment']

    # Perform sentiment analysis
    blob = TextBlob(comment_text)
    polarity = blob.sentiment.polarity
    if polarity > 0:
        sentiment = 'positive'
    elif polarity < 0:
        sentiment = 'negative'
    else:
        sentiment = 'neutral'

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO comments (video_id, user_id, comment, sentiment) VALUES (?, ?, ?, ?)",
                   video_id, current_user.id, comment_text, sentiment)
    conn.commit()
    conn.close()

    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return jsonify({'success': True, 'comment': {'username': current_user.username, 'comment': comment_text, 'created_at': created_at, 'sentiment': sentiment}})

@app.route('/search-videos')
@login_required
def search_videos():
    query = request.args.get('q', '')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
                   SELECT v.id,
                          v.title,
                          v.publisher,
                          v.producer,
                          v.genre,
                          v.age_rating,
                          v.video_url,
                          AVG(CAST(r.rating AS FLOAT)) as avg_rating,
                          v.thumbnail_url
                   FROM videos v
                            LEFT JOIN ratings r ON v.id = r.video_id
                   WHERE v.title LIKE ?
                      OR v.genre LIKE ?
                      OR v.publisher LIKE ?
                   GROUP BY v.id, v.title, v.publisher, v.producer, v.genre, v.age_rating, v.video_url, v.thumbnail_url
                   ''', f'%{query}%', f'%{query}%', f'%{query}%')
    videos = cursor.fetchall()

    video_list = [{
        'id': v[0], 'title': v[1], 'publisher': v[2], 'producer': v[3],
        'genre': v[4], 'age_rating': v[5], 'video_url': v[6], 'avg_rating': v[7], 'thumbnail_url': v[8]
    } for v in videos]

    # Fetch user ratings
    user_ratings = {}
    cursor.execute('''
        SELECT video_id, rating
        FROM ratings
        WHERE user_id = ?
    ''', current_user.id)
    for row in cursor.fetchall():
        user_ratings[row[0]] = row[1]

    for video in video_list:
        video['user_rating'] = user_ratings.get(video['id'], 0)

    # Fetch comments
    comments_dict = {}
    if video_list:
        video_ids = [v['id'] for v in video_list]
        placeholders = ','.join(['?'] * len(video_ids))
        cursor.execute(f'''
            SELECT c.video_id, u.username, c.comment, c.created_at, c.sentiment
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.video_id IN ({placeholders})
            ORDER BY c.created_at DESC
        ''', video_ids)
        all_comments = cursor.fetchall()
        for comment in all_comments:
            vid = comment[0]
            if vid not in comments_dict:
                comments_dict[vid] = []
            comments_dict[vid].append({
                'username': comment[1],
                'comment': comment[2],
                'created_at': comment[3].strftime('%Y-%m-%d %H:%M:%S'),
                'sentiment': comment[4]
            })

    for video in video_list:
        video['comments'] = comments_dict.get(video['id'], [])

    conn.close()

    return jsonify(video_list)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


HOME_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VidStream - Next-Gen Video Platform</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #0a0a0a 0%, #1a1a1a 100%);
            color: #ffffff;
            overflow-x: hidden;
        }

        .floating-nav {
            position: fixed;
            top: 2rem;
            right: 2rem;
            z-index: 1000;
            display: flex;
            gap: 1rem;
        }

        .nav-bubble {
            padding: 0.8rem 1.5rem;
            background: rgba(34, 197, 94, 0.2);
            backdrop-filter: blur(20px);
            border: 1px solid #22c55e;
            border-radius: 50px;
            color: #22c55e;
            text-decoration: none;
            font-weight: 600;
            transition: all 0.3s ease;
            font-size: 0.9rem;
        }

        .nav-bubble:hover {
            background: #22c55e;
            color: #000;
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(34, 197, 94, 0.3);
        }

        .hero-container {
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            position: relative;
            padding: 2rem;
        }

        .animated-bg {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: radial-gradient(circle at 20% 50%, rgba(34, 197, 94, 0.1) 0%, transparent 50%),
                        radial-gradient(circle at 80% 20%, rgba(34, 197, 94, 0.08) 0%, transparent 50%),
                        radial-gradient(circle at 40% 80%, rgba(34, 197, 94, 0.06) 0%, transparent 50%);
            animation: pulse 4s ease-in-out infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }

        .brand-logo {
            font-size: 5rem;
            font-weight: 900;
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 1rem;
            text-align: center;
            letter-spacing: -3px;
        }

        .hero-tagline {
            font-size: 1.5rem;
            color: #a3a3a3;
            text-align: center;
            margin-bottom: 3rem;
            max-width: 600px;
            line-height: 1.4;
        }

        .cta-group {
            display: flex;
            gap: 1.5rem;
            margin-bottom: 4rem;
        }

        .cta-primary {
            padding: 1rem 2.5rem;
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            color: #000;
            text-decoration: none;
            border-radius: 12px;
            font-weight: 700;
            font-size: 1.1rem;
            transition: all 0.3s ease;
            border: none;
            cursor: pointer;
        }

        .cta-primary:hover {
            transform: translateY(-3px);
            box-shadow: 0 15px 40px rgba(34, 197, 94, 0.4);
        }

        .cta-secondary {
            padding: 1rem 2.5rem;
            background: transparent;
            color: #22c55e;
            text-decoration: none;
            border: 2px solid #22c55e;
            border-radius: 12px;
            font-weight: 600;
            font-size: 1.1rem;
            transition: all 0.3s ease;
        }

        .cta-secondary:hover {
            background: rgba(34, 197, 94, 0.1);
            transform: translateY(-3px);
        }

        .features-showcase {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 2rem;
            max-width: 1000px;
            margin: 0 auto;
        }

        .feature-box {
            background: rgba(255, 255, 255, 0.02);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(34, 197, 94, 0.2);
            border-radius: 16px;
            padding: 2rem;
            text-align: center;
            transition: all 0.3s ease;
        }

        .feature-box:hover {
            border-color: #22c55e;
            transform: translateY(-5px);
            background: rgba(34, 197, 94, 0.05);
        }

        .feature-icon {
            width: 60px;
            height: 60px;
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 1.5rem;
            font-size: 1.5rem;
            font-weight: bold;
            color: #000;
        }

        .feature-title {
            font-size: 1.2rem;
            font-weight: 700;
            color: #22c55e;
            margin-bottom: 1rem;
        }

        .feature-description {
            color: #a3a3a3;
            line-height: 1.5;
            font-size: 0.95rem;
        }

        .bottom-section {
            background: #000;
            padding: 3rem 0;
            text-align: center;
            border-top: 1px solid #22c55e;
        }

        .copyright {
            color: #22c55e;
            font-weight: 500;
        }

        @media (max-width: 768px) {
            .floating-nav {
                position: relative;
                top: 1rem;
                right: 0;
                justify-content: center;
            }

            .brand-logo {
                font-size: 3rem;
            }

            .hero-tagline {
                font-size: 1.2rem;
            }

            .cta-group {
                flex-direction: column;
                align-items: center;
            }

            .features-showcase {
                grid-template-columns: 1fr;
                gap: 1.5rem;
            }
        }
    </style>
</head>
<body>
    <div class="floating-nav">
        <a href="{{ url_for('login') }}" class="nav-bubble">Enter Platform</a>
        <a href="{{ url_for('register') }}" class="nav-bubble">Join Community</a>
    </div>

    <div class="hero-container">
        <div class="animated-bg"></div>

        <div class="brand-logo">VidStream</div>
        <p class="hero-tagline">Revolutionary video streaming experience. Upload, discover, and engage with premium content in an immersive digital environment.</p>

        <div class="cta-group">
            <a href="{{ url_for('register') }}" class="cta-primary">Start Streaming</a>
            <a href="{{ url_for('login') }}" class="cta-secondary">Access Portal</a>
        </div>

        <div class="features-showcase">
            <div class="feature-box">
                <div class="feature-icon">⚡</div>
                <div class="feature-title">Lightning Upload</div>
                <div class="feature-description">Ultra-fast video processing with advanced compression technology</div>
            </div>
            <div class="feature-box">
                <div class="feature-icon">🎯</div>
                <div class="feature-title">Smart Discovery</div>
                <div class="feature-description">AI-powered content recommendation engine for personalized viewing</div>
            </div>
            <div class="feature-box">
                <div class="feature-icon">💬</div>
                <div class="feature-title">Interactive Hub</div>
                <div class="feature-description">Real-time engagement with sentiment analysis and community features</div>
            </div>
        </div>
    </div>

    <div class="bottom-section">
        <p class="copyright">© 2024 VidStream. Next-generation streaming platform.</p>
    </div>
</body>
</html>
'''

REGISTER_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VidStream - Create Account</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', sans-serif;
            background: #000;
            color: #fff;
            min-height: 100vh;
            display: grid;
            grid-template-columns: 1fr 1fr;
        }

        .visual-panel {
            background: linear-gradient(45deg, #16a34a 0%, #22c55e 50%, #15803d 100%);
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            padding: 3rem;
            position: relative;
            overflow: hidden;
        }

        .visual-panel::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="2" fill="rgba(0,0,0,0.1)"/></svg>') repeat;
            opacity: 0.3;
        }

        .brand-display {
            font-size: 4rem;
            font-weight: 900;
            color: #000;
            margin-bottom: 2rem;
            z-index: 1;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
        }

        .welcome-text {
            font-size: 1.3rem;
            color: #000;
            text-align: center;
            max-width: 400px;
            line-height: 1.5;
            z-index: 1;
            margin-bottom: 3rem;
            font-weight: 500;
        }

        .stats-display {
            display: flex;
            gap: 3rem;
            z-index: 1;
        }

        .stat-item {
            text-align: center;
        }

        .stat-number {
            font-size: 2.5rem;
            font-weight: 900;
            color: #000;
            display: block;
        }

        .stat-label {
            font-size: 0.9rem;
            color: rgba(0,0,0,0.7);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .form-panel {
            background: #0a0a0a;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 2rem;
        }

        .registration-form {
            background: #1a1a1a;
            padding: 3rem;
            border-radius: 20px;
            border: 1px solid #22c55e;
            width: 100%;
            max-width: 450px;
            box-shadow: 0 20px 60px rgba(34, 197, 94, 0.1);
        }

        .form-header {
            text-align: center;
            margin-bottom: 2.5rem;
        }

        .form-title {
            font-size: 2.2rem;
            font-weight: 800;
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }

        .form-subtitle {
            color: #a3a3a3;
            font-size: 1rem;
        }

        .notification {
            padding: 1rem;
            border-radius: 10px;
            margin-bottom: 2rem;
            font-size: 0.9rem;
            font-weight: 500;
        }

        .notification-success {
            background: rgba(34, 197, 94, 0.1);
            border: 1px solid #22c55e;
            color: #22c55e;
        }

        .notification-error {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid #ef4444;
            color: #ef4444;
        }

        .input-container {
            margin-bottom: 1.8rem;
        }

        .input-label {
            display: block;
            margin-bottom: 0.6rem;
            color: #22c55e;
            font-weight: 600;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .form-input {
            width: 100%;
            padding: 1rem;
            background: #0a0a0a;
            border: 2px solid #333;
            border-radius: 10px;
            color: #fff;
            font-size: 1rem;
            transition: all 0.3s ease;
        }

        .form-input:focus {
            outline: none;
            border-color: #22c55e;
            box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.1);
            background: #111;
        }

        .role-selector {
            margin-bottom: 2rem;
        }

        .role-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
            margin-top: 0.6rem;
        }

        .role-option {
            position: relative;
        }

        .role-input {
            display: none;
        }

        .role-label {
            display: block;
            padding: 1.2rem;
            background: #0a0a0a;
            border: 2px solid #333;
            border-radius: 10px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s ease;
            font-weight: 600;
            color: #a3a3a3;
        }

        .role-input:checked + .role-label {
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            border-color: #22c55e;
            color: #000;
            transform: scale(1.02);
        }

        .role-label:hover {
            border-color: #22c55e;
            background: rgba(34, 197, 94, 0.05);
        }

        .submit-button {
            width: 100%;
            padding: 1.2rem;
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            color: #000;
            border: none;
            border-radius: 10px;
            font-size: 1.1rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s ease;
            margin-bottom: 2rem;
        }

        .submit-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(34, 197, 94, 0.3);
        }

        .form-footer {
            text-align: center;
            padding-top: 1.5rem;
            border-top: 1px solid #333;
        }

        .footer-link {
            color: #22c55e;
            text-decoration: none;
            font-weight: 600;
            transition: color 0.3s ease;
        }

        .footer-link:hover {
            color: #16a34a;
        }

        @media (max-width: 768px) {
            body {
                grid-template-columns: 1fr;
                grid-template-rows: auto 1fr;
            }

            .visual-panel {
                padding: 2rem;
                min-height: 300px;
            }

            .brand-display {
                font-size: 2.5rem;
            }

            .stats-display {
                gap: 2rem;
            }

            .registration-form {
                margin: 0;
                padding: 2rem;
            }
        }
    </style>
</head>
<body>
    <div class="visual-panel">
        <div class="brand-display">VidStream</div>
        <p class="welcome-text">Join thousands of creators and viewers in the ultimate streaming community. Your journey starts here.</p>
        <div class="stats-display">
            <div class="stat-item">
                <span class="stat-number">2.5K+</span>
                <span class="stat-label">Creators</span>
            </div>
            <div class="stat-item">
                <span class="stat-number">15K+</span>
                <span class="stat-label">Videos</span>
            </div>
            <div class="stat-item">
                <span class="stat-number">50K+</span>
                <span class="stat-label">Community</span>
            </div>
        </div>
    </div>

    <div class="form-panel">
        <div class="registration-form">
            <div class="form-header">
                <h1 class="form-title">Create Account</h1>
                <p class="form-subtitle">Build your streaming presence</p>
            </div>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="notification notification-{{ category }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <form method="POST">
                <div class="input-container">
                    <label for="username" class="input-label">Username</label>
                    <input type="text" id="username" name="username" class="form-input" required>
                </div>

                <div class="input-container">
                    <label for="email" class="input-label">Email</label>
                    <input type="email" id="email" name="email" class="form-input" required>
                </div>

                <div class="input-container">
                    <label for="password" class="input-label">Password</label>
                    <input type="password" id="password" name="password" class="form-input" required>
                </div>

                <div class="role-selector">
                    <label class="input-label">Select Role</label>
                    <div class="role-grid">
                        <div class="role-option">
                            <input type="radio" id="creator" name="user_type" value="creator" class="role-input" required>
                            <label for="creator" class="role-label">Creator</label>
                        </div>
                        <div class="role-option">
                            <input type="radio" id="consumer" name="user_type" value="consumer" class="role-input" required>
                            <label for="consumer" class="role-label">Viewer</label>
                        </div>
                    </div>
                </div>

                <button type="submit" class="submit-button">Launch Account</button>
            </form>

            <div class="form-footer">
                <a href="{{ url_for('home') }}" class="footer-link">← Return to Home</a>
            </div>
        </div>
    </div>
</body>
</html>
'''

LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VidStream - Access Portal</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', sans-serif;
            background: radial-gradient(ellipse at center, #1a1a1a 0%, #000000 100%);
            color: #fff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
            overflow: hidden;
        }

        .bg-pattern {
            position: absolute;
            width: 200%;
            height: 200%;
            background: repeating-linear-gradient(
                45deg,
                transparent,
                transparent 50px,
                rgba(34, 197, 94, 0.03) 50px,
                rgba(34, 197, 94, 0.03) 100px
            );
            animation: slide 20s linear infinite;
        }

        @keyframes slide {
            0% { transform: translate(-50%, -50%); }
            100% { transform: translate(-48%, -48%); }
        }

        .login-wrapper {
            background: rgba(26, 26, 26, 0.95);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(34, 197, 94, 0.3);
            border-radius: 24px;
            padding: 0;
            width: 90%;
            max-width: 900px;
            display: grid;
            grid-template-columns: 1fr 1fr;
            overflow: hidden;
            box-shadow: 0 30px 80px rgba(0, 0, 0, 0.5);
            z-index: 1;
        }

        .branding-side {
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            padding: 4rem 3rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            position: relative;
        }

        .branding-side::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(45deg, transparent 30%, rgba(0,0,0,0.1) 50%, transparent 70%);
        }

        .logo-symbol {
            width: 100px;
            height: 100px;
            background: #000;
            border-radius: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2.5rem;
            font-weight: 900;
            color: #22c55e;
            margin-bottom: 2rem;
            z-index: 1;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }

        .brand-name {
            font-size: 3rem;
            font-weight: 900;
            color: #000;
            margin-bottom: 1rem;
            z-index: 1;
            letter-spacing: -2px;
        }

        .brand-tagline {
            font-size: 1.1rem;
            color: rgba(0,0,0,0.8);
            line-height: 1.5;
            z-index: 1;
            font-weight: 500;
        }

        .form-side {
            padding: 4rem 3rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }

        .form-header {
            margin-bottom: 3rem;
        }

        .form-title {
            font-size: 2.5rem;
            font-weight: 800;
            color: #22c55e;
            margin-bottom: 0.5rem;
            letter-spacing: -1px;
        }

        .form-subtitle {
            color: #a3a3a3;
            font-size: 1.1rem;
            font-weight: 400;
        }

        .notification {
            padding: 1rem 1.2rem;
            border-radius: 12px;
            margin-bottom: 2rem;
            font-size: 0.9rem;
            font-weight: 500;
        }

        .notification-success {
            background: rgba(34, 197, 94, 0.15);
            border: 1px solid rgba(34, 197, 94, 0.5);
            color: #22c55e;
        }

        .notification-error {
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.5);
            color: #ef4444;
        }

        .field-group {
            margin-bottom: 2rem;
            position: relative;
        }

        .field-label {
            display: block;
            color: #22c55e;
            font-weight: 700;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 0.8rem;
        }

        .field-input {
            width: 100%;
            padding: 1.2rem 1rem;
            background: rgba(0, 0, 0, 0.4);
            border: 2px solid rgba(34, 197, 94, 0.2);
            border-radius: 12px;
            color: #fff;
            font-size: 1.1rem;
            transition: all 0.3s ease;
        }

        .field-input:focus {
            outline: none;
            border-color: #22c55e;
            background: rgba(0, 0, 0, 0.6);
            box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.1);
        }

        .access-button {
            width: 100%;
            padding: 1.3rem;
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            color: #000;
            border: none;
            border-radius: 12px;
            font-size: 1.2rem;
            font-weight: 800;
            cursor: pointer;
            transition: all 0.3s ease;
            margin: 2rem 0;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .access-button:hover {
            transform: translateY(-3px);
            box-shadow: 0 15px 40px rgba(34, 197, 94, 0.4);
        }

        .form-navigation {
            text-align: center;
            padding-top: 2rem;
            border-top: 1px solid rgba(34, 197, 94, 0.2);
        }

        .nav-link {
            color: #a3a3a3;
            text-decoration: none;
            font-weight: 500;
            transition: color 0.3s ease;
        }

        .nav-link:hover {
            color: #22c55e;
        }

        @media (max-width: 768px) {
            .login-wrapper {
                grid-template-columns: 1fr;
                width: 95%;
                max-width: 400px;
            }

            .branding-side {
                padding: 2rem;
                order: 2;
            }

            .brand-name {
                font-size: 2rem;
            }

            .logo-symbol {
                width: 70px;
                height: 70px;
                font-size: 1.8rem;
            }

            .form-side {
                padding: 3rem 2rem;
            }

            .form-title {
                font-size: 2rem;
            }
        }
    </style>
</head>
<body>
    <div class="bg-pattern"></div>

    <div class="login-wrapper">
        <div class="branding-side">
            <div class="logo-symbol">V</div>
            <div class="brand-name">VidStream</div>
            <p class="brand-tagline">Your gateway to the ultimate streaming experience. Connect, create, and discover amazing content.</p>
        </div>

        <div class="form-side">
            <div class="form-header">
                <h1 class="form-title">Access Portal</h1>
                <p class="form-subtitle">Enter your credentials to continue</p>
            </div>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="notification notification-{{ category }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <form method="POST">
                <div class="field-group">
                    <label for="username" class="field-label">Username</label>
                    <input type="text" id="username" name="username" class="field-input" required>
                </div>

                <div class="field-group">
                    <label for="password" class="field-label">Password</label>
                    <input type="password" id="password" name="password" class="field-input" required>
                </div>

                <button type="submit" class="access-button">Enter Platform</button>
            </form>

            <div class="form-navigation">
                <a href="{{ url_for('home') }}" class="nav-link">← Back to Homepage</a>
            </div>
        </div>
    </div>
</body>
</html>
'''

CREATOR_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VidStream - Creator Studio</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', sans-serif;
            background: linear-gradient(135deg, #000 0%, #0f0f0f 100%);
            color: #fff;
            min-height: 100vh;
        }

        .control-bar {
            background: rgba(34, 197, 94, 0.1);
            backdrop-filter: blur(20px);
            border-bottom: 2px solid #22c55e;
            padding: 1.5rem 3rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .studio-brand {
            font-size: 1.8rem;
            font-weight: 900;
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .user-controls {
            display: flex;
            align-items: center;
            gap: 2rem;
        }

        .creator-badge {
            padding: 0.6rem 1.2rem;
            background: rgba(34, 197, 94, 0.2);
            border: 1px solid #22c55e;
            border-radius: 25px;
            color: #22c55e;
            font-weight: 700;
            font-size: 0.9rem;
        }

        .exit-btn {
            padding: 0.7rem 1.5rem;
            background: transparent;
            border: 2px solid #ef4444;
            color: #ef4444;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .exit-btn:hover {
            background: #ef4444;
            color: #000;
        }

        .studio-workspace {
            max-width: 1000px;
            margin: 0 auto;
            padding: 4rem 2rem;
        }

        .upload-station {
            background: linear-gradient(135deg, #1a1a1a 0%, #0f0f0f 100%);
            border: 2px solid #22c55e;
            border-radius: 24px;
            padding: 4rem;
            box-shadow: 0 20px 60px rgba(34, 197, 94, 0.1);
            position: relative;
            overflow: hidden;
        }

        .upload-station::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: radial-gradient(circle at 30% 20%, rgba(34, 197, 94, 0.05) 0%, transparent 50%);
            pointer-events: none;
        }

        .station-header {
            text-align: center;
            margin-bottom: 4rem;
            position: relative;
        }

        .station-title {
            font-size: 3rem;
            font-weight: 900;
            color: #22c55e;
            margin-bottom: 1rem;
            letter-spacing: -2px;
        }

        .station-subtitle {
            font-size: 1.2rem;
            color: #a3a3a3;
            font-weight: 400;
        }

        .notification {
            padding: 1.2rem 1.5rem;
            border-radius: 12px;
            margin-bottom: 3rem;
            font-size: 1rem;
            font-weight: 600;
        }

        .notification-success {
            background: rgba(34, 197, 94, 0.15);
            border: 1px solid #22c55e;
            color: #22c55e;
        }

        .notification-error {
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid #ef4444;
            color: #ef4444;
        }

        .upload-form {
            position: relative;
        }

        .form-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 2rem;
            margin-bottom: 3rem;
        }

        .field-container {
            display: flex;
            flex-direction: column;
        }

        .field-container.full-span {
            grid-column: 1 / -1;
        }

        .field-title {
            color: #22c55e;
            font-weight: 800;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            margin-bottom: 0.8rem;
        }

        .field-input, .field-select {
            padding: 1.2rem;
            background: rgba(0, 0, 0, 0.6);
            border: 2px solid rgba(34, 197, 94, 0.3);
            border-radius: 12px;
            color: #fff;
            font-size: 1rem;
            font-weight: 500;
            transition: all 0.3s ease;
        }

        .field-input:focus, .field-select:focus {
            outline: none;
            border-color: #22c55e;
            background: rgba(0, 0, 0, 0.8);
            box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.1);
        }

        .drop-zone {
            border: 3px dashed rgba(34, 197, 94, 0.5);
            border-radius: 16px;
            padding: 5rem 3rem;
            text-align: center;
            background: rgba(34, 197, 94, 0.03);
            cursor: pointer;
            transition: all 0.4s ease;
            margin-bottom: 3rem;
            position: relative;
        }

        .drop-zone:hover, .drop-zone.drag-active {
            border-color: #22c55e;
            background: rgba(34, 197, 94, 0.08);
            transform: scale(1.01);
        }

        .drop-icon {
            font-size: 4rem;
            color: #22c55e;
            margin-bottom: 1.5rem;
            display: block;
        }

        .drop-title {
            font-size: 1.4rem;
            font-weight: 700;
            color: #22c55e;
            margin-bottom: 0.8rem;
        }

        .drop-subtitle {
            font-size: 1rem;
            color: #a3a3a3;
            font-weight: 500;
        }

        .file-display {
            background: rgba(34, 197, 94, 0.1);
            border: 2px solid #22c55e;
            border-radius: 12px;
            padding: 1.5rem;
            margin: 2rem 0;
            display: none;
            color: #22c55e;
            font-weight: 600;
        }

        .upload-progress {
            margin: 3rem 0;
            display: none;
        }

        .progress-title {
            font-size: 1rem;
            color: #22c55e;
            font-weight: 700;
            margin-bottom: 1rem;
        }

        .progress-track {
            width: 100%;
            height: 12px;
            background: rgba(34, 197, 94, 0.2);
            border-radius: 6px;
            overflow: hidden;
        }

        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, #22c55e 0%, #16a34a 100%);
            width: 0%;
            transition: width 0.3s ease;
            border-radius: 6px;
        }

        .launch-button {
            width: 100%;
            padding: 1.5rem;
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            color: #000;
            border: none;
            border-radius: 12px;
            font-size: 1.3rem;
            font-weight: 900;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 2px;
        }

        .launch-button:hover {
            transform: translateY(-3px);
            box-shadow: 0 15px 40px rgba(34, 197, 94, 0.4);
        }

        .launch-button:disabled {
            background: #333;
            color: #666;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }

        #videoFile {
            display: none;
        }

        @media (max-width: 768px) {
            .control-bar {
                padding: 1rem;
                flex-direction: column;
                gap: 1rem;
            }

            .studio-workspace {
                padding: 2rem 1rem;
            }

            .upload-station {
                padding: 2rem;
            }

            .station-title {
                font-size: 2rem;
            }

            .form-grid {
                grid-template-columns: 1fr;
                gap: 1.5rem;
            }

            .drop-zone {
                padding: 3rem 2rem;
            }
        }
    </style>
</head>
<body>
    <div class="control-bar">
        <div class="studio-brand">Creator Studio</div>
        <div class="user-controls">
            <span class="creator-badge">{{ current_user.username }}</span>
            <a href="{{ url_for('logout') }}" class="exit-btn">Exit Studio</a>
        </div>
    </div>

    <div class="studio-workspace">
        <div class="upload-station">
            <div class="station-header">
                <h1 class="station-title">Launch Content</h1>
                <p class="station-subtitle">Upload your video and reach your audience instantly</p>
            </div>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="notification notification-{{ category }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <form method="POST" action="{{ url_for('upload_video') }}" enctype="multipart/form-data" id="contentForm">
                <div class="form-grid">
                    <div class="field-container">
                        <label for="title" class="field-title">Content Title</label>
                        <input type="text" id="title" name="title" class="field-input" required>
                    </div>
                    <div class="field-container">
                        <label for="publisher" class="field-title">Publisher</label>
                        <input type="text" id="publisher" name="publisher" class="field-input" required>
                    </div>
                    <div class="field-container">
                        <label for="producer" class="field-title">Producer</label>
                        <input type="text" id="producer" name="producer" class="field-input" required>
                    </div>
                    <div class="field-container">
                        <label for="genre" class="field-title">Category</label>
                        <select id="genre" name="genre" class="field-select" required>
                            <option value="">Select Category</option>
                            <option value="Action">Action</option>
                            <option value="Comedy">Comedy</option>
                            <option value="Drama">Drama</option>
                            <option value="Horror">Horror</option>
                            <option value="Romance">Romance</option>
                            <option value="Sci-Fi">Sci-Fi</option>
                            <option value="Documentary">Documentary</option>
                            <option value="Animation">Animation</option>
                            <option value="Thriller">Thriller</option>
                            <option value="Adventure">Adventure</option>
                        </select>
                    </div>
                    <div class="field-container full-span">
                        <label for="age_rating" class="field-title">Content Rating</label>
                        <select id="age_rating" name="age_rating" class="field-select" required>
                            <option value="">Select Rating</option>
                            <option value="G">G - General Audiences</option>
                            <option value="PG">PG - Parental Guidance</option>
                            <option value="PG-13">PG-13 - Parents Strongly Cautioned</option>
                            <option value="R">R - Restricted</option>
                            <option value="NC-17">NC-17 - Adults Only</option>
                            <option value="18">18+ - Adult Content</option>
                        </select>
                    </div>
                </div>

                <div class="drop-zone" onclick="document.getElementById('videoFile').click()">
                    <span class="drop-icon">🎬</span>
                    <div class="drop-title">Select Video File</div>
                    <div class="drop-subtitle">Click here or drag and drop your video</div>
                </div>

                <input type="file" id="videoFile" name="video" accept="video/*" required>
                <div class="file-display" id="fileDisplay"></div>

                <div class="upload-progress" id="uploadProgress">
                    <div class="progress-title">Processing Upload...</div>
                    <div class="progress-track">
                        <div class="progress-bar" id="progressBar"></div>
                    </div>
                </div>

                <button type="submit" class="launch-button" id="launchBtn">Launch Content</button>
            </form>
        </div>
    </div>

    <script>
        const videoFile = document.getElementById('videoFile');
        const dropZone = document.querySelector('.drop-zone');
        const fileDisplay = document.getElementById('fileDisplay');
        const contentForm = document.getElementById('contentForm');
        const uploadProgress = document.getElementById('uploadProgress');
        const progressBar = document.getElementById('progressBar');
        const launchBtn = document.getElementById('launchBtn');

        videoFile.addEventListener('change', handleFileSelection);

        function handleFileSelection(event) {
            const file = event.target.files[0];
            if (file) {
                fileDisplay.style.display = 'block';
                fileDisplay.innerHTML = `
                    <strong>Ready to Launch:</strong> ${file.name}<br>
                    <strong>Size:</strong> ${(file.size / 1024 / 1024).toFixed(2)} MB<br>
                    <strong>Format:</strong> ${file.type}
                `;
                dropZone.style.borderColor = '#22c55e';
                dropZone.querySelector('.drop-title').textContent = 'Video Selected';
                dropZone.querySelector('.drop-subtitle').textContent = 'Ready for upload';
            }
        }

        // Drag and drop functionality
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => dropZone.classList.add('drag-active'), false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => dropZone.classList.remove('drag-active'), false);
        });

        dropZone.addEventListener('drop', handleDrop, false);

        function handleDrop(e) {
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                videoFile.files = files;
                handleFileSelection({ target: { files } });
            }
        }

        contentForm.addEventListener('submit', function(e) {
            launchBtn.textContent = 'LAUNCHING...';
            launchBtn.disabled = true;
            uploadProgress.style.display = 'block';

            let progress = 0;
            const interval = setInterval(() => {
                progress += Math.random() * 12;
                if (progress > 85) progress = 85;
                progressBar.style.width = progress + '%';
            }, 400);

            setTimeout(() => {
                clearInterval(interval);
                progressBar.style.width = '100%';
            }, 3500);
        });
    </script>
</body>
</html>
'''

CONSUMER_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VidStream - Content Hub</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', sans-serif;
            background: linear-gradient(to bottom, #000 0%, #0a0a0a 100%);
            color: #fff;
            line-height: 1.6;
        }

        .top-navigation {
            background: rgba(0, 0, 0, 0.95);
            backdrop-filter: blur(20px);
            border-bottom: 3px solid #22c55e;
            padding: 1.5rem 0;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 5px 30px rgba(34, 197, 94, 0.2);
        }

        .nav-container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 3rem;
            display: grid;
            grid-template-columns: auto 1fr auto;
            align-items: center;
            gap: 3rem;
        }

        .platform-logo {
            font-size: 2rem;
            font-weight: 900;
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .search-zone {
            position: relative;
            max-width: 600px;
            width: 100%;
        }

        .search-field {
            width: 100%;
            padding: 1rem 1.5rem;
            padding-right: 4rem;
            background: rgba(34, 197, 94, 0.1);
            border: 2px solid rgba(34, 197, 94, 0.3);
            border-radius: 50px;
            color: #fff;
            font-size: 1rem;
            font-weight: 500;
            outline: none;
            transition: all 0.3s ease;
        }

        .search-field:focus {
            border-color: #22c55e;
            background: rgba(34, 197, 94, 0.15);
            box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.1);
        }

        .search-field::placeholder {
            color: #a3a3a3;
        }

        .search-trigger {
            position: absolute;
            right: 8px;
            top: 50%;
            transform: translateY(-50%);
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            color: #000;
            border: none;
            padding: 0.7rem 1.5rem;
            border-radius: 50px;
            cursor: pointer;
            font-weight: 700;
            transition: all 0.3s ease;
        }

        .search-trigger:hover {
            transform: translateY(-50%) scale(1.05);
        }

        .user-panel {
            display: flex;
            align-items: center;
            gap: 2rem;
        }

        .user-display {
            padding: 0.8rem 1.5rem;
            background: rgba(34, 197, 94, 0.2);
            border: 1px solid rgba(34, 197, 94, 0.5);
            border-radius: 25px;
            color: #22c55e;
            font-weight: 700;
        }

        .logout-control {
            padding: 0.8rem 1.5rem;
            background: transparent;
            border: 2px solid #ef4444;
            color: #ef4444;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .logout-control:hover {
            background: #ef4444;
            color: #000;
        }

        .content-area {
            max-width: 1400px;
            margin: 0 auto;
            padding: 4rem 3rem;
        }

        .area-header {
            font-size: 3.5rem;
            font-weight: 900;
            color: #22c55e;
            margin-bottom: 4rem;
            text-align: center;
            letter-spacing: -2px;
        }

        .video-showcase {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(450px, 1fr));
            gap: 3rem;
        }

        .content-card {
            background: linear-gradient(135deg, #1a1a1a 0%, #0f0f0f 100%);
            border: 2px solid rgba(34, 197, 94, 0.3);
            border-radius: 20px;
            overflow: hidden;
            transition: all 0.4s ease;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
        }

        .content-card:hover {
            transform: translateY(-8px);
            border-color: #22c55e;
            box-shadow: 0 20px 60px rgba(34, 197, 94, 0.2);
        }

        .card-title {
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            color: #000;
            padding: 1.5rem 2rem;
            font-weight: 800;
            font-size: 1.3rem;
            letter-spacing: -0.5px;
        }

        .card-details {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
            padding: 2rem;
            background: rgba(34, 197, 94, 0.03);
            border-bottom: 1px solid rgba(34, 197, 94, 0.1);
        }

        .detail-block {
            font-size: 0.95rem;
        }

        .detail-key {
            color: #22c55e;
            font-weight: 700;
            display: block;
            margin-bottom: 0.3rem;
            text-transform: uppercase;
            font-size: 0.8rem;
            letter-spacing: 1px;
        }

        .detail-value {
            color: #e5e5e5;
            font-weight: 500;
        }

        .video-display {
            width: 100%;
            height: 280px;
            background: #000;
            border: none;
        }

        .engagement-area {
            padding: 2rem;
            background: rgba(0, 0, 0, 0.4);
        }

        .rating-section {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid rgba(34, 197, 94, 0.2);
        }

        .star-controls {
            display: flex;
            gap: 0.5rem;
        }

        .rating-star {
            font-size: 1.8rem;
            color: rgba(34, 197, 94, 0.3);
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .rating-star:hover,
        .rating-star.selected {
            color: #22c55e;
            transform: scale(1.1);
        }

        .rating-display {
            color: #a3a3a3;
            font-weight: 600;
            font-size: 1rem;
        }

        .comment-area textarea {
            width: 100%;
            padding: 1.2rem;
            background: rgba(0, 0, 0, 0.6);
            border: 2px solid rgba(34, 197, 94, 0.3);
            border-radius: 12px;
            color: #fff;
            font-family: inherit;
            font-size: 1rem;
            resize: vertical;
            min-height: 100px;
            margin-bottom: 1.5rem;
            transition: all 0.3s ease;
        }

        .comment-area textarea:focus {
            outline: none;
            border-color: #22c55e;
            background: rgba(0, 0, 0, 0.8);
        }

        .comment-area textarea::placeholder {
            color: #666;
        }

        .submit-comment {
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            color: #000;
            border: none;
            padding: 0.8rem 2rem;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 700;
            transition: all 0.3s ease;
        }

        .submit-comment:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(34, 197, 94, 0.3);
        }

        .comments-display {
            margin-top: 2rem;
            max-height: 250px;
            overflow-y: auto;
        }

        .comment-item {
            padding: 1.5rem 0;
            border-bottom: 1px solid rgba(34, 197, 94, 0.1);
        }

        .comment-item:last-child {
            border-bottom: none;
        }

        .comment-user {
            font-weight: 700;
            color: #22c55e;
            margin-bottom: 0.5rem;
            font-size: 1rem;
        }

        .comment-content {
            color: #e5e5e5;
            margin-bottom: 0.8rem;
            line-height: 1.5;
        }

        .comment-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.85rem;
            color: #666;
        }

        .sentiment-tag {
            padding: 0.3rem 0.8rem;
            border-radius: 15px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .sentiment-positive {
            background: rgba(34, 197, 94, 0.2);
            color: #22c55e;
        }

        .sentiment-negative {
            background: rgba(239, 68, 68, 0.2);
            color: #ef4444;
        }

        .sentiment-neutral {
            background: rgba(156, 163, 175, 0.2);
            color: #9ca3af;
        }

        .no-content {
            text-align: center;
            padding: 5rem 3rem;
            background: rgba(34, 197, 94, 0.05);
            border: 2px dashed rgba(34, 197, 94, 0.3);
            border-radius: 20px;
            margin-top: 3rem;
        }

        .no-content h3 {
            font-size: 2rem;
            font-weight: 700;
            color: #22c55e;
            margin-bottom: 1rem;
        }

        .no-content p {
            color: #a3a3a3;
            font-size: 1.1rem;
        }

        @media (max-width: 768px) {
            .nav-container {
                grid-template-columns: 1fr;
                gap: 1.5rem;
                padding: 0 1rem;
            }

            .content-area {
                padding: 2rem 1rem;
            }

            .area-header {
                font-size: 2.5rem;
            }

            .video-showcase {
                grid-template-columns: 1fr;
                gap: 2rem;
            }

            .card-details {
                grid-template-columns: 1fr;
                gap: 1rem;
            }
        }
    </style>
</head>
<body>
    <div class="top-navigation">
        <div class="nav-container">
            <div class="platform-logo">VidStream</div>
            <div class="search-zone">
                <input type="text" class="search-field" id="searchField" placeholder="Discover amazing content...">
                <button class="search-trigger" onclick="performSearch()">Find</button>
            </div>
            <div class="user-panel">
                <span class="user-display">{{ current_user.username }}</span>
                <a href="{{ url_for('logout') }}" class="logout-control">Exit</a>
            </div>
        </div>
    </div>

    <div class="content-area">
        <h1 class="area-header">Content Hub</h1>

        <div class="video-showcase" id="videoShowcase">
            {% if videos %}
                {% for video in videos %}
                <div class="content-card">
                    <div class="card-title">{{ video[1] }}</div>

                    <div class="card-details">
                        <div class="detail-block">
                            <span class="detail-key">Publisher</span>
                            <span class="detail-value">{{ video[2] }}</span>
                        </div>
                        <div class="detail-block">
                            <span class="detail-key">Producer</span>
                            <span class="detail-value">{{ video[3] }}</span>
                        </div>
                        <div class="detail-block">
                            <span class="detail-key">Genre</span>
                            <span class="detail-value">{{ video[4] }}</span>
                        </div>
                        <div class="detail-block">
                            <span class="detail-key">Rating</span>
                            <span class="detail-value">{{ video[5] }}</span>
                        </div>
                    </div>

                    <video class="video-display" controls>
                        <source src="{{ video[6] }}" type="video/mp4">
                        Your browser does not support video playback.
                    </video>

                    <div class="engagement-area">
                        <div class="rating-section">
                            <div class="star-controls" data-video-id="{{ video[0] }}">
                                {% set user_rating = user_ratings.get(video[0], 0) %}
                                {% for i in range(1, 6) %}
                                <span class="rating-star {% if i <= user_rating %}selected{% endif %}" data-rating="{{ i }}">★</span>
                                {% endfor %}
                            </div>
                            <div class="rating-display">
                                {% if video[7] %}
                                    Average: {{ "%.1f"|format(video[7]) }}/5
                                {% else %}
                                    No ratings yet
                                {% endif %}
                            </div>
                        </div>

                        <div class="comment-area">
                            <textarea placeholder="Share your thoughts about this content..." data-video-id="{{ video[0] }}"></textarea>
                            <button class="submit-comment" onclick="submitComment({{ video[0] }})">Post Comment</button>

                            <div class="comments-display">
                                {% if comments[video[0]] %}
                                    {% for comment in comments[video[0]] %}
                                    <div class="comment-item">
                                        <div class="comment-user">{{ comment.username }}</div>
                                        <div class="comment-content">{{ comment.comment }}</div>
                                        <div class="comment-footer">
                                            <span>{{ comment.created_at }}</span>
                                            <span class="sentiment-tag sentiment-{{ comment.sentiment }}">
                                                {{ comment.sentiment }}
                                            </span>
                                        </div>
                                    </div>
                                    {% endfor %}
                                {% else %}
                                    <div class="comment-item">
                                        <div class="comment-content">No comments yet. Be the first to share your thoughts!</div>
                                    </div>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <div class="no-content">
                    <h3>No Videos Available</h3>
                    <p>Check back later for amazing new content uploads.</p>
                </div>
            {% endif %}
        </div>
    </div>

    <script>
        // Rating functionality
        document.querySelectorAll('.star-controls').forEach(starGroup => {
            const stars = starGroup.querySelectorAll('.rating-star');
            const videoId = starGroup.dataset.videoId;

            stars.forEach((star, index) => {
                star.addEventListener('click', () => {
                    const ratingValue = index + 1;

                    fetch('/rate-video', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            video_id: videoId,
                            rating: ratingValue
                        })
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            stars.forEach((s, i) => {
                                s.classList.toggle('selected', i < ratingValue);
                            });

                            const ratingDisplay = starGroup.closest('.rating-section').querySelector('.rating-display');
                            ratingDisplay.textContent = data.avg_rating ? 
                                `Average: ${data.avg_rating.toFixed(1)}/5` : 'No ratings yet';
                        }
                    })
                    .catch(error => console.error('Rating error:', error));
                });

                star.addEventListener('mouseenter', () => {
                    stars.forEach((s, i) => {
                        s.style.color = i <= index ? '#22c55e' : 'rgba(34, 197, 94, 0.3)';
                    });
                });

                starGroup.addEventListener('mouseleave', () => {
                    stars.forEach(s => {
                        s.style.color = s.classList.contains('selected') ? '#22c55e' : 'rgba(34, 197, 94, 0.3)';
                    });
                });
            });
        });

        // Comment functionality
        function submitComment(videoId) {
            const textarea = document.querySelector(`textarea[data-video-id="${videoId}"]`);
            const comment = textarea.value.trim();

            if (!comment) return;

            fetch('/add-comment', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    video_id: videoId,
                    comment: comment
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const commentsDisplay = textarea.closest('.comment-area').querySelector('.comments-display');

                    const newComment = document.createElement('div');
                    newComment.className = 'comment-item';
                    newComment.innerHTML = `
                        <div class="comment-user">${data.comment.username}</div>
                        <div class="comment-content">${data.comment.comment}</div>
                        <div class="comment-footer">
                            <span>${data.comment.created_at}</span>
                            <span class="sentiment-tag sentiment-${data.comment.sentiment}">
                                ${data.comment.sentiment}
                            </span>
                        </div>
                    `;

                    commentsDisplay.insertBefore(newComment, commentsDisplay.firstChild);
                    textarea.value = '';
                }
            })
            .catch(error => console.error('Comment error:', error));
        }

        // Search functionality
        function performSearch() {
            const query = document.getElementById('searchField').value.trim();
            if (!query) {
                location.reload();
                return;
            }

            fetch(`/search-videos?q=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(videos => {
                    const videoShowcase = document.getElementById('videoShowcase');

                    if (videos.length === 0) {
                        videoShowcase.innerHTML = `
                            <div class="no-content">
                                <h3>No Results Found</h3>
                                <p>Try searching with different keywords for amazing content.</p>
                            </div>
                        `;
                        return;
                    }

                    videoShowcase.innerHTML = videos.map(video => `
                        <div class="content-card">
                            <div class="card-title">${video.title}</div>

                            <div class="card-details">
                                <div class="detail-block">
                                    <span class="detail-key">Publisher</span>
                                    <span class="detail-value">${video.publisher}</span>
                                </div>
                                <div class="detail-block">
                                    <span class="detail-key">Producer</span>
                                    <span class="detail-value">${video.producer}</span>
                                </div>
                                <div class="detail-block">
                                    <span class="detail-key">Genre</span>
                                    <span class="detail-value">${video.genre}</span>
                                </div>
                                <div class="detail-block">
                                    <span class="detail-key">Rating</span>
                                    <span class="detail-value">${video.age_rating}</span>
                                </div>
                            </div>

                            <video class="video-display" controls>
                                <source src="${video.video_url}" type="video/mp4">
                                Your browser does not support video playback.
                            </video>

                            <div class="engagement-area">
                                <div class="rating-section">
                                    <div class="star-controls" data-video-id="${video.id}">
                                        ${[1,2,3,4,5].map(i => 
                                            `<span class="rating-star ${i <= (video.user_rating || 0) ? 'selected' : ''}" data-rating="${i}">★</span>`
                                        ).join('')}
                                    </div>
                                    <div class="rating-display">
                                        ${video.avg_rating ? `Average: ${video.avg_rating.toFixed(1)}/5` : 'No ratings yet'}
                                    </div>
                                </div>

                                <div class="comment-area">
                                    <textarea placeholder="Share your thoughts about this content..." data-video-id="${video.id}"></textarea>
                                    <button class="submit-comment" onclick="submitComment(${video.id})">Post Comment</button>

                                    <div class="comments-display">
                                        ${video.comments.map(comment => `
                                            <div class="comment-item">
                                                <div class="comment-user">${comment.username}</div>
                                                <div class="comment-content">${comment.comment}</div>
                                                <div class="comment-footer">
                                                    <span>${comment.created_at}</span>
                                                    <span class="sentiment-tag sentiment-${comment.sentiment}">
                                                        ${comment.sentiment}
                                                    </span>
                                                </div>
                                            </div>
                                        `).join('') || '<div class="comment-item"><div class="comment-content">No comments yet. Be the first to share your thoughts!</div></div>'}
                                    </div>
                                </div>
                            </div>
                        </div>
                    `).join('');

                    // Re-initialize event listeners
                    initializeRatingListeners();
                })
                .catch(error => console.error('Search error:', error));
        }

        function initializeRatingListeners() {
            document.querySelectorAll('.star-controls').forEach(starGroup => {
                const stars = starGroup.querySelectorAll('.rating-star');
                const videoId = starGroup.dataset.videoId;

                stars.forEach((star, index) => {
                    star.addEventListener('click', () => {
                        const ratingValue = index + 1;

                        fetch('/rate-video', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                video_id: videoId,
                                rating: ratingValue
                            })
                        })
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                stars.forEach((s, i) => {
                                    s.classList.toggle('selected', i < ratingValue);
                                });

                                const ratingDisplay = starGroup.closest('.rating-section').querySelector('.rating-display');
                                ratingDisplay.textContent = data.avg_rating ? 
                                    `Average: ${data.avg_rating.toFixed(1)}/5` : 'No ratings yet';
                            }
                        })
                        .catch(error => console.error('Rating error:', error));
                    });

                    star.addEventListener('mouseenter', () => {
                        stars.forEach((s, i) => {
                            s.style.color = i <= index ? '#22c55e' : 'rgba(34, 197, 94, 0.3)';
                        });
                    });

                    starGroup.addEventListener('mouseleave', () => {
                        stars.forEach(s => {
                            s.style.color = s.classList.contains('selected') ? '#22c55e' : 'rgba(34, 197, 94, 0.3)';
                        });
                    });
                });
            });
        }

        // Search on Enter key
        document.getElementById('searchField').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                performSearch();
            }
        });
    </script>
</body>
</html>
'''
init_db()
if __name__ == '__main__':

    app.run(debug=True, host='0.0.0.0', port=5000)