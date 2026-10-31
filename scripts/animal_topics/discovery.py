import datetime, json, math, re, sys, time, urllib.parse
from .db import now_utc
from .http import get_json
from .wishlist import apply
LIVING=[60,45,35,28,22,18,15,10,6,3,1]; EXTINCT=[30,22,16,12,9,6,3,1]
ENDPOINT='https://query.wikidata.org/sparql'

def query_text(kind, minimum, limit, offset):
    if kind=='living':
        return f'''SELECT ?taxon ?name ?sci ?article ?links WHERE {{ ?taxon wdt:P105 wd:Q7432 . ?taxon wdt:P171* wd:Q729 . ?taxon wikibase:sitelinks ?links . FILTER(?links >= {minimum}) FILTER(?taxon != wd:Q15978631) ?article schema:about ?taxon ; schema:isPartOf <https://en.wikipedia.org/> . OPTIONAL {{ ?taxon wdt:P1843 ?name . FILTER(LANG(?name) = "en") }} OPTIONAL {{ ?taxon wdt:P225 ?sci }} FILTER NOT EXISTS {{ ?taxon wdt:P141 wd:Q237350 }} FILTER NOT EXISTS {{ ?taxon wdt:P31 wd:Q23038290 }} }} ORDER BY DESC(?links) ?taxon LIMIT {limit} OFFSET {offset}'''
    return f'''SELECT ?taxon ?name ?sci ?article ?links WHERE {{ {{ ?taxon wdt:P141 wd:Q237350 }} UNION {{ ?taxon wdt:P31 wd:Q23038290 }} ?taxon wdt:P105 ?rank . FILTER(?rank IN (wd:Q7432, wd:Q34740)) ?taxon wdt:P171* wd:Q729 . ?taxon wikibase:sitelinks ?links . FILTER(?links >= {minimum}) ?article schema:about ?taxon ; schema:isPartOf <https://en.wikipedia.org/> . OPTIONAL {{ ?taxon wdt:P1843 ?name . FILTER(LANG(?name) = "en") }} OPTIONAL {{ ?taxon wdt:P225 ?sci }} }} ORDER BY DESC(?links) ?taxon LIMIT {limit} OFFSET {offset}'''

def fetch_pageviews(title, get=get_json):
    end=datetime.datetime.now(datetime.timezone.utc).date()-datetime.timedelta(days=1); start=end-datetime.timedelta(days=89)
    t=urllib.parse.quote(title.replace(' ','_'),safe='')
    data=get(f'https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{t}/daily/{start:%Y%m%d}/{end:%Y%m%d}') or {}
    if not data or 'items' not in data: return None, 0.0
    values=[int(x.get('views',0)) for x in data.get('items',[])]; total=sum(values)
    return total, math.log10(total+1) if values else 0.0

def assert_english_label(qid, expected, get=get_json):
    data=get('https://www.wikidata.org/w/api.php',params={'action':'wbgetentities','ids':qid,'props':'labels','languages':'en','format':'json'}) or {}
    label=data.get('entities',{}).get(qid,{}).get('labels',{}).get('en',{}).get('value')
    if label is not None and label.casefold()!=expected.casefold():
        raise RuntimeError(f'Wikidata label mismatch for {qid}: {label!r} != {expected!r}')
    return True

def insert_binding(conn,b,extinct,source,validate_label=False,label_get=get_json,pageview_get=get_json):
    val=lambda key:b.get(key,{}).get('value')
    qid=val('taxon').rsplit('/',1)[-1]; article=urllib.parse.unquote(val('article').rsplit('/',1)[-1]).replace('_',' '); common=val('name') or re.sub(r'\s+\([^)]*\)$','',article); sci=val('sci')
    if sci and common.casefold()==sci.casefold(): return None
    if validate_label: assert_english_label(qid,common,label_get)
    if conn.execute('SELECT 1 FROM species WHERE wikidata_qid=?',(qid,)).fetchone(): return None
    links=int(float(val('links') or 0)); conn.execute('INSERT INTO species(wikidata_qid,scientific_name,common_name,wikipedia_title,is_extinct,sitelinks,discovered_at,source) VALUES(?,?,?,?,?,?,?,?)',(qid,sci,common,article,int(extinct),links,now_utc(),source))
    sid=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    views,pop=fetch_pageviews(article,pageview_get); conn.execute('UPDATE species SET pageviews_90d=?,popularity=? WHERE id=?',(views,pop,sid)); time.sleep(.2)
    return sid

def discover(conn,max_new,wishlist_path=None, fetch=get_json):
    if wishlist_path: apply(conn,wishlist_path)
    quotas=(('living',math.ceil(.8*max_new),LIVING),('extinct',max_new-math.ceil(.8*max_new),EXTINCT)); inserted=[]
    for kind,quota,ladder in quotas:
        if quota<=0: continue
        row=conn.execute('SELECT value FROM meta WHERE key=?',(kind+'_min_sitelinks',)).fetchone()
        if row:
            try: rung=ladder.index(int(row['value']))
            except ValueError: rung=min(int(row['value']),len(ladder)-1)
        else: rung=0
        row=conn.execute('SELECT value FROM meta WHERE key=?',(kind+'_offset',)).fetchone(); offset=int(row['value']) if row else 0
        data=None; requested=quota
        while data is None:
            data=fetch(ENDPOINT,params={'query':query_text(kind,ladder[rung],requested,offset),'format':'json'})
            if data is None:
                if requested<=10: break
                requested=max(10,requested//2)
        if data is None:
            print(f'{kind} discovery failed; paging state unchanged',file=sys.stderr); continue
        rows=data.get('results',{}).get('bindings',[])
        for binding in rows:
            sid=insert_binding(conn,binding,kind=='extinct','wikidata_'+kind,validate_label=True,label_get=fetch,pageview_get=fetch)
            if sid: inserted.append(sid)
        if len(rows)<quota:
            rung=min(rung+1,len(ladder)-1)
        else:
            offset += len(rows)
        conn.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',(kind+'_min_sitelinks',str(ladder[rung]))); conn.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',(kind+'_offset',str(offset))); conn.commit()
    return inserted
