import json
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

# Load config
with open('config.json') as f:
    config = json.load(f)

# Load template
with open('templates/cortogen_direct.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Generate personalized HTML
html = html.replace('{{first_name}}', 'Rudray')
html = html.replace('{{email}}', config['notification_email'])

# Send email
msg = MIMEMultipart('alternative')
msg['Subject'] = Header('Test Email: Cortogen Direct Template', 'utf-8')
msg['From'] = Header(f"Cortogen Team <{config['sender_email']}>", 'utf-8')
msg['To'] = Header(config['notification_email'], 'utf-8')
reply_to = config.get("reply_to_email")
if reply_to:
    msg['Reply-To'] = Header(reply_to, 'utf-8')

msg.attach(MIMEText('Please view in HTML', 'plain', 'utf-8'))
msg.attach(MIMEText(html, 'html', 'utf-8'))

print('Connecting to SMTP...')
try:
    with smtplib.SMTP_SSL(config['smtp_host'], config['smtp_port']) as server:
        server.login(config['smtp_username'], config['app_password'])
        server.sendmail(config['sender_email'], [config['notification_email']], msg.as_string())
    print('Test email sent successfully to', config['notification_email'])
except Exception as e:
    print(f'Error: {e}')
