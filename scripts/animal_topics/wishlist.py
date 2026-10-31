import datetime, json, math, os, re, sys, time, urllib.parse
from .db import now_utc
from .http import get_json

def parse(path):
    result=[]
    try: lines=open(path,encoding='utf-8')
    except OSError: return result
    with lines:
        for raw in lines:
            line=raw.strip()
            if not line or line.startswith('#'): continue
            parts=line.split('|',1); name=parts[0].strip()
            try: boost=float(parts[1].strip()) if len(parts)==2 else 3.0
            except ValueError: boost=3.0
            if boost<=0: boost=3.0
            result.append((name,boost))
    return result

def _sparql(qid):
    return f'''SELECT ?name ?sci ?article ?links ?ext WHERE {{ VALUES ?taxon {{ wd:{qid} }} ?taxon wdt:P171* wd:Q729 . ?taxon wikibase:sitelinks ?links . ?article schema:about ?taxon ; schema:isPartOf <https://en.wikipedia.org/> . OPTIONAL {{ ?taxon wdt:P1843 ?name . FILTER(LANG(?name) = "en") }} OPTIONAL {{ ?taxon wdt:P225 ?sci }} BIND(EXISTS {{ ?taxon wdt:P141 wd:Q237350 }} || EXISTS {{ ?taxon wdt:P31 wd:Q23038290 }} AS ?ext) }}'''

def resolve_entry(conn, name, search=None, sparql=None, pageviews=None):
    search = search or get_json; sparql = sparql or get_json
    data=search('https://www.wikidata.org/w/api.php', params={'action':'wbsearchentities','search':name,'language':'en','type':'item','limit':5,'format':'json'}) or {}
    for item in data.get('search',[]):
        qid=item.get('id'); result=sparql('https://query.wikidata.org/sparql',params={'query':_sparql(qid),'format':'json'}) or {}
        rows=result.get('results',{}).get('bindings',[])
        if not rows: continue
        b=rows[0]; val=lambda k:b.get(k,{}).get('value')
        article=urllib.parse.unquote(val('article').rsplit('/',1)[-1]).replace('_',' ')
        sci=val('sci'); ext=val('ext')=='true'; links=int(float(val('links') or 0))
        conn.execute('INSERT OR IGNORE INTO species(wikidata_qid,scientific_name,common_name,wikipedia_title,is_extinct,sitelinks,discovered_at,source) VALUES(?,?,?,?,?,?,?,?)',(qid,sci,name,article,int(ext),links,now_utc(),'wishlist'))
        row=conn.execute('SELECT * FROM species WHERE wikidata_qid=?',(qid,)).fetchone()
        if pageviews:
            views, popularity = pageviews(article)
        else:
            end=datetime.datetime.now(datetime.timezone.utc).date()-datetime.timedelta(days=1)
            start=end-datetime.timedelta(days=89)
            title=urllib.parse.quote(article.replace(' ','_'),safe='')
            data=get_json(f'https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{title}/daily/{start:%Y%m%d}/{end:%Y%m%d}') or {}
            if 'items' not in data: views, popularity=None, 0.0
            else:
                total=sum(int(x.get('views',0)) for x in data.get('items',[])); views, popularity=total,math.log10(total+1) if total else 0.0
        conn.execute('UPDATE species SET pageviews_90d=?,popularity=? WHERE id=?',(views,popularity,row['id']))
        time.sleep(.2)
        return row['id']
    return None

def apply(conn,path,resolve=None):
    entries=parse(path); unresolved=[]
    unresolved_attempts=0
    for name, boost in entries:
        row=conn.execute('SELECT id FROM species WHERE lower(common_name)=lower(?)',(name,)).fetchone()
        if not row:
            if unresolved_attempts >= 25:
                unresolved.append(name)
                continue
            unresolved_attempts += 1
            row_id=resolve(conn,name) if resolve else resolve_entry(conn,name)
            if hasattr(row_id, "keys"):
                row_id = row_id["id"]
        else: row_id=row['id']
        if row_id is None: unresolved.append(name)
        else: conn.execute('UPDATE species SET boost=? WHERE id=?',(boost,row_id))
    values={name.casefold():boost for name,boost in entries}
    for row in conn.execute('SELECT id,common_name FROM species'):
        conn.execute('UPDATE species SET boost=? WHERE id=?',(values.get(row['common_name'].casefold(),1.0),row['id']))
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('wishlist_unresolved',?)",(json.dumps(unresolved),)); conn.commit()
    for name in unresolved: print(f'wishlist unresolved: {name}',file=sys.stderr)
    return unresolved
