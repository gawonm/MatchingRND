"""Recover words omitted by nested/merged tables, using PDF coordinates only."""
import re
from collections import defaultdict

def compact(value):
    return re.sub(r'\s+','',value)

def recover_layout(pdf_path,blocks,issues,document_factory):
    import pdfplumber
    grouped=defaultdict(list)
    for block in blocks:
        grouped[block.metadata['page']].append(block)
    output=[]
    with pdfplumber.open(pdf_path) as pdf:
        for number,page in enumerate(pdf.pages,1):
            existing=grouped[number]
            if not existing:
                continue  # OCR-only pages remain explicitly flagged by the loader.
            words=page.dedupe_chars(tolerance=1,extra_attrs=()).extract_words(x_tolerance=2,y_tolerance=3)
            representations=[(b.metadata['bbox'],compact(b.page_content)) for b in existing]
            missing=[]
            for word in words:
                x,y=(word['x0']+word['x1'])/2,(word['top']+word['bottom'])/2
                if not any(box[0]-1<=x<=box[2]+1 and box[1]-1<=y<=box[3]+1 and compact(word['text']) in text
                           for box,text in representations):
                    missing.append(word)
            lines=[]
            for word in sorted(missing,key=lambda w:(w['top'],w['x0'])):
                if not lines or abs(lines[-1][0]['top']-word['top'])>3:
                    lines.append([word])
                else:
                    lines[-1].append(word)
            for line in lines:
                line.sort(key=lambda w:w['x0'])
                metadata={**existing[0].metadata,'kind':'text','recovered_layout':True,
                          'page_height':page.height,'page_width':getattr(page,'width',595),
                          'bbox':[min(w['x0'] for w in line),min(w['top'] for w in line),
                                  max(w['x1'] for w in line),max(w['bottom'] for w in line)]}
                metadata.pop('cells',None)
                text=' '.join(w['text'] for w in line)
                marker=re.fullmatch(r'([-–—]?)\s*(\d+)\s*([-–—]?)',text)
                centered=abs((metadata['bbox'][0]+metadata['bbox'][2])/2-metadata['page_width']/2)<25
                if metadata['bbox'][1]>page.height-45 and centered and marker and (marker[1] or abs(int(marker[2])-number)<=3):
                    metadata['kind']='page_marker'
                existing.append(document_factory(page_content=text,metadata=metadata))
            # Restore explicitly labelled, empty title cells from their right-hand words.
            for block in list(existing):
                cells=[str(v).strip() for v in block.metadata.get('cells',[]) if str(v).strip()]
                if len(cells)!=1 or not re.fullmatch(r'(?:총괄|\d+세부|세부)?(?:품목명|과제명|개발과제명|제안요청서명|RFP명)',compact(cells[0])):
                    continue
                box=block.metadata['bbox']
                right=[w for w in words if w['x0']>=box[2]-1 and box[1]-1<=(w['top']+w['bottom'])/2<=box[3]+1]
                if not right:
                    continue
                value=' '.join(w['text'] for w in sorted(right,key=lambda w:(round(w['top']/3),w['x0'])))
                if re.match(r'^(?:공모유형|사업유형|TRL|산업기술)',value):
                    continue
                existing.append(document_factory(page_content=cells[0]+' | '+value,
                     metadata={**block.metadata,'cells':[cells[0],value],'recovered_layout':True,
                               'bbox':[box[0],box[1]-.1,max(w['x1'] for w in right),box[3]]}))
                issues.append({'filename':pdf_path.name,'page':number,'reason':'빈 제목 셀의 우측 원문 좌표 복원'})
            if missing:
                issues.append({'filename':pdf_path.name,'page':number,'reason':'표 추출에서 누락된 단어 좌표 복원','recovered_words':len(missing)})
            output.extend(sorted(existing,key=lambda b:(b.metadata['bbox'][1],b.metadata['bbox'][0])))
    return output
