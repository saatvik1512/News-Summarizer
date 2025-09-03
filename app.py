from newsapi import NewsApiClient
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash
import os
from flask_migrate import Migrate
from datetime import datetime
from dateutil import parser
from services.sentiment_analyzer import SentimentAnalyzer

load_dotenv()
newsapi = NewsApiClient(api_key=os.getenv('NEWS_API_KEY'))
# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = '11223344'  # Change to a strong secret key
if 'DATABASE_URL' in os.environ:
    # For Render's PostgreSQL (replace postgres:// with postgresql://)
    database_url = os.environ['DATABASE_URL']
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # For local development
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
# SQLite database
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'  # Redirect to login page for protected routes


# Load CSV data
summaries_df = pd.read_csv("summaries_with_sentiment.csv")

# User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    summary_id = db.Column(db.Integer, nullable=False)  # Assuming each summary has a unique ID
    comment_text = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer, nullable=True)  # Optional
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)

    user = db.relationship('User', backref=db.backref('comments', lazy=True))


# Add below the Comment model
class SavedArticle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    article_id = db.Column(db.String(255), nullable=False)  # NewsAPI's unique ID
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    url = db.Column(db.String(500))
    source = db.Column(db.String(150))
    published_at = db.Column(db.DateTime)
    added_at = db.Column(db.DateTime, default=db.func.now())
    sentiment = db.Column(db.String(20), default='neutral')  # Add default
    confidence = db.Column(db.Float, default=0.0) 

    user = db.relationship('User', backref=db.backref('articles', lazy=True))

migrate = Migrate(app, db)

def safe_parse_iso(date_str):
    try:
        return parser.isoparse(date_str)
    except:
        return datetime.now(datetime.timezone.utc)


# Load user callback
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Homepage route to display all summaries
@app.route('/')
@login_required
def home():
    data = summaries_df.to_dict(orient='records')
    return render_template('index.html', data=data, username=current_user.username)

# Search route to display filtered summaries
@app.route('/search', methods=['GET'])
@login_required
def search_summaries():
    query = request.args.get('query')
    if query:
        filtered_df = summaries_df[summaries_df['title'].str.contains(query, case=False) |
                                   summaries_df['summary'].str.contains(query, case=False)]
        data = filtered_df.to_dict(orient='records')
    else:
        data = []
    return render_template('search.html', data=data, query=query)

# Registration route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # Corrected hashing method
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful! Please log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Fetch the user from the database
        user = User.query.filter_by(username=username).first()

        # Validate credentials
        if user and check_password_hash(user.password, password):
            login_user(user)  # Log the user in
            flash('Login successful!', 'success')
            
            # Redirect to dashboard
            return redirect(url_for('personal_feed'))

        flash('Invalid username or password', 'danger')
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    
    username = current_user.username
    summaries_df['id'] = summaries_df.index
    data = summaries_df.to_dict(orient='records')  # Load summaries from the CSV
    
    # Load comments for each summary
    comments = Comment.query.all()
    comments_by_summary = {}
    for comment in comments:
        comments_by_summary.setdefault(comment.summary_id, []).append({
            'username': comment.user.username,
            'comment': comment.comment_text,
            'rating': comment.rating,
            'timestamp': comment.timestamp
        })
    
    return render_template('dashboard.html', data=data, username=username, comments=comments_by_summary)




# Logout route
@app.route('/logout')
def logout():
    session.clear()  # Clear the session
    logout_user()
    return redirect(url_for('login'))



@app.route('/add_comment/<int:summary_id>', methods=['POST'])
@login_required
def add_comment(summary_id):
    comment_text = request.form['comment']
    rating = int(request.form['rating'])

    # Add the comment to the database
    new_comment = Comment(summary_id=summary_id, user_id=current_user.id, comment_text=comment_text, rating=rating)
    db.session.add(new_comment)
    db.session.commit()

    flash('Comment added successfully!')
    return redirect(url_for('dashboard'))


# new routes to be added
# Add these routes below existing ones

@app.route('/news/search')
@login_required
def news_search():
    query = request.args.get('q', '')
    if query:
        try:
            results = newsapi.get_everything(
                q=query,
                language='en',
                sort_by='relevancy',
                page_size=20
            )
            articles = results['articles']
        except Exception as e:
            flash('Error fetching news articles', 'danger')
            articles = []
    else:
        articles = []
    return render_template('news_search.html', articles=articles, query=query)

# @app.route('/save_article', methods=['POST'])
# @login_required
# def save_article():
#     try:
#         # Convert ISO string to datetime object
#         # published_at = datetime.fromisoformat(
#         #     request.form['published_at'].replace('Z', '+00:00')
#         # )
#         published_at = safe_parse_iso(request.form['published_at'])
#     except Exception as e:
#         published_at = datetime.now(datetime.timezone.utc) # Fallback to current time

#     article_data = {
#         'article_id': request.form['url'][-15:],  # Simple unique ID from URL
#         'title': request.form['title'],
#         'description': request.form['description'],
#         'url': request.form['url'],
#         'source': request.form['source'],
#         'published_at': published_at  # Now using datetime object
#     }

#     analyzer = SentimentAnalyzer()
#     text_to_analyze = f"{article_data['title']} {article_data['description']}"
#     sentiment = analyzer.analyze(text_to_analyze)
#     article_data.update({
#         'sentiment': sentiment['sentiment'],
#         'confidence': sentiment['confidence']
#     })
    
#     # Rest of the code remains the same
#     existing = SavedArticle.query.filter_by(
#         user_id=current_user.id,
#         article_id=article_data['article_id']
#     ).first()
    
#     if not existing:
#         new_article = SavedArticle(
#             user_id=current_user.id,
#             **article_data
#         )
#         db.session.add(new_article)
#         db.session.commit()
#         flash('Article saved to your feed!', 'success')
#     else:
#         flash('Article already in your feed', 'warning')
    
#     return redirect(url_for('news_search', q=request.form.get('query', '')))

@app.route('/save_article', methods=['POST'])
@login_required
def save_article():
    try:
        # Parse published_at date
        published_at = safe_parse_iso(request.form['published_at'])
    except Exception as e:
        published_at = datetime.now(datetime.timezone.utc)

    article_data = {
        'article_id': request.form['url'][-15:],
        'title': request.form['title'],
        'description': request.form['description'],
        'url': request.form['url'],
        'source': request.form['source'],
        'published_at': published_at
    }

    # Analyze sentiment
    try:
        analyzer = SentimentAnalyzer()
        text_to_analyze = f"{article_data['title']} {article_data['description']}"
        sentiment = analyzer.analyze(text_to_analyze)
        article_data.update({
            'sentiment': sentiment.get('sentiment', 'neutral'),
            'confidence': sentiment.get('confidence', 0.0)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Sentiment analysis failed: {str(e)}'
        }), 500

    # Check for existing article
    existing = SavedArticle.query.filter_by(
        user_id=current_user.id,
        article_id=article_data['article_id']
    ).first()

    if existing:
        return jsonify({
            'success': False,
            'message': 'Article already in your feed'
        }), 409

    try:
        new_article = SavedArticle(
            user_id=current_user.id,
            **article_data
        )
        db.session.add(new_article)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Article saved to your feed!',
            'sentiment': new_article.sentiment,
            'confidence': new_article.confidence,
            'article_id': new_article.article_id
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Database error: {str(e)}'
        }), 500

@app.route('/feed')
@login_required
def personal_feed():
    search_query = request.args.get('search', '')
    base_query = SavedArticle.query.filter_by(user_id=current_user.id)
    
    if search_query:
        # Search in title or description
        articles = base_query.filter(
            (SavedArticle.title.ilike(f'%{search_query}%')) | 
            (SavedArticle.description.ilike(f'%{search_query}%'))
        ).order_by(SavedArticle.added_at.desc()).all()
    else:
        articles = base_query.order_by(SavedArticle.added_at.desc()).all()
    
    return render_template('personal_feed.html', 
                         articles=articles,
                         search_query=search_query)

# Run the application
if __name__ == '__main__':
    app.run(debug=True)