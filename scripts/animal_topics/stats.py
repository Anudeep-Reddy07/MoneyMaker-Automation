import datetime, difflib, os, re, sys
from .db import norm_title
from .http import get_json

def _cutoff(days): return (datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=days)).isoformat()
def _youtube_title(s): return norm_title(re.sub(r'#\w+','',s or ''))
def stats(conn):
    key=os.getenv('YOUTUBE_API_KEY'); channel=os.getenv('YOUTUBE_CHANNEL_ID')
    if not key or not channel: print('stats skipped',file=sys.stderr); return
    playlist='UU'+channel[2:]; items=[]; token=None
    for _ in range(4):
        params={'part':'snippet','playlistId':playlist,'maxResults':50,'key':key};
        if token: params['pageToken']=token
        data=get_json('https://www.googleapis.com/youtube/v3/playlistItems',params=params) or {}; items.extend(data.get('items',[])); token=data.get('nextPageToken')
        if not token: break
    latest=[]
    for topic in conn.execute("SELECT t.*,v.id video_row FROM topics t JOIN videos v ON v.id=(SELECT id FROM videos WHERE topic_id=t.id ORDER BY id DESC LIMIT 1) WHERE t.status='published' AND v.youtube_video_id IS NULL ORDER BY t.id DESC"):
        latest.append(topic)
    used_topics=set(); used_videos=set()
    for item in items:
        snippet=item.get('snippet',{}); video_id=snippet.get('resourceId',{}).get('videoId')
        if not video_id or video_id in used_videos: continue
        yt=_youtube_title(snippet.get('title')); exact=next((t for t in latest if t['id'] not in used_topics and yt==t['title_norm']),None)
        best=exact; ratio=1 if exact else 0
        if not best:
            for topic in latest:
                if topic['id'] in used_topics: continue
                score=difflib.SequenceMatcher(None,yt,topic['title_norm']).ratio()
                if score>ratio: ratio=score;best=topic
        if best and ratio>=.9:
            conn.execute('UPDATE videos SET youtube_video_id=? WHERE id=?',(video_id,best['video_row'])); used_topics.add(best['id']);used_videos.add(video_id)
    cutoff=_cutoff(90); videos=list(conn.execute('SELECT id,youtube_video_id FROM videos WHERE youtube_video_id IS NOT NULL AND created_at>=?',(cutoff,)))
    for start in range(0,len(videos),50):
        batch=videos[start:start+50]; ids=','.join(v['youtube_video_id'] for v in batch)
        data=get_json('https://www.googleapis.com/youtube/v3/videos',params={'part':'statistics','id':ids,'key':key}) or {}
        returned={x.get('id'):x.get('statistics',{}) for x in data.get('items',[])}
        for video in batch:
            if video['youtube_video_id'] not in returned: continue
            st=returned[video['youtube_video_id']]; views=int(st['viewCount']) if st.get('viewCount') is not None else None; likes=int(st['likeCount']) if st.get('likeCount') is not None else None
            conn.execute('UPDATE videos SET views=?,likes=?,stats_fetched_at=? WHERE id=?',(views,likes,datetime.datetime.now(datetime.timezone.utc).isoformat(),video['id']))
    conn.commit()

def performance_multipliers(conn):
    cutoff=_cutoff(7); rows=list(conn.execute("SELECT v.views,v.created_at,s.id species_id FROM videos v JOIN topics t ON t.id=v.topic_id JOIN species s ON s.id=t.species_id WHERE v.views IS NOT NULL AND v.created_at<=?",(cutoff,)))
    if len(rows)<10:
        return {row['id']: 1.0 for row in conn.execute('SELECT id FROM species')}
    overall=sum(r['views'] for r in rows)/len(rows); group_rows=conn.execute("SELECT DISTINCT sg.group_id,v.id,v.views FROM videos v JOIN topics t ON t.id=v.topic_id JOIN species s ON s.id=t.species_id JOIN species_groups sg ON sg.species_id=s.id WHERE v.views IS NOT NULL AND v.created_at<=?",(cutoff,)).fetchall()
    grouped={}
    for r in group_rows: grouped.setdefault(r['group_id'],[]).append(r['views'])
    multipliers={g:max(.5,min(2.0,((sum(vals)+5*overall)/(len(vals)+5))/overall)) for g,vals in grouped.items()}
    result={}
    for sid in {r['species_id'] for r in rows}:
        gids=[x['group_id'] for x in conn.execute('SELECT group_id FROM species_groups WHERE species_id=?',(sid,))]; vals=[multipliers[g] for g in gids if g in multipliers]; result[sid]=sum(vals)/len(vals) if vals else 1.0
    return result
