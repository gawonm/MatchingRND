"""Conservative task boundaries with complete block accounting."""
import hashlib
import re
from collections import defaultdict
from .notices import _source_key
from ..config import TECHNICAL_SECTIONS

TITLE = re.compile(r'^(?:(총괄)|(?:(\d+)세부)|(?:세부))?(품목명|과제명|개발과제명|제안요청서명|제안요청서|프로젝트명|RFP명|연구개발과제명|연구과제명|연구주제명|세부과제명|세부품목명)$')
NUMBER = {'품목번호','과제번호','관리번호','기술번호','RFP번호','RFP관리번호'}
SECTIONS = [
    ('개발내용',r'^(?:개념및개발내용|개발기술세부내용|세부개발내용|개발내용|연구개발내용|연구기획내용|연구내용|주요연구내용|지원내용|성과목표및연구내용)'),
    ('개발목표',r'^(?:개발목표|연구개발목표|연구기획목표|과제목표|최종목표|연구목표|개념|연구목적|지원목적)'),
    ('요구기술',r'^(?:요구기술|핵심기술|필요기술|기술요구사항|주요기술)'),
    ('적용대상',r'^(?:적용대상|적용분야|적용범위|대상시스템)'),
    ('실증조건',r'^(?:실증조건|실증내용|실증환경|실증대상|실증계획|검증조건)'),
    ('연구개발범위',r'^(?:연구개발범위|연구기획범위|개발범위|연구범위|사업범위)'),
    ('성능지표',r'^(?:성능지표|성과지표|평가지표|성능목표|정량적목표)'),
    ('평가방법·평가조건',r'^(?:평가방법|평가조건|시험조건|시험방법)'),
    ('지원기간',r'^(?:개발기간|연구기간|지원기간)$'),
    ('지원금액',r'^(?:지원금액|정부지원금|총투입비용)'),
    ('지원조건·특이사항',r'^(?:지원조건|지원대상|특기사항|기타사항|주관기관|주관연구개발기관|기술료|안전관리)'),
    ('기타 원문',r'^(?:지원필요성|지원필요|필요성|기대효과|활용방안|추진배경|추진체계)'),
]

def key(text):
    text = re.sub(r'^[\s□■ㅇ◦○▪※▶▷◆\u2460-\u2473]+','',text)
    text = re.sub(r'^(?:\d+|[가-하])[.)]\s*','',text)
    text = re.sub(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX]+[.)]\s*','',text)
    return re.sub(r'\s+','',text).strip(':：|')

def label_value(block):
    cells = [str(v).strip() for v in block.metadata.get('cells',[]) if str(v).strip()]
    if cells:
        return key(cells[0]),cells[1] if len(cells)>1 else ''
    text = block.page_content.strip()
    match = re.match(r'^\s*[\u2460-\u2473]?\s*((?:총괄\s*|\d+\s*세부\s*|세부\s*)?(?:연구개발과제명|연구과제명|연구주제명|개발과제명|제안요청서명|과제명|품목명|프로젝트명|RFP명)|품목번호|과제번호|관리번호)\s*(?:[:：|]\s*|\s+)(.+)$',text,re.S)
    return (key(match[1]),match[2].strip()) if match else (key(text),'')

def parse_tasks(loaded_docs,pdf_files,data_dir,review_list,document_factory):
    grouped = defaultdict(list)
    for block in loaded_docs:
        grouped[block.metadata['source']].append(block)
    tasks,issues,excluded = [],list(review_list),[]
    for path in pdf_files:
        blocks = grouped.get(_source_key(path,data_dir),[])
        current,parent,pending_number = None,None,''
        blocked_region=False
        uncertain_pages={i['page'] for i in issues if i.get('filename')==path.name and i.get('page') and 'OCR' in i.get('reason','')}
        previous_page=0
        field,scope = '기타 원문',0
        file_tasks,records = [],[]
        identities = {}
        missing_titles = []
        def make_task(title,block,label):
            nonlocal parent,current,field,pending_number
            title = re.split(r'\(TRL\s*:',title,flags=re.I)[0].strip()
            # Lists of children inside a total title cell are context, not task boundaries.
            if label.startswith('총괄'):
                title = re.split(r'\n\s*\([1-9]\s*세부\)',title)[0].strip()
            if not title:
                return None
            child = re.match(r'\(?\s*(\d+)\s*세부\)?',title)
            kind = 'total' if label.startswith('총괄') else 'subtask' if ('세부' in label or child) else 'standalone'
            number = pending_number
            identity = (number if number else scope,key(title),kind)
            # Repeated parent headers on a child's page must not steal the child's body.
            if kind=='total' and parent and key(parent['title'])==key(title):
                return parent
            if identity in identities:
                task = identities[identity]
            else:
                task_id = hashlib.sha256((block.metadata['document_id']+str(identity)).encode()).hexdigest()[:24]
                task = dict(task_id=task_id,title=title,task_number=number,
                    document_id=block.metadata['document_id'],file_hash=block.metadata['file_hash'],
                    filename=path.name,source=block.metadata['source'],
                    title_source={'text':block.page_content,'metadata':dict(block.metadata)},
                    fields=defaultdict(list),metrics=[],task_type=kind,
                    subtask_number=int(child[1]) if child else None,
                    parent_task_id=parent['task_id'] if kind=='subtask' and parent else None,
                    parent_title=parent['title'] if kind=='subtask' and parent else None,
                    status='parsed',boundary_pages=[])
                identities[identity]=task
                file_tasks.append(task)
            task['boundary_pages'].append(block.metadata['page'])
            if kind=='total':
                parent=task
            elif kind=='standalone':
                parent=None
            current,field,pending_number=task,'기타 원문',''
            return task

        for index,block in enumerate(blocks):
            page=block.metadata['page']
            if current and any(previous_page<p<page for p in uncertain_pages):
                current=None
                blocked_region=True
            previous_page=page
            record = {'block_id':f'{block.metadata["page"]}:{index}', 'page':block.metadata['page'],
                      'text':block.page_content,'bbox':block.metadata.get('bbox'),'role':'context','task_id':None}
            records.append(record)
            marker=re.fullmatch(r'([-–—]?)\s*(\d+)\s*([-–—]?)',block.page_content.strip())
            box=block.metadata['bbox']
            recovered_footer=block.metadata.get('recovered_layout') and box[1]>block.metadata.get('page_height',842)-45 and abs((box[0]+box[2])/2-block.metadata.get('page_width',595)/2)<25 and marker and (marker[1] or abs(int(marker[2])-page)<=3)
            if block.metadata['kind']=='page_marker' or recovered_footer:
                continue
            label,value = label_value(block)
            if label in NUMBER and value:
                # End the old task before collecting a new task's header.
                current,field = None,'기타 원문'
                pending_number = value.splitlines()[0].strip()
                blocked_region=False
                scope += 1
                record['role']='boundary'
                continue
            title_match = TITLE.fullmatch(label)
            if title_match:
                if '세부' in label and current and current['task_type']=='total' and page==current['boundary_pages'][-1]:
                    # Child-name rosters in the total header are not separate RFP bodies.
                    current['fields']['기타 원문'].append(document_factory(page_content=block.page_content,
                        metadata={**block.metadata,'block_id':record['block_id']}))
                    record.update(role='task_content',task_id=current['task_id'])
                    continue
                if not value:
                    # A nested table label may have a separate, coordinate-restored row.
                    reconstructed = any(label_value(other)[0]==label and label_value(other)[1]
                        and other.metadata['page']==block.metadata['page']
                        and abs(other.metadata['bbox'][1]-block.metadata['bbox'][1])<45 for other in blocks[max(0,index-5):index+8])
                    if not reconstructed:
                        current=None
                        missing_titles.append(record['block_id'])
                        blocked_region=True
                        record['role']='quarantine'
                    continue
                task = make_task(value,block,label)
                record.update(role='boundary',task_id=task['task_id'] if task else None)
                if current is not None:
                    blocked_region=False
                continue
            if current is None:
                if blocked_region:
                    record['role']='quarantine'
                continue
            # Unknown attachment headings stop attribution until another explicit title.
            if re.match(r'^\s*(?:별첨|별지|붙임|부록)\s*\d+',block.page_content) and not re.search(r'개발|기술|RFP|과제',block.page_content):
                current=None
                record['role']='context'
                continue
            metadata = {**block.metadata,'block_id':record['block_id']}
            if block.metadata['kind']=='metric_table':
                field='성능지표'
                current['fields'][field].append(document_factory(page_content=block.page_content,metadata=metadata))
                current['metrics'].extend({'columns':dict(zip(metadata['headers'],row)),
                    'indicator':next((v for h,v in zip(metadata['headers'],row) if h in {'항목','지표명','평가항목','성능지표'}),''),
                    'goals':[{'stage':h,'value':v} for h,v in zip(metadata['headers'],row) if '차년도' in h or '목표' in h or '단계' in h],
                    'unit':next((v for h,v in zip(metadata['headers'],row) if '단위' in h),''),
                    'evaluation_method':next((v for h,v in zip(metadata['headers'],row) if '평가방법' in h or '시험방법' in h),''),
                    'evaluation_conditions':next((v for h,v in zip(metadata['headers'],row) if '평가조건' in h or '시험조건' in h),''),
                    'page':metadata['page'],'bbox':metadata['bbox']} for row in metadata['rows'])
            else:
                for line in block.page_content.splitlines():
                    if not line.strip():
                        continue
                    heading = key(line.split('|')[0].split(':')[0])
                    detected = next((name for name,pattern in SECTIONS if re.match(pattern,heading)),None)
                    if detected:
                        field=detected
                    current['fields'][field].append(document_factory(page_content=line,metadata=dict(metadata)))
            record.update(role='task_content',task_id=current['task_id'])

        usable=[]
        for task in file_tasks:
            if any(task['fields'].get(section) for section in TECHNICAL_SECTIONS):
                usable.append(task)
            else:
                task['status']='review_required'
                issues.append({'filename':path.name,'page':task['boundary_pages'][0],
                               'reason':'명시적 기술 요구항목 없음','task_id':task['task_id']})
        valid_ids={task['task_id'] for task in usable}
        for record in records:
            if record['task_id'] and record['task_id'] not in valid_ids:
                record['role']='quarantine'
        if not usable:
            excluded.append(path.name)
        if missing_titles or not usable:
            issues.append({'filename':path.name,'page':None,'reason':'제목·과제 경계 검수 필요',
                           'unresolved_title_blocks':missing_titles})
        issues.append({'filename':path.name,'page':None,'reason':'원문 블록 연결 감사',
                       'audit':True,'task_count':len(usable),'raw_block_count':len(records),
                       'context_blocks':sum(r['role']=='context' for r in records),
                       'quarantine_blocks':sum(r['role']=='quarantine' for r in records),
                       'blocks':records})
        tasks.extend(usable)
    return tasks,issues,excluded
