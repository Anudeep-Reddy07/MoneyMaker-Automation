import os,tempfile,unittest
from scripts.animal_topics.db import connect,init_schema,fmt_id,norm_title,export,restore
class TestSchema(unittest.TestCase):
 def _add_species(self,conn,count,prefix='Q'):
  for index in range(count):
   conn.execute("INSERT INTO species(wikidata_qid,common_name,wikipedia_title,discovered_at,source) VALUES(?,?,?,?,?)",(f'{prefix}{index}',f'Species {index}',f'Species {index}','x','wishlist'))
  conn.commit()

 def test_seed_and_ids(self):
  p=tempfile.mktemp(); c=connect(p);init_schema(c)
  self.assertEqual(c.execute('select name from groups order by id limit 3').fetchall()[0][0],'Mammal')
  self.assertEqual(fmt_id('SPC',4,6),'SPC-000004'); self.assertEqual(norm_title('A!  B'),'a b')
  c.execute("insert into species(wikidata_qid,common_name,wikipedia_title,discovered_at,source) values('Q1','A','A','x','wishlist')");i=c.execute('select id from species').fetchone()[0];c.execute('delete from species where id=?',(i,));c.execute("insert into species(wikidata_qid,common_name,wikipedia_title,discovered_at,source) values('Q2','B','B','x','wishlist')");self.assertGreater(c.execute('select id from species').fetchone()[0],i);c.close();os.remove(p)
 def test_roundtrip(self):
  d=tempfile.mktemp();s=tempfile.mktemp();restore(d,s);export(d,s); data=open(s,'rb').read();restore(d,s);export(d,s);self.assertEqual(data,open(s,'rb').read());os.remove(d);os.remove(s)

 def test_export_refuses_smaller_database_and_leaves_dump_unchanged(self):
  committed=tempfile.mktemp(); good=tempfile.mktemp(); smaller=tempfile.mktemp()
  try:
   c=connect(good); init_schema(c); self._add_species(c,2); c.close()
   export(good,committed); original=open(committed,'rb').read()
   c=connect(smaller); init_schema(c); self._add_species(c,1); c.close()
   export(smaller,committed)
   self.assertEqual(open(committed,'rb').read(),original)
  finally:
   for path in (committed,good,smaller):
    if os.path.exists(path): os.remove(path)

 def test_export_accepts_equal_or_larger_database(self):
  committed=tempfile.mktemp(); equal=tempfile.mktemp(); larger=tempfile.mktemp()
  try:
   for path,count in ((equal,2),(larger,3)):
    c=connect(path); init_schema(c); self._add_species(c,count); c.close()
    export(path,committed)
    restored=tempfile.mktemp()
    restore(restored,committed)
    self.assertEqual(connect(restored).execute('SELECT COUNT(*) FROM species').fetchone()[0],count)
    os.remove(restored)
  finally:
   for path in (committed,equal,larger):
    if os.path.exists(path): os.remove(path)

 def test_export_accepts_new_database_when_committed_dump_is_empty(self):
  committed=tempfile.mktemp(); database=tempfile.mktemp()
  try:
   c=connect(database); init_schema(c); c.close()
   export(database,committed)
   c=connect(database); self._add_species(c,1); c.close()
   export(database,committed)
   restored=tempfile.mktemp()
   restore(restored,committed)
   self.assertEqual(_species_count(restored),1)
   os.remove(restored)
  finally:
   for path in (committed,database):
    if os.path.exists(path): os.remove(path)

 def test_export_dump_restores_and_reorders_schema_before_data(self):
  database=tempfile.mktemp(); dump=tempfile.mktemp(); restored=tempfile.mktemp()
  try:
   c=connect(database); init_schema(c); self._add_species(c,1)
   species_id=c.execute('SELECT id FROM species').fetchone()[0]
   c.execute("INSERT INTO facts(species_id,fact_text,fact_key,created_at) VALUES(?,?,?,?)",(species_id,'Fact','fact','x')); c.commit(); c.close()
   export(database,dump); restore(restored,dump)
   c=connect(restored)
   self.assertEqual(c.execute('SELECT COUNT(*) FROM species').fetchone()[0],1)
   self.assertEqual(c.execute('SELECT COUNT(*) FROM facts').fetchone()[0],1)
   c.close()
  finally:
   for path in (database,dump,restored):
    if os.path.exists(path): os.remove(path)

 def test_restore_handles_data_before_referenced_table(self):
  dump=tempfile.mktemp(); database=tempfile.mktemp()
  try:
   open(dump,'w').write('''BEGIN TRANSACTION;
CREATE TABLE facts(id INTEGER PRIMARY KEY,species_id INTEGER REFERENCES species(id),fact_text TEXT);
INSERT INTO facts VALUES(1,1,'Fact');
CREATE TABLE species(id INTEGER PRIMARY KEY,wikidata_qid TEXT,common_name TEXT,wikipedia_title TEXT,discovered_at TEXT,source TEXT);
INSERT INTO species VALUES(1,'Q1','Species','Species','x','wishlist');
COMMIT;
''')
   restore(database,dump)
   self.assertEqual(connect(database).execute('SELECT COUNT(*) FROM facts').fetchone()[0],1)
  finally:
   for path in (dump,database):
    if os.path.exists(path): os.remove(path)


def _species_count(path):
 c=connect(path)
 try:
  return c.execute('SELECT COUNT(*) FROM species').fetchone()[0]
 finally:
  c.close()
