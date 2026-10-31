import json, os
from .http import post_json

def call(prompt,system='You are a YouTube Shorts strategist. Output only valid JSON.'):
    key=os.environ.get('GROQ_API_KEY')
    if not key:return None
    response=post_json('https://api.groq.com/openai/v1/chat/completions',{'model':'openai/gpt-oss-120b','temperature':0.8,'max_tokens':4096,'reasoning_effort':'low','messages':[{'role':'system','content':system},{'role':'user','content':prompt}]},{'Authorization':f'Bearer {key}'},60,(5,15,30))
    try:
        content=response['choices'][0]['message']['content']; start=content.index('{'); end=content.rindex('}')+1; obj=json.loads(content[start:end]); return obj if isinstance(obj,dict) else None
    except Exception:return None
