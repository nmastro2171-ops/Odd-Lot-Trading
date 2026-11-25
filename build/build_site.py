#!/usr/bin/env python3
"""Builds listings.js, blog posts, blog index, posts.json, sitemap for oddlottrading.com.
Usage: python3 build_site.py <raw listings txt> <site dir>
"""
import json, re, sys, os, html, unicodedata
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))
from content_ref import P, S
from content_items_a import A
from content_items_b import B

ITEMS = {**A, **B}
RAW, SITE = sys.argv[1], sys.argv[2]
DOMAIN = "https://oddlottrading.com"
PUB_DATE = "2026-11-23"
STORE = "https://www.ebay.com/usr/oddlottrading"

def cat(t):
    tl = t.lower()
    if 'stock certificate' in tl: return 'Stock Certificates'
    if re.search(r'banknote|nickels|penny coin|krugerrand|francs|coin set', tl): return 'Coins & Currency'
    if re.search(r'comic|superman|batman', tl): return 'Comics'
    if re.search(r'ticket|photo|newspaper|yearbook|calendar|program|sports illustrated', tl): return 'Memorabilia'
    if re.search(r'sealed pack|pack \d+ cards|cards box| box 132', tl): return 'Sealed Packs & Boxes'
    if re.search(r'favre|irvin|ahman green|jim brown|jeanty|nubin|football|nfl', tl): return 'Football Cards'
    if re.search(r"lakers|nba|celtics|jazz|nets|warriors|spurs|timberwolves|mavericks|bulls|okc|basketball|dribble|bowman's best", tl): return 'Basketball Cards'
    return 'Baseball Cards'

def slugify(s):
    s = s.replace('Đ', 'D').replace('đ', 'd')
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^a-zA-Z0-9]+', '-', s).strip('-').lower()
    return s[:72].rstrip('-')

def esc(s): return html.escape(str(s), quote=True)
def money(n): return f"${n:,.2f}"

# ---- load listings
rows = []
for line in open(RAW, encoding='utf-8'):
    line = line.rstrip('\n')
    if not line: continue
    i, t, p, c, s, img = line.split('|')
    yrs = [int(y) for y in re.findall(r'\b(19[0-9]{2}|20[0-2][0-9])\b', t)]
    rows.append(dict(id=i, title=t, price=float(p.strip('$').replace(',', '')), condition=c or None,
                     shipping=float(s.strip('+$')), category=cat(t), year=min(yrs) if yrs else None,
                     image=f"https://i.ebayimg.com/images/g/{img}/s-l500.webp",
                     imageLarge=f"https://i.ebayimg.com/images/g/{img}/s-l1600.webp",
                     url=f"https://www.ebay.com/itm/{i}"))
used = set()
for r in rows:
    head = ITEMS[r['id']][0]
    slug = slugify(head)
    if slug in used: slug = f"{slug}-{r['id'][-4:]}"
    used.add(slug); r['slug'] = slug; r['headline'] = head

# ---- listings.js (shop snapshot)
os.makedirs(f"{SITE}/js", exist_ok=True)
snap = [{k: r[k] for k in ('id','title','price','condition','shipping','category','year','image','url','slug')} for r in rows]
with open(f"{SITE}/js/listings.js", 'w', encoding='utf-8') as f:
    f.write('/* Odd Lot Trading eBay listings snapshot (fallback when the live eBay sync is unavailable). */\n')
    f.write('window.OLT_LISTINGS = ' + json.dumps({'updated': PUB_DATE, 'seller': 'oddlottrading', 'items': snap}, ensure_ascii=False) + ';\n')

# ---- posts.json (used by the Worker to link live listings to their stories)
os.makedirs(f"{SITE}/data", exist_ok=True)
with open(f"{SITE}/data/posts.json", 'w', encoding='utf-8') as f:
    json.dump({r['id']: {'slug': r['slug'], 'headline': r['headline']} for r in rows}, f, ensure_ascii=False)

# ---- shared chrome
def head(title, desc, prefix, canonical, image=None, extra=""):
    img = image or f"{DOMAIN}/assets/logo-round.jpg"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:image" content="{esc(img)}">
<meta property="og:url" content="{canonical}">
<meta name="theme-color" content="#0d0b09">
<link rel="icon" href="{prefix}favicon.ico" sizes="any">
<link rel="icon" type="image/png" href="{prefix}assets/favicon.png">
<link rel="apple-touch-icon" href="{prefix}assets/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Alfa+Slab+One&family=Oswald:wght@400;500;600&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{prefix}assets/site.css">
{extra}</head>
<body>
<header class="top">
  <div class="wrap">
    <a class="brand" href="{prefix}index.html" aria-label="Odd Lot Trading Co. home">
      <img src="{prefix}assets/logo-round.webp" alt="" width="42" height="42">
      <span>Odd Lot</span>
    </a>
    <nav class="main" aria-label="Main">
      <a href="{prefix}index.html#shop">Shop</a>
      <a href="{prefix}blog/index.html">Blog</a>
      <a href="{prefix}index.html#about">About</a>
      <a class="btn btn-gold" href="{STORE}" target="_blank" rel="noopener">eBay Store</a>
    </nav>
  </div>
</header>
"""

def foot(prefix):
    return f"""<footer>
  <div class="wrap">
    <div>© 2026 Odd Lot Trading Co. · All sales handled through <a href="{STORE}" target="_blank" rel="noopener">eBay</a>.</div>
    <div><a href="{prefix}index.html#shop">Shop</a> · <a href="{prefix}blog/index.html">Blog</a></div>
  </div>
</footer>
"""

SECTION = {
 'Comics': 'About the comic', 'Coins & Currency': 'Collecting notes', 'Stock Certificates': 'About collecting stock certificates',
 'Memorabilia': 'Why collectors love it', 'Sealed Packs & Boxes': 'About the product',
}
CHECK = {
 'Baseball Cards': "Zoom in on the corners, edges, centering and surface in the eBay photos. Vintage cards are graded on all four, and the scans show exactly what you'll receive.",
 'Basketball Cards': "Zoom in on the corners, edges and surface in the eBay photos. Chromium and foil cards can show scratches or print lines, and the scans show exactly what you'll receive.",
 'Football Cards': "Zoom in on the corners, edges and surface in the eBay photos. The scans show exactly what you'll receive.",
 'Sealed Packs & Boxes': "Sealed product is sold as-is and unsearched, and the eBay photos show the wrapper and any wear.",
 'Comics': "Check the eBay photos for spine stress, corner wear and cover gloss. What you see is what ships.",
 'Coins & Currency': "Items are uncertified and ungraded unless stated. The eBay photos show the actual piece, front and back.",
 'Stock Certificates': "The eBay photos show the actual certificate, including folds, cancellations and toning.",
 'Memorabilia': "The eBay photos show the actual piece, including any creases, toning or wear from age.",
}

def buttons(r, cls=""):
    return f"""<div class="post-actions {cls}">
      <a class="btn btn-gold" href="{r['url']}" target="_blank" rel="noopener">Buy It Now · {money(r['price'])}</a>
      <a class="btn btn-line" href="{r['url']}" target="_blank" rel="noopener">Make an Offer</a>
    </div>"""

by_cat = defaultdict(list)
for r in rows: by_cat[r['category']].append(r)

def post_page(r, idx):
    head_, lede, people, setk = ITEMS[r['id']]
    prefix = "../../"
    canonical = f"{DOMAIN}/blog/{r['slug']}/"
    desc = re.sub(r'\s+', ' ', lede)[:155].rsplit(' ', 1)[0] + '…' if len(lede) > 158 else lede
    ship = f"+{money(r['shipping'])} shipping" if r['shipping'] else "Free shipping"
    body = [f'<p class="lede">{esc(lede)}</p>']
    for pk in people:
        name, bio = P[pk]
        body.append(f'<h2>About {esc(name)}</h2>\n<p>{esc(bio)}</p>')
    sec = SECTION.get(r['category'], 'About the set')
    body.append(f'<h2>{sec}</h2>\n<p>{esc(S[setk])}</p>')
    facts = [("Listing", r['title']), ("Category", r['category']), ("Condition", r['condition'] or "See listing photos"),
             ("Price", f"{money(r['price'])} or Best Offer"), ("Shipping", ship), ("eBay item #", r['id'])]
    body.append('<h2>What you\'re getting</h2>\n<dl class="facts">' + ''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k, v in facts) + '</dl>')
    body.append(f'<p>{esc(CHECK[r["category"]])} Every purchase goes through eBay checkout, so you\'re covered by the eBay Money Back Guarantee.</p>')
    body.append(f'<h2>Make it yours</h2>\n<p>Like it? Buy it now, or make us an offer. We read every one and are happy to work with collectors on fair deals. Bundling with other items from the shop? Send an offer or message us on eBay about combined shipping.</p>')
    rel = [x for x in by_cat[r['category']] if x['id'] != r['id']]
    # pick 3 nearby related items, deterministic
    rel = (rel[idx % max(1, len(rel)):] + rel)[:3]
    rel_html = ''.join(f"""<a class="rel" href="../{x['slug']}/index.html"><img src="{x['image']}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src='{prefix}assets/logo-round.webp';this.classList.add('ph')"><span>{esc(x['headline'])}</span><b>{money(x['price'])}</b></a>""" for x in rel)
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "BlogPosting", "headline": head_, "datePublished": PUB_DATE, "image": r['imageLarge'], "mainEntityOfPage": canonical,
         "author": {"@type": "Organization", "name": "Odd Lot Trading Co."}, "publisher": {"@type": "Organization", "name": "Odd Lot Trading Co.", "logo": {"@type": "ImageObject", "url": f"{DOMAIN}/assets/logo-round.jpg"}}},
        {"@type": "Product", "name": r['title'], "image": r['imageLarge'], "sku": r['id'], "category": r['category'],
         "offers": {"@type": "Offer", "url": r['url'], "priceCurrency": "USD", "price": f"{r['price']:.2f}", "availability": "https://schema.org/InStock",
                    "itemCondition": "https://schema.org/NewCondition" if (r['condition'] or '').startswith(('Brand New', 'New')) else "https://schema.org/UsedCondition"}}]}
    extra = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>\n'
    return head(f"{head_} | Odd Lot Trading Co. Blog", desc, prefix, canonical, r['imageLarge'], extra) + f"""
<main class="post" data-item-id="{r['id']}">
  <div class="wrap narrow">
    <nav class="crumbs"><a href="../index.html">Blog</a> / <span>{esc(r['category'])}</span></nav>
    <h1>{esc(head_)}</h1>
    <div class="post-meta">Odd Lot Trading Co. · <time datetime="{PUB_DATE}">November 23, 2026</time></div>
    <figure class="hero-img"><a href="{r['url']}" target="_blank" rel="noopener"><img src="{r['imageLarge']}" alt="{esc(r['title'])}" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src='{prefix}assets/logo-round.webp';this.classList.add('ph')"></a>
      <figcaption>Photo of the actual item from our eBay listing.</figcaption></figure>
    <div class="buybox">
      <div><span class="price">{money(r['price'])}</span> <span class="ship">{ship}</span><div class="offer-note">or Best Offer</div></div>
      {buttons(r)}
    </div>
    <div class="sold-banner" hidden>This item has sold. <a href="{prefix}index.html#shop">See what's still available &rarr;</a></div>
    <article class="prose">
      {chr(10).join(body)}
    </article>
    <div class="buybox bottom">
      <div><span class="price">{money(r['price'])}</span> <span class="ship">{ship}</span><div class="offer-note">or Best Offer</div></div>
      {buttons(r)}
    </div>
    <section class="related"><h2>More {esc(r['category'])}</h2><div class="rel-grid">{rel_html}</div></section>
  </div>
</main>
""" + foot(prefix) + POST_SCRIPT + "</body>\n</html>\n"

POST_SCRIPT = """<script>
(function(){
  var el=document.querySelector('[data-item-id]'); if(!el||location.protocol.indexOf('http')!==0) return;
  var id=el.getAttribute('data-item-id');
  fetch('/api/listings').then(function(r){return r.ok?r.json():null}).then(function(j){
    if(!j||!j.items||!j.items.length) return;
    var it=j.items.filter(function(x){return x.id===id})[0];
    if(!it){
      document.querySelector('.sold-banner').hidden=false;
      Array.prototype.forEach.call(document.querySelectorAll('.buybox'),function(b){b.hidden=true});
      return;
    }
    var p='$'+Number(it.price).toFixed(2).replace(/\\B(?=(\\d{3})+(?!\\d))/g,',');
    Array.prototype.forEach.call(document.querySelectorAll('.buybox .price'),function(n){n.textContent=p});
    Array.prototype.forEach.call(document.querySelectorAll('.post-actions .btn-gold'),function(n){n.textContent='Buy It Now · '+p});
  }).catch(function(){});
})();
</script>
"""

for idx, r in enumerate(rows):
    d = f"{SITE}/blog/{r['slug']}"
    os.makedirs(d, exist_ok=True)
    open(f"{d}/index.html", 'w', encoding='utf-8').write(post_page(r, idx))

# ---- blog index
cats = ["Baseball Cards","Basketball Cards","Football Cards","Sealed Packs & Boxes","Comics","Coins & Currency","Stock Certificates","Memorabilia"]
cards = []
for r in rows:
    lede = ITEMS[r['id']][1]
    ex = lede if len(lede) < 170 else lede[:165].rsplit(' ', 1)[0] + '…'
    cards.append(f"""<article class="bcard" data-cat="{esc(r['category'])}" data-hay="{esc((r['headline']+' '+r['title']+' '+r['category']).lower())}">
  <a class="bimg" href="{r['slug']}/index.html"><img src="{r['image']}" alt="{esc(r['title'])}" loading="lazy" referrerpolicy="no-referrer"></a>
  <div class="bbody"><span class="tag-inline">{esc(r['category'])}</span>
  <h2><a href="{r['slug']}/index.html">{esc(r['headline'])}</a></h2>
  <p>{esc(ex)}</p>
  <div class="bfoot"><b>{money(r['price'])}</b><a href="{r['slug']}/index.html">Read more &rarr;</a></div></div>
</article>""")
counts = defaultdict(int)
for r in rows: counts[r['category']] += 1
chips = '<button class="chip" type="button" data-cat="All" aria-pressed="true">All<span class="n">%d</span></button>' % len(rows) + ''.join(
    f'<button class="chip" type="button" data-cat="{esc(c)}" aria-pressed="false">{esc(c)}<span class="n">{counts[c]}</span></button>' for c in cats if counts[c])
blog_index = head("The Odd Lot Blog | Stories Behind the Haul", "Stories, history and collecting notes behind every card, coin, comic and collectible in the Odd Lot Trading Co. shop.", "../", f"{DOMAIN}/blog/") + f"""
<main class="bloglist">
  <div class="wrap">
    <section class="blog-hero">
      <h1>The Odd Lot Blog</h1>
      <p>The story behind every piece in the haul: the players, the sets, the history and what to look for. Every post links straight to the eBay listing.</p>
    </section>
    <div class="chips" id="chips" role="group" aria-label="Filter posts by category">{chips}</div>
    <div class="controls"><label class="search"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input type="search" id="q" placeholder="Search posts…" aria-label="Search posts"></label><span class="count" id="count" aria-live="polite">{len(rows)} posts</span></div>
    <div class="bgrid" id="bgrid">
{chr(10).join(cards)}
    </div>
    <div class="bgrid" id="autoposts"></div>
  </div>
</main>
""" + foot("../") + """<script>
(function(){
  var cat='All',q='',grid=document.getElementById('bgrid'),cards=[].slice.call(grid.children),cnt=document.getElementById('count');
  function apply(){var w=q.toLowerCase().split(/\\s+/).filter(Boolean),n=0;
    cards.forEach(function(c){var ok=(cat==='All'||c.getAttribute('data-cat')===cat)&&w.every(function(x){return c.getAttribute('data-hay').indexOf(x)>=0});c.hidden=!ok;if(ok)n++});
    cnt.textContent=n+(n===1?' post':' posts');}
  document.getElementById('chips').addEventListener('click',function(e){var b=e.target.closest('.chip');if(!b)return;cat=b.getAttribute('data-cat');
    [].forEach.call(this.children,function(c){c.setAttribute('aria-pressed',c===b)});apply();});
  var t;document.getElementById('q').addEventListener('input',function(e){clearTimeout(t);var v=e.target.value;t=setTimeout(function(){q=v;apply()},120)});
  grid.addEventListener('error',function(e){var i=e.target;if(i.tagName==='IMG'&&!i.dataset.f){i.dataset.f=1;i.src='../assets/logo-round.webp';i.classList.add('ph')}},true);
  // Posts generated automatically for newly listed items (from the eBay sync).
  if(location.protocol.indexOf('http')===0){fetch('/api/posts').then(function(r){return r.ok?r.json():null}).then(function(j){
    if(!j||!j.posts||!j.posts.length)return;
    var html=j.posts.map(function(p){return '<article class="bcard" data-cat="'+p.category+'" data-hay="'+(p.headline+' '+p.category).toLowerCase().replace(/"/g,'')+'"><a class="bimg" href="/blog/'+p.slug+'/"><img src="'+p.image+'" alt="" loading="lazy" referrerpolicy="no-referrer"></a><div class="bbody"><span class="tag-inline">New listing</span><h2><a href="/blog/'+p.slug+'/">'+p.headline.replace(/</g,'&lt;')+'</a></h2><div class="bfoot"><b>$'+Number(p.price).toFixed(2)+'</b><a href="/blog/'+p.slug+'/">Read more &rarr;</a></div></div></article>'}).join('');
    grid.insertAdjacentHTML('afterbegin',html);cards=[].slice.call(grid.children);apply();}).catch(function(){});}
})();
</script>
</body>
</html>
"""
open(f"{SITE}/blog/index.html", 'w', encoding='utf-8').write(blog_index)

# ---- sitemap + robots
urls = [f"{DOMAIN}/", f"{DOMAIN}/blog/"] + [f"{DOMAIN}/blog/{r['slug']}/" for r in rows]
open(f"{SITE}/sitemap.xml", 'w').write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
    ''.join(f"  <url><loc>{u}</loc><lastmod>{PUB_DATE}</lastmod></url>\n" for u in urls) + '</urlset>\n')
open(f"{SITE}/robots.txt", 'w').write(f"User-agent: *\nAllow: /\nSitemap: {DOMAIN}/sitemap.xml\n")
print("built", len(rows), "posts")
