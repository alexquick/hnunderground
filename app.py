import re, os
from gevent import monkey; monkey.patch_all()
import lxml.html
import lxml.etree
import requests
import logging
import base64
import simplejson
import hashlib
import urlparse
import feedparser
from StringIO import StringIO
from requests import async
from flask import Flask, Response
from itertools import chain
from datetime import datetime
import redis
from readability.readability import Document

logging.basicConfig()
app = Flask(__name__)

front_regex = """<a\sid=up_([0-9]*).*?vote.*?<a\shref="([^"]*)".*?>([^<]*)<"""

def getConnection():
    return redis.StrictRedis(host='localhost')

class Article():
  def __init__(self, id, url, title, article = None):
    url = urlparse.urljoin("http://news.ycombinator.com/news", url)
    self.id = id
    self.url = url
    self.title = title
    self.article = article

  def _update(self, response):
    app.logger.debug("Updating %s" % response.url)
    data = Document(response.text).summary()
    doc = lxml.html.fromstring(data)
    images = []
    imageElems = doc.xpath("//img")
    app.logger.debug("%d images for %s",len(imageElems), response.url)
    for img in imageElems:
      src = urlparse.urljoin(response.url, img.get("src"))
      imgResp = requests.get(src)
      encoded = base64.b64encode(imgResp.content)
      if len(encoded) < 3000:
        src = "data:" + imgResp.headers["content-type"] + ";base64," + encoded
      else:
        md5 = hashlib.sha1()
        md5.update(encoded)
        name = md5.hexdigest()
        src = name +"." + src.rpartition(".")[2]
        images.append((src, encoded))
      img.set("src", src)
    data = StringIO()
    data.write(lxml.etree.tostring(doc, pretty_print=True))
    for (name, imageData) in images:
      data.write("\n--data:"+name+"\n"+imageData)
    data.seek(0)
    self.article = data.read()
    self.save()

  def refreshAsync(self):
    request = requests.async.get(self.url, hooks=dict( response= self._update))
    return request

  def fill(self):
    if self.article is None:
      self.refreshAsync().send()

  @classmethod
  def lookup(cls, id):
    r = getConnection()
    page = r.get("page_%s" % id)
    if page is None: return None
    rep = simplejson.loads(page)
    id = rep['id']
    title = rep['title']
    url = rep['url']
    article = rep['article']
    return Article(id, title, url, article=article);

  def save(self):
    data = {
      'id': self.id,
      'url': self.url,
      'title': self.title,
      'article': self.article
    }
    r = getConnection()
    r.set("page_%s" % self.id, simplejson.dumps(data));
    app.logger.debug("saving page_%s" % self.id)

  @classmethod
  def fillAll(cls, articles):
    reqs = []
    for article in articles:
      if(article.article is None):
        reqs.append(article.refreshAsync())
    async.map(reqs)

class HNParser(object):
  def __init__(self):
    pass
  def results(self):
    articles = []
    baseUrl = "http://news.ycombinator.com/rss"
    feed = feedparser.parse(baseUrl)
    for entry in feed.entries:
      id = re.search("([0-9]+$)", entry.comments).groups(0)[0]
      url = entry.link
      title = entry.title
      article = Article.lookup(id)
      if article is None:
        article = Article(id, url, title)
        article.save()
      articles.append(article)
    return articles

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
  articles = parser.results()
  Article.fillAll(articles)
  linkReps = [(l.id, l.url, l.title, l.article) for l in articles]
  rep = simplejson.dumps(linkReps, default=lambda x: repr(x))
  return Response(rep, content_type="application/json")

if __name__ == "__main__":
  # Bind to PORT if defined, otherwise default to 5000.
  port = int(os.environ.get('PORT', 5000))
  app.run(host='0.0.0.0', port=port, debug=True)
