-- Reference DDL (the app also creates these automatically via SQLAlchemy `db.create_all()`).
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY, username VARCHAR(80) UNIQUE NOT NULL, full_name VARCHAR(120),
  password_hash VARCHAR(255) NOT NULL, role VARCHAR(20) DEFAULT 'user', created_at TIMESTAMP DEFAULT now());
CREATE TABLE IF NOT EXISTS customers (
  id SERIAL PRIMARY KEY, cust_ref VARCHAR(20) UNIQUE NOT NULL, account_no VARCHAR(40),
  name VARCHAR(200) NOT NULL, currency VARCHAR(3) NOT NULL, contact_person VARCHAR(120),
  phone VARCHAR(40), email VARCHAR(120), address TEXT, credit_limit NUMERIC(16,2),
  notes TEXT, created_at TIMESTAMP DEFAULT now());
CREATE INDEX IF NOT EXISTS ix_customers_account_no ON customers(account_no);
CREATE INDEX IF NOT EXISTS ix_customers_name ON customers(name);
CREATE TABLE IF NOT EXISTS instalments (
  id SERIAL PRIMARY KEY, inst_id VARCHAR(30) UNIQUE NOT NULL,
  customer_id INT NOT NULL REFERENCES customers(id), currency VARCHAR(3) NOT NULL,
  original_amount NUMERIC(16,2) NOT NULL, due_date DATE, security VARCHAR(60),
  reference VARCHAR(200), date_raised DATE, description VARCHAR(300), created_at TIMESTAMP DEFAULT now());
CREATE TABLE IF NOT EXISTS collections (
  id SERIAL PRIMARY KEY, customer_id INT NOT NULL REFERENCES customers(id),
  instalment_id INT NOT NULL REFERENCES instalments(id), txn_ref VARCHAR(60),
  amount NUMERIC(16,2) NOT NULL, currency VARCHAR(3) NOT NULL, method VARCHAR(30),
  collected_on DATE, received_by VARCHAR(80), comments VARCHAR(300), created_at TIMESTAMP DEFAULT now());
CREATE TABLE IF NOT EXISTS reminders (
  id SERIAL PRIMARY KEY, customer_id INT NOT NULL REFERENCES customers(id), level INT NOT NULL,
  currency VARCHAR(3), amount_overdue NUMERIC(16,2), sent_on DATE, sent_by VARCHAR(80),
  notes VARCHAR(300), created_at TIMESTAMP DEFAULT now());
