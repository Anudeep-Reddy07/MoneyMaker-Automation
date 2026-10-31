import os,re,sqlite3
from datetime import datetime,timezone
from .schema import SCHEMA,CLASSES,HABITATS,STATUSES
def connect(path):
 c=sqlite3.connect(path); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
def init_schema(conn):
 conn.executescript(SCHEMA)
 for kind,names in [('class',CLASSES),('habitat',HABITATS),('status',STATUSES)]:
  for name in names:
   if not conn.execute('SELECT 1 FROM groups WHERE name=?',(name,)).fetchone():
    conn.execute('INSERT INTO groups(name,kind) VALUES (?,?)',(name,kind))
 conn.commit()
def now_utc(): return datetime.now(timezone.utc).isoformat()
def fmt_id(prefix,n,width): return f'{prefix}-{n:0{width}d}'
def norm_title(s): return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9 ]',' ',s.lower())).strip()
def restore(db_path,sql_path):
 if os.path.exists(db_path): os.remove(db_path)
 c=connect(db_path)
 if os.path.exists(sql_path):
  with open(sql_path,encoding='utf-8') as f: c.executescript(f.read())
  c.commit()
 else: init_schema(c)
 c.close()
def export(db_path,sql_path):
 c=connect(db_path); init_schema(c); text='\n'.join(c.iterdump())+'\n'
 with open(sql_path,'w',encoding='utf-8',newline='\n') as f: f.write(text)
 c.close()
