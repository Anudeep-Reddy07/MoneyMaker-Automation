import re
from .db import norm_title

def clean_title(value):
    value=(value or '').replace('‑','-').replace('‐','-').replace('‒','-').replace('’',"'").replace('‘',"'").replace('“','"').replace('”','"').replace('\xa0',' ').replace('\u202f',' ')
    value=re.sub(r'[【】「」『』\[\]]','',value); value=value.splitlines()[0] if value.splitlines() else ''
    return re.sub(r'\s+',' ',value).strip('"#*- \t\r\n')

def _name_pattern(name):
    words=name.split(); patterns=[re.escape(name)]
    if len(words)>1: patterns.append(re.escape(words[-1]))
    return r'(?:'+'|'.join(patterns)+r")(?:s|es|'s)?"

def valid_title(title,name,extinct=False):
    if not 15<=len(title)<=95:return False
    if not re.search(r'(?<!\w)'+_name_pattern(name)+r'(?!\w)',title,re.I):return False
    if extinct and not re.search(r'(?<!\w)(?:extinct|prehistoric|ancient|lost|last|fossil|ice\s+age|dinosaur)(?!\w)',title,re.I):return False
    return True

def parse_candidates(obj):
    if not isinstance(obj,dict) or not isinstance(obj.get('candidates'),list): return []
    return [x for x in obj['candidates'] if isinstance(x,dict)]
