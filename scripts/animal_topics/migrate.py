import json,os,re
from .db import norm_title,now_utc
def migrate(conn,path='scripts/topic_history_animal.json',force=False):
 if conn.execute("SELECT 1 FROM meta WHERE key='legacy_migrated'").fetchone() and not force:return
 if os.path.exists(path):
  for e in json.load(open(path,encoding='utf-8')).get('history',[]):
   t=e.get('topic',''); n=norm_title(t)
   if conn.execute('SELECT 1 FROM topics WHERE title_norm=?',(n,)).fetchone():continue
   s=None
   for r in conn.execute('SELECT * FROM species'):
    if re.search(r'\b'+re.escape(r['common_name'])+r"(?:s|es|'s)?\b",t,re.I):s=r;break
   ts=e.get('timestamp') or now_utc(); fid=None
   if s:
    key='legacy-'+'-'.join(n.split()[:6]); conn.execute('INSERT OR IGNORE INTO facts(species_id,fact_text,fact_key,created_at) VALUES(?,?,?,?)',(s['id'],t,key,ts)); x=conn.execute('SELECT id FROM facts WHERE species_id=? AND fact_key=?',(s['id'],key)).fetchone();fid=x['id'];conn.execute('UPDATE species SET use_count=use_count+1,last_used_at=? WHERE id=?',(ts,s['id']))
   conn.execute('INSERT INTO topics(species_id,fact_id,title,title_norm,status,legacy,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(s['id'] if s else None,fid,t,n,'published',1,ts,ts))
 conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('legacy_migrated','1')");conn.commit()
