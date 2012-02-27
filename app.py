import re, os, json, simplejson
from gevent import monkey; monkey.patch_all()
import requests
from requests import async
from flask import Flask, Response
from itertools import chain
from datetime import datetime
from flaskext.sqlalchemy import SQLAlchemy
from readability.readability import Document
import logging
logging.basicConfig()
logger = logging.Logger("hnunderground")
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
db = SQLAlchemy(app)

front_regex = """<a\sid=up_([0-9]*).*?vote.*?<a\shref="([^"]*)".*?>([^<]*)<"""

class Link(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  url = db.Column(db.String(255), unique=True)
  title = db.Column(db.String(255))
  article = db.Column(db.Text)
  current = db.Column(db.Boolean)
  last_updated = db.Column(db.DateTime)
     
  def __init__(self, id, url, title):
    if not url.startswith("http"):
      url = "http://news.ycombinator.com/" + url
    self.id = id
    self.url = url
    self.title = title
    self.article = None
    self.current = True
    
  def refreshAsync(self):
    def update(response):
      self.article = Document(response.text).summary()
      self.last_updated = datetime.now()
    request = requests.async.get(self.url, hooks=dict( response= update))
    return request
  
  def fill(self):
    if self.article is None:
      self.refreshAsync().send()
  
  @classmethod
  def fillAll(cls, links):
    reqs = []
    for link in links:
      if(link.article is None):
        reqs.append(link.refreshAsync())
    async.map(reqs)
    
class HNParser(object):
  def __init__(self, pages = 1):
    self.pages = pages
    
  def results(self):
    pageset = [self.getPage(x) for x in xrange(1,self.pages + 1)]
    return [x for x in chain(*pageset)]
    
  def getPage(self, page):
    baseUrl = "http://news.ycombinator.com/news"
    if page > 1:
      baseUrl += str(page)
    resp = requests.get(baseUrl)
    data = resp.text
    raw = re.findall(front_regex, data)
    links = []
    for (id, url, title) in raw:
      link = Link.query.get(id)
      if link is None:
        link = Link(id, url, title)
        db.session.add(link)
      links.append(link)
    return links
    
@app.route("/")
def root():
  rep = simplejson.dumps({
    "/": "these messages",
    "/recent": "recent hn articles"
  }, default=lambda x: repr(x))
  return Response(rep, content_type="application/json")

@app.route("/recent")
def recent():
  parser = HNParser()
  links = parser.results()
  Link.fillAll(links)
  db.session.commit()
  linkReps = [(l.id, l.url, l.title, l.article, l.last_updated) for l in links]
  rep = simplejson.dumps(linkReps, default=lambda x: repr(x))
  return Response(rep, content_type="application/json")
  

if __name__ == "__main__":
  # Bind to PORT if defined, otherwise default to 5000.
  port = int(os.environ.get('PORT', 5000))
  app.run(host='0.0.0.0', port=port, debug=True)
