-- Backend-only schema. Neither anon nor authenticated can read company data.
create schema if not exists extensions;
create extension if not exists vector with schema extensions;
create schema if not exists rag;
revoke all on schema rag from public, anon, authenticated;

create table if not exists rag.corpora (
    corpus_id text primary key,
    embedding_model text not null check (embedding_model = 'dragonkue/BGE-m3-ko'),
    embedding_profile text not null check (embedding_profile = 'bgem3ko-normalized-v1'),
    fingerprint text not null,
    payload jsonb not null default '{}',
    updated_at timestamptz not null default now()
);
create table if not exists rag.documents (
    corpus_id text not null references rag.corpora on delete cascade,
    document_id text not null,
    source text not null,
    title text not null,
    year integer,
    institution text,
    source_path text,
    category_major text,
    category_middle text,
    category_minor text,
    full_text text not null,
    metadata jsonb not null default '{}',
    payload jsonb not null default '{}',
    primary key (corpus_id, document_id)
);
create table if not exists rag.chunks (
    corpus_id text not null,
    chunk_id text not null,
    document_id text not null,
    section text,
    content text not null,
    page_start integer check (page_start >= 0),
    page_end integer check (page_end >= page_start),
    metadata jsonb not null default '{}',
    payload jsonb not null default '{}',
    primary key (corpus_id, chunk_id),
    foreign key (corpus_id, document_id) references rag.documents on delete cascade
);
create table if not exists rag.embeddings (
    corpus_id text not null,
    chunk_id text not null,
    embedding extensions.vector(1024) not null,
    primary key (corpus_id, chunk_id),
    foreign key (corpus_id, chunk_id) references rag.chunks on delete cascade
);
create table if not exists rag.announcements (
    corpus_id text not null references rag.corpora on delete cascade,
    notice_id text not null,
    title text not null,
    year integer,
    institution text,
    url text,
    payload jsonb not null default '{}',
    primary key (corpus_id, notice_id)
);
create table if not exists rag.rfp_tasks (
    corpus_id text not null,
    task_id text not null,
    document_id text not null,
    task_number text,
    title text not null,
    payload jsonb not null,
    primary key (corpus_id, task_id),
    foreign key (corpus_id, document_id) references rag.documents on delete cascade
);
create table if not exists rag.task_announcements (
    corpus_id text not null,
    task_id text not null,
    notice_id text not null,
    primary key (corpus_id, task_id, notice_id),
    foreign key (corpus_id, task_id) references rag.rfp_tasks on delete cascade,
    foreign key (corpus_id, notice_id) references rag.announcements on delete cascade
);
create table if not exists rag.patents (
    corpus_id text not null,
    document_id text not null,
    patent_number text not null,
    title text not null,
    owner_name text,
    classification text,
    payload jsonb not null default '{}',
    primary key (corpus_id, document_id, patent_number),
    foreign key (corpus_id, document_id) references rag.documents on delete cascade
);
create table if not exists rag.ntis_projects (
    corpus_id text not null,
    document_id text not null,
    project_id text not null,
    title text not null,
    institution text,
    payload jsonb not null default '{}',
    primary key (corpus_id, project_id),
    foreign key (corpus_id, document_id) references rag.documents on delete cascade
);
create index if not exists documents_filter_idx on rag.documents (corpus_id, source, year, institution);
create index if not exists chunks_document_idx on rag.chunks (corpus_id, document_id);
create index if not exists chunks_metadata_idx on rag.chunks using gin (metadata);
create index if not exists embeddings_hnsw_idx on rag.embeddings using hnsw (embedding extensions.vector_cosine_ops);

create or replace function rag.match_chunks(
    query_embedding extensions.vector(1024), target_corpus text,
    match_count integer default 30, metadata_filter jsonb default '{}',
    document_filter jsonb default '{}'
) returns table (
    chunk_id text, document_id text, content text, metadata jsonb,
    similarity double precision, title text, institution text,
    page_start integer, page_end integer
) language sql stable security invoker set search_path = rag, extensions, pg_catalog as $$
    -- Filter BEFORE distance ranking. A global ANN scan can lose small corpora
    -- after filtering; exact ranking is intentional for this initial dataset.
    with eligible as materialized (
        select c.chunk_id,c.document_id,c.content,c.metadata,e.embedding,
               d.title,d.institution,c.page_start,c.page_end
        from rag.embeddings e
        join rag.chunks c using (corpus_id, chunk_id)
        join rag.documents d using (corpus_id, document_id)
        join rag.corpora p using (corpus_id)
        where e.corpus_id = target_corpus
          and p.embedding_model = 'dragonkue/BGE-m3-ko'
          and p.embedding_profile = 'bgem3ko-normalized-v1'
          and c.metadata @> metadata_filter
          and jsonb_build_object('source',d.source,'year',d.year,'institution',d.institution) @> document_filter
    )
    select chunk_id,document_id,content,metadata,1-(embedding <=> query_embedding),
           title,institution,page_start,page_end
    from eligible
    order by embedding <=> query_embedding
    limit greatest(0, least(match_count, 1000));
$$;
revoke all on all tables in schema rag from public, anon, authenticated;
revoke execute on all functions in schema rag from public, anon, authenticated;
grant usage on schema rag to service_role;
grant select, insert, update, delete on all tables in schema rag to service_role;
grant execute on all functions in schema rag to service_role;
alter default privileges in schema rag revoke all on tables from public, anon, authenticated;
alter default privileges in schema rag revoke execute on functions from public, anon, authenticated;
