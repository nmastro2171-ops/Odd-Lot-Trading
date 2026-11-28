/**
 * oddlottrading.com — Cloudflare Worker
 *
 * - Serves the static site in ./site (Workers static assets).
 * - Every hour (cron) pulls the seller's active listings from the eBay Browse API
 *   and stores them in KV, so the shop always matches eBay.
 * - GET  /api/listings  -> live listings (same shape as js/listings.js)
 * - GET  /api/posts     -> auto-generated posts for listings that don't have a written post yet
 * - POST /api/refresh   -> run a sync now (header  X-Refresh-Key: <REFRESH_KEY>)
 * - GET  /blog/item-<ebayId>/ -> auto-generated post page for a new listing
 *
 * Secrets (wrangler secret put ...): EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, REFRESH_KEY
 * Vars (wrangler.toml): EBAY_SELLER, EBAY_MARKETPLACE
 * Bindings: OLT (KV namespace), ASSETS (static assets)
 */

const API = "https://api.ebay.com";
const SCOPE = "https://api.ebay.com/oauth/api_scope";
const STORE = "https://www.ebay.com/usr/oddlottrading";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const p = url.pathname;

    if (p === "/api/listings") return listingsResponse(env, ctx);
    if (p === "/api/posts") return postsResponse(env);
    if (p === "/api/sold") return json((await env.OLT.get("recent_sold", "json")) || { items: [] }, 200, { "Cache-Control": "public, max-age=300" });
    if (p === "/api/status") return json((await env.OLT.get("last_sync", "json")) || { synced: false, secretSet: !!env.EBAY_CLIENT_SECRET }, 200, { "Cache-Control": "no-store" });
    if (p === "/api/refresh") {
      if (request.method !== "POST") return json({ error: "Use POST" }, 405);
      if (!env.REFRESH_KEY || request.headers.get("X-Refresh-Key") !== env.REFRESH_KEY) return json({ error: "Unauthorized" }, 401);
      const result = await sync(env);
      return json(result);
    }
    const m = p.match(/^\/blog\/item-(\d+)(\/|\/index\.html)?$/);
    if (m) return autoPostPage(env, m[1], url);

    return env.ASSETS.fetch(request);
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(sync(env)
      .then(r => { console.log("eBay sync", JSON.stringify(r)); return env.OLT.put("last_sync", JSON.stringify({ at: new Date().toISOString(), ...r })); })
      .catch(e => { console.log("eBay sync failed", e.message); return env.OLT.put("last_sync", JSON.stringify({ at: new Date().toISOString(), ok: false, error: e.message })); }));
  },
};

/* ------------------------------------------------------------------ API responses */

async function listingsResponse(env, ctx) {
  const data = await env.OLT.get("listings", "json");
  if (!data) {
    // First run: start a sync in the background (at most once every 2 minutes).
    if (env.EBAY_CLIENT_SECRET && !(await env.OLT.get("sync_lock"))) {
      await env.OLT.put("sync_lock", "1", { expirationTtl: 120 });
      ctx.waitUntil(sync(env).then(r => env.OLT.put("last_sync", JSON.stringify({ at: new Date().toISOString(), ...r }))).catch(e => env.OLT.put("last_sync", JSON.stringify({ at: new Date().toISOString(), ok: false, error: e.message }))));
    }
    return json({ error: "Not synced yet" }, 503, { "Cache-Control": "no-store" });
  }
  return json(data, 200, { "Cache-Control": "public, max-age=300" });
}

async function postsResponse(env) {
  const data = (await env.OLT.get("autoposts", "json")) || { posts: [] };
  return json(data, 200, { "Cache-Control": "public, max-age=300" });
}

function json(obj, status = 200, headers = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });
}

/* ------------------------------------------------------------------ eBay */

async function getToken(env) {
  const cached = await env.OLT.get("ebay_token", "json");
  if (cached && cached.expires > Date.now() + 60_000) return cached.token;
  const res = await fetch(`${API}/identity/v1/oauth2/token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Authorization: "Basic " + btoa(`${env.EBAY_CLIENT_ID}:${env.EBAY_CLIENT_SECRET}`),
    },
    body: `grant_type=client_credentials&scope=${encodeURIComponent(SCOPE)}`,
  });
  if (!res.ok) throw new Error(`eBay token error ${res.status}: ${await res.text()}`);
  const t = await res.json();
  await env.OLT.put("ebay_token", JSON.stringify({ token: t.access_token, expires: Date.now() + t.expires_in * 1000 }), {
    expirationTtl: Math.max(60, t.expires_in - 60),
  });
  return t.access_token;
}

async function ebayGet(env, token, path) {
  const res = await fetch(API + path, {
    headers: {
      Authorization: `Bearer ${token}`,
      "X-EBAY-C-MARKETPLACE-ID": env.EBAY_MARKETPLACE || "EBAY_US",
      "Accept-Language": "en-US",
    },
  });
  if (!res.ok) throw new Error(`eBay ${path.split("?")[0]} ${res.status}: ${(await res.text()).slice(0, 300)}`);
  return res.json();
}

/** All active listings for the seller. category_ids=0 lets the seller filter run without a keyword. */
async function fetchSellerListings(env, token) {
  const seller = env.EBAY_SELLER || "oddlottrading";
  const out = new Map();
  let offset = 0;
  for (let page = 0; page < 50; page++) {
    const q = `/buy/browse/v1/item_summary/search?category_ids=0&filter=${encodeURIComponent(`sellers:{${seller}}`)}&limit=200&offset=${offset}`;
    const r = await ebayGet(env, token, q);
    for (const it of r.itemSummaries || []) {
      const id = it.legacyItemId || (it.itemId || "").split("|")[1];
      if (id && !out.has(id)) out.set(id, it);
    }
    offset += 200;
    if (!r.next || offset >= (r.total || 0)) break;
  }
  return [...out.entries()];
}

function bigImage(u, size = 500) {
  return u ? u.replace(/s-l\d+\.(jpg|jpeg|png|webp)/i, `s-l${size}.webp`) : "";
}

function categorize(t) {
  const tl = t.toLowerCase();
  if (tl.includes("stock certificate")) return "Stock Certificates";
  if (/banknote|nickels?\b|penny|coin|krugerrand|francs|currency|silver round|bullion/.test(tl)) return "Coins & Currency";
  if (/comic|superman|batman|marvel|spider-man|x-men/.test(tl)) return "Comics";
  if (/ticket|photo|newspaper|yearbook|calendar|program|sports illustrated|scorecard|magazine/.test(tl)) return "Memorabilia";
  if (/sealed pack|pack \d+ cards|cards box|hobby box|blaster|wax box/.test(tl)) return "Sealed Packs & Boxes";
  if (/football|nfl|panini prizm.*(qb|rb|wr)|favre|irvin/.test(tl)) return "Football Cards";
  if (/basketball|nba|lakers|celtics|bulls|warriors|knicks|nets|spurs|mavericks|thunder|okc|timberwolves|jazz|bowman's best/.test(tl)) return "Basketball Cards";
  if (/card|topps|bowman|fleer|donruss|score|upper deck|panini/.test(tl)) return "Baseball Cards";
  return "Collectibles";
}

function yearOf(t) {
  const ys = (t.match(/\b(19\d{2}|20[0-2]\d)\b/g) || []).map(Number);
  return ys.length ? Math.min(...ys) : null;
}

function slugify(s) {
  return s.normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase().slice(0, 60).replace(/-$/, "");
}

/** Main sync: listings -> KV; new listings without a written post get an auto post. */
async function sync(env) {
  const started = Date.now();
  const token = await getToken(env);
  const entries = await fetchSellerListings(env, token);

  const previous = await env.OLT.get("listings", "json");
  // Safety net: never wipe the shop because of an API hiccup.
  if (!entries.length && previous && previous.items && previous.items.length > 0) {
    return { ok: false, reason: "eBay returned 0 items; kept previous data", kept: previous.items.length };
  }

  // Written posts (shipped with the site) keyed by eBay item id.
  let written = {};
  try {
    const r = await env.ASSETS.fetch(new Request("https://assets.local/data/posts.json"));
    if (r.ok) written = await r.json();
  } catch (e) {}

  const auto = (await env.OLT.get("autoposts", "json")) || { posts: [] };
  const autoById = new Map(auto.posts.map(p => [p.id, p]));
  let newAuto = 0;

  const items = [];
  for (const [id, it] of entries) {
    const price = Number((it.price && it.price.value) || 0);
    const shipOpt = (it.shippingOptions || [])[0];
    const shipping = shipOpt && shipOpt.shippingCost ? Number(shipOpt.shippingCost.value) : 0;
    const img = (it.image && it.image.imageUrl) || ((it.thumbnailImages || [])[0] || {}).imageUrl || "";
    const item = {
      id,
      title: it.title,
      price,
      condition: it.condition || null,
      shipping,
      category: categorize(it.title),
      year: yearOf(it.title),
      image: bigImage(img),
      url: `https://www.ebay.com/itm/${id}`,
      bestOffer: (it.buyingOptions || []).includes("BEST_OFFER"),
      buyItNow: (it.buyingOptions || []).includes("FIXED_PRICE"),
      slug: null,
      created: it.itemCreationDate || null,
    };
    if (written[id]) {
      item.slug = written[id].slug;
    } else {
      // New listing: build an auto post (once) from the item's full details.
      if (!autoById.has(id) && newAuto < 25) {
        try {
          const d = await ebayGet(env, token, `/buy/browse/v1/item/get_item_by_legacy_id?legacy_item_id=${id}`);
          const post = buildAutoPost(id, item, d);
          await env.OLT.put(`post:${id}`, JSON.stringify(post));
          autoById.set(id, { id, slug: `item-${id}`, headline: post.headline, image: item.image, price, category: item.category, created: item.created });
          newAuto++;
        } catch (e) {
          console.log("detail fetch failed", id, e.message);
        }
      }
      if (autoById.has(id)) item.slug = `item-${id}`;
    }
    items.push(item);
  }

  // Newest first by creation date when available; written posts keep eBay order otherwise.
  items.sort((a, b) => (b.created || "").localeCompare(a.created || ""));

  const activeIds = new Set(items.map(i => i.id));
  const autoPosts = [...autoById.values()].filter(p => activeIds.has(p.id))
    .sort((a, b) => (b.created || "").localeCompare(a.created || ""));

  // Items that were listed last sync but are gone now are treated as sold.
  let newlySold = 0;
  if (previous && previous.items) {
    const gone = previous.items.filter(i => !activeIds.has(i.id));
    if (gone.length && gone.length <= 25) {
      const log = (await env.OLT.get("recent_sold", "json")) || { items: [] };
      const known = new Set(log.items.map(i => i.id));
      const now = new Date().toISOString();
      for (const g of gone) {
        if (known.has(g.id)) continue;
        log.items.unshift({ id: g.id, title: g.title, image: g.image, category: g.category, slug: g.slug || null, soldAt: now });
        newlySold++;
      }
      log.items = log.items.slice(0, 40);
      await env.OLT.put("recent_sold", JSON.stringify(log));
    }
  }

  await env.OLT.put("listings", JSON.stringify({ updated: new Date().toISOString(), seller: env.EBAY_SELLER, items }));
  await env.OLT.put("autoposts", JSON.stringify({ posts: autoPosts }));

  return { ok: true, items: items.length, newAutoPosts: newAuto, newlySold, ms: Date.now() - started };
}

/* ------------------------------------------------------------------ auto posts */

function stripHtml(h) {
  return (h || "")
    .replace(/<(script|style)[\s\S]*?<\/\1>/gi, " ")
    .replace(/<br\s*\/?>|<\/p>|<\/div>|<\/li>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/[ \t]+/g, " ").replace(/\n\s*\n+/g, "\n").trim();
}

function buildAutoPost(id, item, d) {
  const aspects = (d.localizedAspects || []).map(a => [a.name, a.value]).filter(([n, v]) => n && v);
  const get = n => (aspects.find(([k]) => k.toLowerCase() === n.toLowerCase()) || [])[1];
  const player = get("Player/Athlete") || get("Player") || get("Character");
  const set = get("Set") || get("Series") || get("Publisher");
  const year = get("Year Manufactured") || get("Season") || get("Publication Year") || get("Year") || item.year;
  const desc = stripHtml(d.description || d.shortDescription || "").slice(0, 2500);
  const images = [d.image && d.image.imageUrl, ...((d.additionalImages || []).map(i => i.imageUrl))].filter(Boolean).map(u => bigImage(u, 1600)).slice(0, 6);

  const intro = [
    `Fresh to the Odd Lot shop: ${item.title}.`,
    player && set ? `This piece features ${player} from ${year ? year + " " : ""}${set}.` : set ? `It comes from ${year ? year + " " : ""}${set}.` : "",
    item.condition ? `It's listed in ${item.condition.toLowerCase()} condition, and the photos on eBay show the exact item you'll receive.` : `The photos on eBay show the exact item you'll receive.`,
  ].filter(Boolean).join(" ");

  return { id, headline: item.title, intro, description: desc, aspects: aspects.slice(0, 16), images, created: item.created };
}

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = n => "$" + Number(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

async function autoPostPage(env, id, url) {
  const post = await env.OLT.get(`post:${id}`, "json");
  if (!post) {
    const nf = await env.ASSETS.fetch(new Request(new URL("/404.html", url)));
    return new Response(nf.body, { status: 404, headers: { "Content-Type": "text/html; charset=utf-8" } });
  }
  const listings = (await env.OLT.get("listings", "json")) || { items: [] };
  const item = listings.items.find(i => i.id === id);
  const sold = !item;
  const ebay = `https://www.ebay.com/itm/${id}`;
  const price = item ? money(item.price) : "";
  const ship = item ? (item.shipping ? `+${money(item.shipping)} shipping` : "Free shipping") : "";
  const buy = sold ? "" : `<div class="buybox"><div><span class="price">${price}</span> <span class="ship">${ship}</span>${item.bestOffer ? '<div class="offer-note">or Best Offer</div>' : ""}</div>
      <div class="post-actions"><a class="btn btn-gold" href="${ebay}" target="_blank" rel="noopener">Buy It Now · ${price}</a>
      ${item.bestOffer ? `<a class="btn btn-line" href="${ebay}" target="_blank" rel="noopener">Make an Offer</a>` : ""}</div></div>`;
  const gallery = post.images.slice(1).map(u => `<img src="${esc(u)}" alt="" loading="lazy" referrerpolicy="no-referrer">`).join("");
  const facts = post.aspects.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
  const descHtml = post.description ? `<h2>From the listing</h2>${post.description.split("\n").filter(Boolean).map(l => `<p>${esc(l)}</p>`).join("")}` : "";
  const html = `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(post.headline)} | Odd Lot Trading Co. Blog</title><meta name="description" content="${esc(post.intro.slice(0, 155))}">
<link rel="canonical" href="https://oddlottrading.com/blog/item-${id}/"><meta property="og:image" content="${esc(post.images[0] || "")}">
<link rel="icon" href="/favicon.ico"><link href="https://fonts.googleapis.com/css2?family=Alfa+Slab+One&family=Oswald:wght@400;500;600&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/site.css"></head><body>
<header class="top"><div class="wrap"><a class="brand" href="/"><img src="/assets/logo-round.webp" alt="" width="42" height="42"><span>Odd Lot</span></a>
<nav class="main"><a href="/#shop">Shop</a><a href="/blog/">Blog</a><a href="/#about">About</a><a class="btn btn-gold" href="${STORE}" target="_blank" rel="noopener">eBay Store</a></nav></div></header>
<main class="post"><div class="wrap narrow">
<nav class="crumbs"><a href="/blog/">Blog</a> / <span>${esc(item ? item.category : "Sold")}</span></nav>
<h1>${esc(post.headline)}</h1>
<div class="post-meta">Odd Lot Trading Co. · New listing</div>
<figure class="hero-img"><a href="${ebay}" target="_blank" rel="noopener"><img src="${esc(post.images[0] || "")}" alt="${esc(post.headline)}" referrerpolicy="no-referrer"></a><figcaption>Photo of the actual item from our eBay listing.</figcaption></figure>
${sold ? `<div class="sold-banner">This item has sold. <a href="/#shop">See what's still available &rarr;</a></div>` : buy}
<article class="prose"><p class="lede">${esc(post.intro)}</p>
${facts ? `<h2>Item details</h2><dl class="facts">${facts}</dl>` : ""}
${descHtml}
${gallery ? `<h2>More photos</h2><div class="rel-grid">${gallery}</div>` : ""}
<h2>Make it yours</h2><p>Buy it now${item && item.bestOffer ? ", or make us an offer. We read every one" : ""}. Every purchase goes through eBay checkout, so you're covered by the eBay Money Back Guarantee.</p></article>
${buy.replace('class="buybox"', 'class="buybox bottom"')}
</div></main>
<footer><div class="wrap"><div>© ${new Date().getFullYear()} Odd Lot Trading Co. · All sales handled through <a href="${STORE}" target="_blank" rel="noopener">eBay</a>.</div></div></footer>
</body></html>`;
  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "public, max-age=300" } });
}
