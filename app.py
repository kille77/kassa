from flask import Flask, render_template, redirect, url_for, request, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from xhtml2pdf import pisa
import io

from flask_migrate import Migrate

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://kassa_9biv_user:UNDmoxBV4Atwk1QDohC1Zs1M5XTxT8bg@dpg-cvdj108gph6c73b2gqbg-a/kassa_9biv"
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# -----------------------------
# Models
# -----------------------------
from models import User, Transaction  # Import models

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    transaction_type = db.Column(db.String(50), nullable=False)  # "withdrawal" or "deposit"
    reason = db.Column(db.String(250))  # Reason for the transaction; required for withdrawals
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Make the current datetime available as "now" in templates
@app.context_processor
def inject_now():
    return {'now': datetime.now}

# -----------------------------
# Authentication Routes
# -----------------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('Username already exists!')
            return redirect(url_for('register'))
        new_user = User(
            username=username,
            password=generate_password_hash(password, method='pbkdf2:sha256')
        )
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful! Please log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password, password):
            flash('Invalid credentials, please try again.')
            return redirect(url_for('login'))
        login_user(user)
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# -----------------------------
# Dashboard & Transaction Routes
# -----------------------------
@app.route('/')
@login_required
def dashboard():
    # Optional filters via query string: start_date, end_date, transaction_type
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    tx_type = request.args.get('transaction_type')
    
    query = Transaction.query.filter_by(user_id=current_user.id)
    
    if start_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(Transaction.date >= start_date_obj)
        except ValueError:
            pass
    if end_date:
        try:
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(Transaction.date <= end_date_obj)
        except ValueError:
            pass
    if tx_type and tx_type in ['withdrawal', 'deposit']:
        query = query.filter_by(transaction_type=tx_type)
    
    transactions = query.order_by(Transaction.date.desc()).all()
    balance = sum(tx.amount if tx.transaction_type == 'deposit' else -tx.amount for tx in transactions)
    
    return render_template('dashboard.html', transactions=transactions, balance=balance)

@app.route('/add_transaction', methods=['POST'])
@login_required
def add_transaction():
    amount = request.form.get('amount')
    date_str = request.form.get('date')
    transaction_type = request.form.get('transaction_type')
    reason = request.form.get('reason', '').strip()
    
    try:
        amount = float(amount)
    except ValueError:
        flash('Invalid amount entered.')
        return redirect(url_for('dashboard'))
    
    try:
        tx_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        tx_date = date.today()

    # Validate that reason is provided for withdrawals
    if transaction_type == 'withdrawal' and not reason:
        flash('Reason is required for a withdrawal.')
        return redirect(url_for('dashboard'))
    
    new_tx = Transaction(
        amount=amount,
        date=tx_date,
        transaction_type=transaction_type,
        reason=reason,
        user_id=current_user.id
    )
    db.session.add(new_tx)
    db.session.commit()
    flash('Transaction added successfully!')
    return redirect(url_for('dashboard'))

# -----------------------------
# Report Generation (PDF) using xhtml2pdf
# -----------------------------
@app.route('/report')
@login_required
def report():
    report_type = request.args.get('type', 'daily')  # Options: daily, weekly, monthly, yearly
    today = date.today()
    
    # Determine report period based on type
    if report_type == 'daily':
        start = today
        end = today
    elif report_type == 'weekly':
        start = today - timedelta(days=today.weekday())  # Monday
        end = start + timedelta(days=6)
    elif report_type == 'monthly':
        start = today.replace(day=1)
        if today.month == 12:
            next_month = today.replace(year=today.year+1, month=1, day=1)
        else:
            next_month = today.replace(month=today.month+1, day=1)
        end = next_month - timedelta(days=1)
    elif report_type == 'yearly':
        start = today.replace(month=1, day=1)
        end = today.replace(month=12, day=31)
    else:
        flash('Invalid report type.')
        return redirect(url_for('dashboard'))
    
    transactions = Transaction.query.filter(
        Transaction.user_id == current_user.id,
        Transaction.date >= start,
        Transaction.date <= end
    ).order_by(Transaction.date.desc()).all()
    balance = sum(tx.amount if tx.transaction_type == 'deposit' else -tx.amount for tx in transactions)
    
    # Render the HTML for the report
    rendered = render_template(
        'report.html',
        transactions=transactions,
        balance=balance,
        report_type=report_type.capitalize(),
        start=start,
        end=end
    )
    
    # Create a PDF file from the rendered HTML using xhtml2pdf
    pdf = io.BytesIO()
    pisa_status = pisa.CreatePDF(rendered, dest=pdf)
    
    if pisa_status.err:
        flash('Error generating PDF report.')
        return redirect(url_for('dashboard'))
    
    response = Response(pdf.getvalue(), mimetype='application/pdf')
    response.headers['Content-Disposition'] = f'attachment; filename={report_type}_report.pdf'
    return response

if __name__ == "__main__":
    app.run(debug=True)
