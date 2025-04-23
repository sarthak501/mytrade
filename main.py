from GoogleNews import GoogleNews
import time
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import random
import logging
import sys
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from urllib.parse import urlparse, parse_qsl, urlunparse, urlencode

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
SEARCH_QUERY = (
    "India AND (business OR finance OR economy OR markets "
    "OR stocks OR revenue OR company OR IPO OR investment OR profit)"
)
MAX_PAGES = 100

# Initialize sentiment analyzer
analyzer = SentimentIntensityAnalyzer()

def normalize_url(url):
    """Strip tracking/query params to avoid near-duplicate URLs."""
    p = urlparse(url)
    qs = [(k, v) for k, v in parse_qsl(p.query) if not k.startswith('utm_')]
    return urlunparse((p.scheme, p.netloc, p.path, '', urlencode(sorted(qs)), ''))


def normalize_title(title):
    """Lowercase and strip title for secondary dedupe."""
    return title.strip().lower()


class NewsScraper:
    def __init__(self):
        # initialize GoogleNews instance and tracking sets
        self.gn = self.create_instance()
        self.articles = []
        self.unique_urls = set()
        self.unique_titles = set()
        self.consecutive_empty = 0

    def create_instance(self):  
        gn = GoogleNews(lang='en', region='IN', encode='utf-8')  
        gn.search(SEARCH_QUERY)
        gn.set_period('1d')  
        return gn  

    def smart_delay(self, page):  
        delay = random.uniform(3, 7) + (page * 0.2)  
        time.sleep(min(delay, 15))  
        return delay  

    def score_sentiment(self, text):
        """Return compound sentiment score for given text."""
        vs = analyzer.polarity_scores(text)
        return vs['compound']

    def scrape_page(self, page):  
        """Use page_at for true pagination, score sentiment, normalize before dedupe."""
        max_retries = 3  
        for attempt in range(max_retries):  
            try:  
                results = self.gn.page_at(page)  
                new_articles = []  
                for a in results or []:  
                    link = normalize_url(a['link'])  
                    title = a.get('title','').strip()
                    key_title = normalize_title(title)
                    if link not in self.unique_urls and key_title not in self.unique_titles:  
                        # compute sentiment score
                        score = self.score_sentiment(title)
                        a['sentiment'] = score
                        new_articles.append(a)  
                        self.unique_urls.add(link)  
                        self.unique_titles.add(key_title)  
                return new_articles  

            except Exception as e:  
                err = str(e).lower()  
                if '429' in err or 'too many requests' in err:  
                    wait = 600  
                    logger.warning(f"Page {page}: rate limit (attempt {attempt+1}), sleeping {wait}s")  
                    time.sleep(wait)  
                    self.gn = self.create_instance()  
                    continue  

                wait = 30 * (2**attempt) * random.uniform(0.8,1.2)  
                logger.warning(f"Page {page}: attempt {attempt+1} failed ({e}), sleeping {wait:.1f}s")  
                self.gn = self.create_instance()  
                time.sleep(wait)  

        logger.error(f"Page {page}: failed after {max_retries} attempts")  
        return []  

    def scrape(self):  
        logger.info(f"Starting scraping up to {MAX_PAGES} pages…")  
        batch = 10  
        try:  
            for start in range(0, MAX_PAGES, batch):  
                end = min(start+batch, MAX_PAGES)  
                logger.info(f"Batch pages {start+1}–{end}")  
                for page in range(start+1, end+1):  
                    if page % random.randint(3,7) == 0:  
                        self.gn = self.create_instance()  
                    d = self.smart_delay(page)  
                    logger.info(f"Page {page} (delay {d:.1f}s)")  
                    new = self.scrape_page(page)  
                    if new:  
                        self.articles.extend(new)  
                        self.consecutive_empty = 0  
                        logger.info(f"Page {page}: +{len(new)} articles")  
                    else:  
                        self.consecutive_empty += 1  
                        logger.info(f"Page {page}: no new articles")  
                    if self.consecutive_empty >= 15:  
                        logger.info("Stopping after 15 empty pages")  
                        return self.articles  
                if end < MAX_PAGES:  
                    ld = random.uniform(240,360)  
                    logger.info(f"Batch done, sleeping {ld:.1f}s")  
                    time.sleep(ld)  
        except KeyboardInterrupt:  
            logger.info("Interrupted by user")  
        return self.articles  

    def create_pdf(self):  
        if not self.articles:  
            return None  
        fn = f"India_Business_News_{datetime.today():%Y-%m-%d}.pdf"  
        c = canvas.Canvas(fn, pagesize=letter)  
        styles = getSampleStyleSheet()  
        y = 750  
        c.setFont("Helvetica-Bold", 16)  
        c.drawString(50, y, "India Business News Report")  
        y -= 40  
        style = styles['Normal']  
        style.wordWrap, style.fontSize, style.leading = 'LTR', 10, 13  
        for i, a in enumerate(self.articles, 1):  
            title = a.get('title','').strip()  
            score = a.get('sentiment', 0)
            desc = a.get('desc','').strip()  
            src = a.get('media','').strip()  
            # prefix sentiment score
            txt = f"<b>{i}. [{score:+.2f}] {title}</b>"  
            if src:
                txt += f" <i>({src})</i>"
            if desc:
                txt += f"<br/>{desc}"
            p = Paragraph(txt, style)  
            p.wrapOn(c, 500, 800)  
            h = p.height  
            if y - h < 50:  
                c.showPage()
                y = 750  
            p.drawOn(c, 50, y - h)  
            y -= h + 10  
        c.save()  
        logger.info(f"PDF saved: {fn}")  
        return fn


def send_email(pdf):
    sender, receiver = "sarthakrana501@gmail.com", "sarthakr274@gmail.com"
    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = sender, receiver, "India Business News Report"
    msg.attach(MIMEText("Please find attached the latest report.", 'plain'))
    pwd = os.getenv("GMAIL_PASSWORD")
    if not pwd:
        logger.error("No GMAIL_PASSWORD env var")
        return False
    try:
        with open(pdf,'rb') as f:
            part = MIMEBase('application','octet-stream')
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(pdf)}')
        msg.attach(part)
    except Exception as e:
        logger.error(f"Attach failed: {e}")
        return False
    try:
        s = smtplib.SMTP("smtp.gmail.com",587)
        s.starttls()
        s.login(sender,pwd)
        s.send_message(msg)
        s.quit()
        logger.info("Email sent")
        return True
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return False


if __name__ == "__main__":
    # Initialize scraper and run first scrape
    scraper = NewsScraper()
    scraper.scrape()
    # Create initial PDF
    initial_pdf = scraper.create_pdf()
    # Wait for 2 hours before next scrape
    logger.info("Waiting 2 hours before next scrape...")
    time.sleep(2 * 3600)
    # Run scrape again; will only add new articles
    scraper.scrape()
    # Create final PDF with all collected articles
    final_pdf = scraper.create_pdf()
    # Send the final PDF via email
    success = send_email(final_pdf)
    sys.exit(0 if success else 1)
