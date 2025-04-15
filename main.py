from GoogleNews import GoogleNews
import time
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import random
import logging
import sys
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('news_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
SEARCH_QUERY = "India AND (business OR finance OR economy OR markets OR stocks OR revenue OR company OR IPO OR investment OR profit)"
MAX_PAGES = 100

class NewsScraper:
    def __init__(self):
        self.gn = self.create_instance()
        self.articles = []
        self.unique_urls = set()
        self.consecutive_empty = 0
        
    def create_instance(self):
        """Create fresh GoogleNews instance"""
        gn = GoogleNews(lang='en', region='IN', encode='utf-8')
        gn.search(SEARCH_QUERY)
        gn.set_period('1d')
        return gn
    
    def smart_delay(self, page):
        """Adaptive delay with randomness"""
        delay = random.uniform(3, 7) + (page * 0.2)
        time.sleep(min(delay, 15))
        return delay
    
    def scrape_page(self, page):
        """Scrape individual page with exponential backoff retries"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                self.gn.get_page(page)
                results = self.gn.results()
                new_articles = []
                
                if results:
                    new_articles = [
                        a for a in results 
                        if a['link'] not in self.unique_urls
                    ]
                
                return new_articles
                
            except Exception as e:
                error_str = str(e).lower()
                # Check for rate-limiting error (assuming 429 or "too many requests" in message)
                if '429' in error_str or 'too many requests' in error_str:
                    wait_time = 600  # 10 minutes for rate limit errors
                    logger.warning(f"Page {page}: Rate limit hit (attempt {attempt+1}), waiting {wait_time}s")
                    time.sleep(wait_time)
                    self.gn = self.create_instance()  # Refresh instance after rate limit
                    continue
                
                # Exponential backoff for other errors
                wait_time = 30 * (2 ** attempt) * random.uniform(0.8, 1.2)  # e.g., 24–36s, 48–72s, 96–144s
                logger.warning(f"Page {page}: Attempt {attempt+1} failed ({e}), waiting {wait_time:.1f}s")
                self.gn = self.create_instance()
                time.sleep(wait_time)
        
        logger.error(f"Page {page}: Failed after {max_retries} attempts")
        return []

    def scrape(self):
        """Persistent scraping through pagination with batch processing"""
        logger.info("Starting 100-page scraping session...")
        batch_size = 10  # Process 10 pages per batch
        
        try:
            for batch_start in range(0, MAX_PAGES, batch_size):
                batch_end = min(batch_start + batch_size, MAX_PAGES + 1)
                logger.info(f"Processing batch: pages {batch_start + 1} to {batch_end - 1}")
                
                for page in range(batch_start + 1, batch_end):
                    # Random instance refresh
                    if page % random.randint(3, 7) == 0:
                        self.gn = self.create_instance()
                    
                    delay = self.smart_delay(page)
                    logger.info(f"Page {page}: Processing (delay {delay:.1f}s)")
                    
                    new_articles = self.scrape_page(page)
                    
                    if new_articles:
                        self.articles.extend(new_articles)
                        self.unique_urls.update(a['link'] for a in new_articles)
                        logger.info(f"Page {page}: Added {len(new_articles)} new articles")
                        self.consecutive_empty = 0
                    else:
                        self.consecutive_empty += 1
                        logger.info(f"Page {page}: No new articles")
                    
                    # Stop if too many consecutive empty pages
                    if self.consecutive_empty >= 15:
                        logger.info("Too many empty pages, stopping")
                        return self.articles
                
                # Long break between batches (except after the last batch)
                if batch_end <= MAX_PAGES:
                    long_delay = random.uniform(240, 360)  # 4–6 minutes
                    logger.info(f"Batch completed, waiting {long_delay:.1f}s before next batch")
                    time.sleep(long_delay)
                    
        except KeyboardInterrupt:
            logger.info("User interrupted scraping")
            
        return self.articles

    def create_pdf(self):
        """PDF creation with proper text wrapping"""
        if not self.articles:
            return None
        
        try:
            pdf_filename = f"India_Business_News_{datetime.today().strftime('%Y-%m-%d')}.pdf"
            c = canvas.Canvas(pdf_filename, pagesize=letter)
            styles = getSampleStyleSheet()
            
            y_position = 750
            c.setFont("Helvetica-Bold", 16)
            c.drawString(50, y_position, "India Business News Report")
            y_position -= 40
            
            style = styles['Normal']
            style.wordWrap = 'LTR'
            style.fontSize = 10
            style.leading = 13
            
            for idx, article in enumerate(self.articles):
                # Format title and description
                title = article.get('title', 'No Title').strip()
                desc = article.get('desc', '').strip()
                source = article.get('media', '').strip()
                
                text = f"<b>{idx+1}. {title}</b>"
                if source:
                    text += f" <i>({source})</i>"
                if desc:
                    text += f"<br/>{desc}"
                
                # Create paragraph with proper wrapping
                p = Paragraph(text, style)
                p.wrapOn(c, 500, 800)
                h = p.height
                
                if y_position - h < 50:
                    c.showPage()
                    y_position = 750
                
                p.drawOn(c, 50, y_position - h)
                y_position -= h + 10
                
            c.save()
            logger.info(f"Created PDF with {len(self.articles)} articles")
            return pdf_filename
            
        except Exception as e:
            logger.error(f"PDF creation failed: {str(e)}")
            return None

def send_email(pdf_filename):
    """Sends an email with the PDF attached."""
    sender_email = "sarthakrana501@gmail.com"
    receiver_email = "sarthakr274@gmail.com"
    subject = "India Business News Report"
    body = "Please find attached the latest India Business News Report."
    
    # Fetch the password from environment variables
    password = os.getenv("GMAIL_PASSWORD")
    if not password:
        logger.error("Gmail password is not set in environment variables.")
        return False

    # Create message container
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = subject

    # Attach message body
    msg.attach(MIMEText(body, 'plain'))
    
    # Open the PDF file in binary mode and attach it to the email
    try:
        with open(pdf_filename, "rb") as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(pdf_filename)}')
        msg.attach(part)
    except Exception as e:
        logger.error(f"Failed to attach PDF: {str(e)}")
        return False

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        server.quit()
        logger.info("Email sent successfully!")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return False

if __name__ == "__main__":
    scraper = NewsScraper()
    articles = scraper.scrape()
    
    if articles:
        logger.info(f"Total articles collected: {len(articles)}")
        pdf_filename = scraper.create_pdf()
        if pdf_filename:
            email_success = send_email(pdf_filename)
            sys.exit(0 if email_success else 1)
        else:
            logger.error("PDF creation failed.")
            sys.exit(1)
    else:
        logger.error("No articles collected")
        sys.exit(1)
