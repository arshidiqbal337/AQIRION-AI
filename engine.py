"""Offline evidence-grounded text retrieval. Not an LLM or live web agent."""
import re
import math
from collections import Counter

STOP = set('the a an is are was were be been and or of for to in on with from by at as it its this that these those what how why do does can could would should i you your my our about into than more their they them'.split())

def tokens(s):
    return [x for x in re.findall(r"[a-z0-9]+", s.lower()) if x not in STOP and len(x)>1]

def chunks(text, size=1000, overlap=120):
    text = re.sub(r'\s+', ' ', text).strip()
    if not text: return []
    result=[]; start=0
    while start < len(text):
        end=min(len(text),start+size)
        if end<len(text):
            boundary=text.rfind('. ',start+int(size*.5),end)
            if boundary>start: end=boundary+1
        result.append(text[start:end])
        if end==len(text): break
        start=max(start+1,end-overlap)
    return result

def retrieve(query, documents, limit=6):
    """Return ranked evidence with provenance, using normalized TF-IDF overlap."""
    passages=[{'source':d['name'],'text':part,'document_id':d['id']} for d in documents for part in chunks(d['text'])]
    if not passages:return []
    vocab=[Counter(tokens(p['text'])) for p in passages]
    df=Counter(t for v in vocab for t in v)
    q=Counter(tokens(query)); n=len(vocab)
    scores=[]
    for p,counts in zip(passages,vocab):
        numerator=sum(q[t]*counts[t]*(math.log((n+1)/(df[t]+1))+1)**2 for t in q)
        denominator=math.sqrt(sum((v*(math.log((n+1)/(df[t]+1))+1))**2 for t,v in counts.items())) or 1
        score=numerator/denominator
        if score>0: scores.append({**p,'score':round(score,3)})
    return sorted(scores,key=lambda x:x['score'],reverse=True)[:limit]

def analyze(question, documents):
    evidence=retrieve(question,documents)
    if not evidence:
        return {'status':'insufficient_evidence','summary':'No relevant passages were found in your uploaded documents. Upload relevant sources or refine your question.','evidence':[],'steps':[{'agent':'Research','status':'complete','detail':'Searched available uploaded documents'},{'agent':'Analysis','status':'complete','detail':'No matching evidence found'},{'agent':'Verification','status':'complete','detail':'Answer withheld because evidence is insufficient'},{'agent':'Report','status':'complete','detail':'Prepared a transparent result'}]}
    snippets=[]
    for e in evidence[:4]:
        sentences=re.split(r'(?<=[.!?])\s+',e['text'])
        relevant=sorted(sentences,key=lambda s:len(set(tokens(question))&set(tokens(s))),reverse=True)
        candidate=(relevant[0] if relevant else e['text'])[:420]
        snippets.append(f"[{e['source']}] {candidate}")
    return {'status':'evidence_found','summary':'Relevant excerpts from uploaded sources (not AI-generated factual conclusions):\n\n'+'\n\n'.join(snippets),'evidence':evidence,'steps':[{'agent':'Research','status':'complete','detail':f'Found {len(evidence)} relevant source passages'},{'agent':'Analysis','status':'complete','detail':'Ranked excerpts by query relevance'},{'agent':'Verification','status':'complete','detail':'Each excerpt retains its uploaded file source; factual truth not independently verified'},{'agent':'Report','status':'complete','detail':'Prepared source-linked result'}]}
