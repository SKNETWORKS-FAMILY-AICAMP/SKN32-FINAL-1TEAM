"""Bounded local retrieval over the user's existing crawling artifacts; no re-crawl."""
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'res/crawling'
FILES=[('market','industry_research/output/raw_kiet_results.json'),
       ('market','industry_research/output/keyword_history.json'),
       ('development','development_knowledge/output/development_knowledge.json'),
       ('design','web_trend/output/web_design_trends_2026.json')]
STOP={'개발','기술','시스템','사업','계획','활용','실시간','연구','서비스','통한','위한','기반','융합한'}

# 사용자 문서에서 자주 쓰는 복합어를 조사 자료의 표현으로 확장한다.
QUERY_ALIASES={
    '개발계획': {'개발','개발방법론','개발프로세스','단계별','추진내용','개발방법'},
    '핵심기술': {'기술','방법론','아키텍처','모델','전처리','학습','구현'},
    '시장동향': {'시장','동향','산업','수요','트렌드'},
    '경쟁사': {'경쟁','경쟁사','대체','비교'},
}


def terms(text):
    return {t.lower() for t in re.findall(r'[가-힣]{2,}|[A-Za-z][A-Za-z0-9]+',text) if t not in STOP}


def _records(node, pointer=''):
    if isinstance(node,dict):
        if node.get('summaryText') or node.get('knowledgeName') or node.get('trendName'):
            yield pointer,node
        else:
            for key,value in node.items():
                yield from _records(value,pointer+'/'+str(key).replace('~','~0').replace('/','~1'))
    elif isinstance(node,list):
        for i,value in enumerate(node):yield from _records(value,pointer+'/'+str(i))


@lru_cache(maxsize=4)
def _index(signature):
    rows=[]
    for domain,name,_mtime in signature:
        data=json.loads((ROOT/name).read_text(encoding='utf-8'))
        for pointer,record in _records(data):
            title=record.get('title') or record.get('knowledgeName') or record.get('trendName')
            text=record.get('summaryText') or ' '.join(str(record.get(k,'')) for k in ['knowledgeName','categoryName','definition','whenToUse','howToApply','cautions','description','webApplicationExample','agentPromptHint'])
            url=record.get('url') or record.get('source',{}).get('url')
            if not url and record.get('evidence'):url=record['evidence'][0].get('sourceUrl')
            if record.get('evidence'):text+=' '+' '.join(e.get('supportingText','') for e in record['evidence'])
            rows.append({'domain':domain,'sourceRef':name+'#'+pointer,'title':title,'url':url,
                         'publishedAt':record.get('publishedAt'),'text':text,'keyword':record.get('keyword',''),
                         'contentHash':hashlib.sha256(text.encode()).hexdigest()})
    return rows


def retrieve(query, domains=('market','development','design'), limit=6, char_budget=6500):
    signature=tuple((domain,name,(ROOT/name).stat().st_mtime_ns) for domain,name in FILES if (ROOT/name).exists())
    tokens=terms(query)
    expanded=set(tokens)
    for token in tokens: expanded.update(QUERY_ALIASES.get(token, set()))
    ranked=[]
    for row in _index(signature):
        if row['domain'] not in domains:continue
        title=(row['title'] or '').lower(); body=row['text'].lower()
        # Exact query terms/subwords first, allowing compound Korean field names.
        matched=[t for t in expanded if (bool(re.search(r'(?<![a-z0-9])'+re.escape(t)+r'(?![a-z0-9])',body+' '+title)) if re.fullmatch('[a-z0-9]+',t) else t in body or t in title or any(w in t and len(w)>=3 for w in terms(title)))]
        if not matched:continue
        score=sum(4 if t in title else 1 for t in matched)
        positions=[body.find(t) for t in matched if t in body]
        start=max(0,min(positions)-160) if positions else 0
        excerpt=row['text'][start:start+1100]
        ranked.append((score,{**row,'text':excerpt,'matchedTerms':matched,'excerptOffset':start,'excerptTruncated':len(row['text'])>len(excerpt)}))
    ranked.sort(key=lambda pair:(-pair[0],pair[1]['sourceRef']))
    selected=[]; seen=set(); used=0
    for score,row in ranked:
        identity=row['contentHash']
        if identity in seen:continue
        item={k:v for k,v in row.items() if k not in {'keyword','contentHash'}}
        size=len(json.dumps(item,ensure_ascii=False))
        if used+size>char_budget:continue
        selected.append(item); seen.add(identity); used+=size
        if len(selected)>=limit:break
    return {'retrievalMethod':'local lexical retrieval (no embedding API)', 'query':query,
            'queryTerms':sorted(tokens),
            'sources':selected,'availableFiles':[name for _,name,_ in signature],
            'issues':[] if selected else ['첨부 자료에서 해당 주제의 직접 근거를 찾지 못함; 수치·경쟁사 추정 금지'],
            'contextChars':used,'status':'retrieved' if selected else 'no_relevant_evidence'}

