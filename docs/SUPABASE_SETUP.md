# Supabase RAG 실행

## 저장 구조

`rag` 전용 스키마에 다음 테이블을 둡니다. Dashboard Table Editor에서 스키마를 `rag`로 선택하세요.

- `documents`: 제목, 자료 종류, 연도, 기관, 분류, 파일 위치, 전체 원문.
- `chunks`: 문서와 연결된 검색 텍스트, 섹션, 0부터 시작하는 물리 페이지, 원문 위치 메타데이터.
- `embeddings`: 청크와 연결된 1024차원 벡터.
- `announcements`, `rfp_tasks`, `task_announcements`: 공고, PDF 내부 과제, 공고-과제 연결.
- `patents`, `ntis_projects`: 특허번호·분류 및 NTIS 과제번호·기관.
- `corpora`: 임베딩 프로필, 전체 자료 지문, 파서 출력. RFP 요구사항·표·좌표를 재구성할 수 있도록 보존합니다.

모든 문서와 질문은 `dragonkue/BGE-m3-ko`, L2 정규화, 코사인 거리로 통일합니다. 이전 NTIS/OpenAI 및 RFP/BGE-m3 벡터를 혼합하지 않습니다. 기존 Chroma 파일은 자동 삭제하지 않습니다.

## 연결과 권한

`.env.example`의 DB 항목을 `.env`에 설정합니다. Supabase Connect의 Session pooler 값을 그대로 사용하세요. Secret key는 DB 비밀번호가 아닙니다.

이 구현은 `psycopg`로 DB에 직접 접속합니다. `rag`는 Data API에 노출하지 않는 백엔드 전용 스키마이며 `anon`·`authenticated`의 접근은 차단합니다. 현재 DB 계정은 환경의 접속 계정입니다. 기업별 웹 서비스 접근은 별도의 인증·소유권 정책을 구현한 뒤 제공해야 합니다. 시나리오 특허 CSV는 실제 기업 소유권을 증명하지 않습니다.

## 실행 순서

기존 RAG 의존성이 설치된 환경에 `requirements-supabase.txt`를 추가 설치합니다. GPU에서는 CUDA 지원 PyTorch를 사용해야 합니다.

```powershell
python -m app.scripts.supabase_rag setup
python -m app.scripts.supabase_rag ingest --modules technology rfp policy ntis company
python -m app.scripts.supabase_rag status
python -m app.scripts.verify_supabase_rag
python -m app.scripts.supabase_rag search --module rfp --query "폐열 회수 열교환기 ORC 터빈" --top-k 5
python -m app.scripts.run_analysis --backend supabase --query "보유기술과 개발 목표를 입력하세요"
```

GPU 환경이 `.venv-gpu`에 있으면 위 `python` 대신 `.\.venv-gpu\Scripts\python.exe -X utf8`를 사용합니다. VS Code의 Python 인터프리터도 해당 파일을 선택합니다. 이 PC에서 만든 GPU 환경은 기존 `itda/.venv`의 RAG 의존성을 `.pth`로 읽습니다. 다른 PC에서는 독립적으로 의존성을 설치해야 합니다.

`RAG_EMBEDDING_DEVICE=cuda`는 GPU 사용을 강제합니다. CUDA를 사용할 수 없으면 CPU로 조용히 전환하지 않고 오류가 납니다. `auto`는 GPU가 없으면 CPU를 사용합니다.

기술나눔 적재는 기존 `tech_documents.jsonl`과 설정에 해당하는 청크 JSONL을 사용합니다. 없으면 기존 문서·청크 생성 스크립트를 먼저 실행하세요. 나머지는 원본을 파싱하며 각 모듈의 기존 섹션·표·조문 청킹을 유지합니다. NTIS·기업 특허는 제목을 포함하여 긴 본문을 토큰 단위로 분할합니다.

적재 중 임베딩 캐시를 저장합니다. 중단 후 같은 명령을 다시 실행하면 캐시를 재사용합니다. DB는 자료 종류별 트랜잭션으로 완성된 스냅샷만 반영합니다. 동일 지문이면 DB 적재를 생략합니다. 변경된 자료 종류를 재적재하면 그 종류의 이전 스냅샷을 교체하고 다른 종류는 유지합니다.

## 검색과 기존 분석 연결

Supabase 경로는 청크/원문을 DB에서 읽고 BM25를 메모리에서 구성합니다. 벡터 검색과 BM25 순위를 RRF로 결합합니다. 기술나눔·NTIS의 기존 리랭커와 후속 생성·인용 검증은 유지합니다. 공통 `ModuleResult` 형식도 유지합니다. 질문 실행에서는 PDF 파싱·전체 문서 임베딩을 하지 않습니다.

초기 검색 함수는 자료 종류·메타데이터를 먼저 제한한 뒤 정확한 코사인 순위를 계산합니다. 전체 벡터의 근사 검색 후 필터링해서 작은 자료군의 후보가 사라지는 문제를 방지합니다. HNSW 인덱스는 생성하지만 이 함수의 정확 검색 경로에서는 사용하지 않습니다. 규모가 커지면 자료군별 인덱스·필터 검색 재현율을 비교한 뒤 근사 검색으로 전환하세요.

RFP·법령은 저장된 파서 출력을 복원하므로 기존 요구기술·성능표·조문 검색을 그대로 사용할 수 있습니다. 페이지 컬럼은 0-based이고 기존 PDF 파서 메타데이터는 1-based임을 보존합니다. 웹에서 원문을 공유하려면 현재 로컬 파일 경로를 Storage 객체 경로나 공개 원문 URL로 추가 연결해야 합니다. 이 작업은 PDF 자체를 Storage에 업로드하지 않습니다.

기업 특허는 적재 및 명시적 검색을 지원합니다. 현재 Gap 분석의 보유기술 입력은 사용자 진술을 사용합니다. 특정 기업의 보유특허를 자동 연결하려면 기업 식별자와 소유 관계를 먼저 지정해야 합니다. 전체 시나리오 CSV를 사용자의 보유기술로 간주하지 않습니다.

LLM 반복 호출·잘린 NTIS 원문·인용 검증의 표기 차이는 저장소 이전과 별개의 문제입니다.

## 확인

```sql
select corpus_id, count(*) from rag.documents group by corpus_id;
select corpus_id, count(*) from rag.chunks group by corpus_id;
select corpus_id, embedding_model, embedding_profile from rag.corpora;
```

`python -m unittest discover -s tests`는 네트워크·LLM 호출 없이 공통 계약, 메타데이터 복원, 모델/벡터 검증과 기존 분석 동작을 확인합니다.
