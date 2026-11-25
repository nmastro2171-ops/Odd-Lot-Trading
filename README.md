# oddlottrading.com

The Odd Lot Trading Co. website: a shop page for the eBay listings, a blog with a post for every item, and an hourly sync with eBay.

```
site/          the website (static files, served by Cloudflare)
  index.html     shop page
  blog/          blog index + one folder per post (213 written posts)
  js/listings.js listings snapshot (used if the live sync isn't available)
  data/posts.json  eBay item id -> blog post (the Worker uses this)
worker/        Cloudflare Worker: eBay sync, /api/*, auto-posts for new listings
build/         content + generator for the blog (python3 build/build_site.py ...)
data/          the listings snapshot the blog was written from
wrangler.toml  Cloudflare config (KV id needs filling in)
```

## How it works

- The Worker runs every hour at minute :07. It gets an app token from eBay and asks the **Browse API** for every active listing from seller `oddlottrading`, then saves the results in Cloudflare KV.
- The shop page loads `/api/listings`, so prices, new items and sold items update on their own. If the API isn't set up yet, the page uses the bundled snapshot.
- Every written blog post checks `/api/listings`. When an item has sold, the post shows a "Sold" banner and hides the buttons. The post stays up for search traffic.
- **New listings** that don't have a written post get an automatic post at `/blog/item-<ebayId>/`. It's built from the listing's item specifics, description and photos, and it appears at the top of the blog. When you'd like a full write-up for a new item, add it to `build/content_items_*.py` and rebuild.
- If eBay ever returns zero items (an outage, for example), the sync keeps the previous data instead of emptying the shop.

## One-time setup (when the eBay developer account is approved)

1. **eBay keys.** In developer.ebay.com, go to *Application Keysets* and create a **Production** keyset. Copy the **App ID (Client ID)** and **Cert ID (Client Secret)**.
   - Before the production keyset is enabled, eBay asks about *Marketplace Account Deletion* notifications. This site stores no eBay user data, only your public listings, so you can choose the exemption option.
2. **KV namespace.** Run `npx wrangler kv namespace create OLT` and paste the id into `wrangler.toml`.
3. **Secrets:**
   ```
   npx wrangler secret put EBAY_CLIENT_ID
   npx wrangler secret put EBAY_CLIENT_SECRET
   npx wrangler secret put REFRESH_KEY      # any long random string
   ```
4. **Deploy** with `npx wrangler deploy`, or connect the GitHub repo in Cloudflare (Workers → Settings → Builds) to auto-deploy on every push.
5. **First sync (optional, instead of waiting up to an hour):**
   ```
   curl -X POST https://oddlottrading.com/api/refresh -H "X-Refresh-Key: <REFRESH_KEY>"
   ```

The sync uses about 24 search calls a day plus one detail call per new listing, which is well under the Browse API's daily limit.

## Rebuilding the blog

```
python3 build/build_site.py data/listings-snapshot.txt site
```
This regenerates `site/blog/*`, `site/js/listings.js`, `site/data/posts.json` and `site/sitemap.xml`.
