import json, os, re, sys, time
from .db import CLASSES, HABITATS
from .http import get_json
from .groq import call

def _valid_keywords(values, common, extinct):
    if not isinstance(values,list) or not 1<=len(values)<=3 or any(not isinstance(x,str) or not x.strip() or len(x.split())>5 for x in values): return False
    if not extinct and not any(common.casefold()==x.casefold() for x in values): return False
    if extinct and any(re.search(r'\b'+re.escape(common)+r'\b',x,re.I) for x in values): return False
    return True

def enrich(conn,batch):
    if not os.getenv('GROQ_API_KEY') or not os.getenv('PEXELS_API_KEY'):
        print('enrichment skipped: missing API key',file=sys.stderr); return
    rows=conn.execute("SELECT * FROM species WHERE enrichment_status IN ('pending','failed') AND enrichment_attempts<3 ORDER BY CASE WHEN boost>1 THEN 0 ELSE 1 END, discovered_at LIMIT ?",(batch,)).fetchall()
    for row in rows:
        try:
            data=get_json('https://en.wikipedia.org/w/api.php',params={'action':'query','prop':'extracts','explaintext':'1','exchars':'2500','redirects':'1','format':'json','titles':row['wikipedia_title']}) or {}
            pages=data.get('query',{}).get('pages',{}); page=next(iter(pages.values()),{}); text=page.get('extract','')
            if len(text)<400:
                conn.execute("UPDATE species SET status='disabled',disabled_reason='short_text',enrichment_status='failed',enrichment_attempts=enrichment_attempts+1 WHERE id=?",(row['id'],)); conn.commit(); continue
            prompt=(f'Animal: {row["common_name"]}\nExtinct: {bool(row["is_extinct"])}\nSOURCE TEXT:\n{text}\n'
                    'Return JSON with classes, habitats, and visual_keywords. Living species visual_keywords must include the common name plus up to two closely related real search terms. Extinct species must never use the species name; use a closest living relative, museum skeleton, fossil, or similar real stock-footage subjects.')
            result=call(prompt) or {}; classes=[x for x in result.get('classes',[]) if x in CLASSES]; habitats=[x for x in result.get('habitats',[]) if x in HABITATS]; keywords=result.get('visual_keywords',[])
            if not classes or not habitats or not _valid_keywords(keywords,row['common_name'],bool(row['is_extinct'])): raise ValueError('invalid enrichment response')
            score=0
            for keyword in keywords:
                response=get_json('https://api.pexels.com/videos/search',headers={'Authorization':os.environ['PEXELS_API_KEY']},params={'query':keyword,'per_page':1}) or {}
                remaining=response.get('_headers',{}).get('X-Ratelimit-Remaining',response.get('X-Ratelimit-Remaining'))
                if remaining is not None and int(remaining)<25: raise StopIteration('Pexels rate limit remaining below 25')
                score=max(score,int(response.get('total_results',0)))
            if not row['is_extinct']:
                response=get_json('https://api.pexels.com/videos/search',headers={'Authorization':os.environ['PEXELS_API_KEY']},params={'query':row['common_name'],'per_page':1}) or {}
                remaining=response.get('_headers',{}).get('X-Ratelimit-Remaining',response.get('X-Ratelimit-Remaining'))
                if remaining is not None and int(remaining)<25: raise StopIteration('Pexels rate limit remaining below 25')
                score=max(score,int(response.get('total_results',0)))
            with conn:
                conn.execute("UPDATE species SET wiki_text=?,visual_keywords=?,footage_score=?,enrichment_status='done',enrichment_attempts=enrichment_attempts+1,status=CASE WHEN ?<15 THEN 'disabled' ELSE status END,disabled_reason=CASE WHEN ?<15 THEN 'low_footage' ELSE disabled_reason END WHERE id=?",(text,json.dumps(keywords),score,score,score,row['id']))
                names=classes+habitats+(['Extinct'] if row['is_extinct'] else ['Living'])
                for name in names:
                    gid=conn.execute('SELECT id FROM groups WHERE name=?',(name,)).fetchone()['id']; conn.execute('INSERT OR IGNORE INTO species_groups(species_id,group_id) VALUES(?,?)',(row['id'],gid))
            time.sleep(1.5)
        except StopIteration as exc:
            print(str(exc),file=sys.stderr); return
        except Exception as exc:
            print(f'enrichment failed {row["common_name"]}: {exc}',file=sys.stderr)
            conn.execute("UPDATE species SET enrichment_status='failed',enrichment_attempts=enrichment_attempts+1 WHERE id=?",(row['id'],)); conn.commit()
