SCHEMA='''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS species(id INTEGER PRIMARY KEY AUTOINCREMENT,wikidata_qid TEXT UNIQUE NOT NULL,scientific_name TEXT,common_name TEXT NOT NULL,wikipedia_title TEXT NOT NULL,is_extinct INTEGER NOT NULL DEFAULT 0,sitelinks INTEGER NOT NULL DEFAULT 0,pageviews_90d INTEGER,popularity REAL,boost REAL NOT NULL DEFAULT 1.0,wiki_text TEXT,visual_keywords TEXT,footage_score INTEGER,enrichment_status TEXT NOT NULL DEFAULT 'pending',enrichment_attempts INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'active',disabled_reason TEXT,use_count INTEGER NOT NULL DEFAULT 0,last_used_at TEXT,discovered_at TEXT NOT NULL,source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE NOT NULL,kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS species_groups(species_id INTEGER NOT NULL REFERENCES species(id),group_id INTEGER NOT NULL REFERENCES groups(id),PRIMARY KEY(species_id,group_id));
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY AUTOINCREMENT,species_id INTEGER NOT NULL REFERENCES species(id),fact_text TEXT NOT NULL,fact_key TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(species_id,fact_key));
CREATE TABLE IF NOT EXISTS topics(id INTEGER PRIMARY KEY AUTOINCREMENT,species_id INTEGER REFERENCES species(id),fact_id INTEGER REFERENCES facts(id),title TEXT NOT NULL,title_norm TEXT NOT NULL UNIQUE,status TEXT NOT NULL,manual INTEGER NOT NULL DEFAULT 0,legacy INTEGER NOT NULL DEFAULT 0,run_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS videos(id INTEGER PRIMARY KEY AUTOINCREMENT,topic_id INTEGER NOT NULL REFERENCES topics(id),task_id TEXT,video_file TEXT,youtube_video_id TEXT,views INTEGER,likes INTEGER,stats_fetched_at TEXT,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
'''
CLASSES=['Mammal','Bird','Reptile','Amphibian','Fish','Insect','Arachnid','Crustacean','Mollusc','Cephalopod','Cnidarian','Dinosaur','Other Invertebrate']
HABITATS=['Aquatic','Terrestrial','Aerial']
STATUSES=['Living','Extinct']
