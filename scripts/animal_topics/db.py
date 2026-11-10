import os,re,sqlite3,sys
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


def _split_sql_statements(text):
 statements=[]; current=[]
 for line in text.splitlines():
  current.append(line)
  if sqlite3.complete_statement('\n'.join(current)):
   statement='\n'.join(current).strip()
   current=[]
   if statement and not statement.upper().startswith(('BEGIN','COMMIT')):
    statements.append(statement)
 if current and '\n'.join(current).strip():
  raise sqlite3.OperationalError('unfinished SQL export')
 return statements


def _ordered_dump_statements(text):
 statements=_split_sql_statements(text)
 schema=[s for s in statements if s.lstrip().upper().startswith('CREATE ')]
 data=[s for s in statements if not s.lstrip().upper().startswith('CREATE ')]
 priorities={'meta':0,'groups':1,'species':2,'species_groups':3,'facts':4,'topics':5,'videos':6}
 def key(statement):
  if statement.lstrip().upper().startswith('DELETE FROM'):
   return (-1, '')
  match=re.search(r'INSERT INTO\s+"?([^"\s(]+)',statement,re.I)
  return (priorities.get(match.group(1).lower(), 99) if match else 98, statement)
 return schema + sorted(data,key=key)


def _apply_dump(conn,text):
 conn.execute('PRAGMA foreign_keys=OFF')
 conn.execute('BEGIN')
 try:
  for statement in _ordered_dump_statements(text):
   if re.match(r'(DELETE FROM|INSERT INTO)\s+"?sqlite_sequence',statement,re.I):
    continue
   conn.execute(statement)
  if conn.execute('PRAGMA foreign_key_check').fetchone():
   raise sqlite3.IntegrityError('foreign key check failed')
  conn.commit()
 finally:
  conn.execute('PRAGMA foreign_keys=ON')


def _species_count_from_dump(path):
 if not os.path.exists(path):
  return 0
 with open(path,encoding='utf-8') as f:
  text=f.read()
 conn=sqlite3.connect(':memory:')
 try:
  _apply_dump(conn,text)
  return conn.execute('SELECT COUNT(*) FROM species').fetchone()[0]
 finally:
  conn.close()


def restore(db_path,sql_path):
 if os.path.exists(db_path): os.remove(db_path)
 c=connect(db_path)
 try:
  if os.path.exists(sql_path):
   with open(sql_path,encoding='utf-8') as f: text=f.read()
   _apply_dump(c,text)
  else: init_schema(c)
  count=c.execute('SELECT COUNT(*) FROM species').fetchone()[0]
  if count == 0:
   print('restore warning: dump has no species',file=sys.stderr)
 finally:
  c.close()


def export(db_path,sql_path):
 committed_count=_species_count_from_dump(sql_path)
 c=connect(db_path)
 try:
  init_schema(c)
  new_count=c.execute('SELECT COUNT(*) FROM species').fetchone()[0]
  if committed_count > 0 and new_count < committed_count:
   print(
    f'export refused: new DB has {new_count} species, committed dump has {committed_count}',
    file=sys.stderr,
   )
   return
  lines=list(c.iterdump())
  text='\n'.join(_ordered_dump_statements('\n'.join(lines)))+'\n'
  with open(sql_path,'w',encoding='utf-8',newline='\n') as f: f.write(text)
 finally:
  c.close()
