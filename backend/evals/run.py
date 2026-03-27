from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete

from app.infra.db.session import get_session_manager
from app.infra.telemetry.langsmith import configure_langsmith
from app.modules.agent.chat.service import send_message
from app.modules.agent.search.service import get_search_session, start_agent_search
from app.modules.agent.summary.service import generate_summary
from app.modules.ingest.service import build_article_chunk_rows, build_article_fields, ingest
from app.modules.ingest.types import IngestInput, InputType
from app.modules.notebooks import repo as notebooks_repo
from app.modules.notebooks.models import Article, ArticleChunk
from app.modules.notebooks.service import create_notebook
from app.modules.settings.runtime import resolve_search_api_key, resolve_tavily_api_key
from evals.judges import judge_ingest, judge_search, judge_text_length
from evals.reporters import write_report_bundle

BASE_DIR = Path(__file__).resolve().parent
CASES_DIR = BASE_DIR / 'cases'
RUNS_DIR = BASE_DIR / 'runs'


class EvalUser:
    id = '00000000-0000-0000-0000-000000000001'
    settings_json = {}
    llm_api_key_ciphertext = None
    llm_api_key_last4 = None
    exa_api_key_ciphertext = None
    exa_api_key_last4 = None
    embedding_api_key_ciphertext = None
    embedding_api_key_last4 = None


EVAL_USER = EvalUser()


def load_cases(pipeline: str, profile: str) -> list[dict]:
    path = CASES_DIR / pipeline / f'{profile}.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def _create_eval_notebook(session, *, pipeline: str, case_id: str) -> dict:
    return await create_notebook(
        session,
        user_id=EVAL_USER.id,
        title=f'Eval {pipeline} {case_id} {datetime.now(UTC).strftime("%H%M%S")}',
        emoji='🧪',
        color='#2563eb',
        tags=['eval', pipeline],
    )


async def _delete_eval_notebook(session, *, notebook_id: str) -> None:
    notebook = await notebooks_repo.get_notebook(session, user_id=EVAL_USER.id, notebook_id=notebook_id)
    if notebook is None:
        return
    await notebooks_repo.delete_notebook(session, notebook)
    await session.commit()


async def _create_ingested_article(session, *, notebook_id: str, notebook_title: str, title: str, content: str) -> tuple[Article, object]:
    article = Article(
        user_id=EVAL_USER.id,
        notebook_id=notebook_id,
        input_type='text',
        dedupe_key=f"eval:text:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
        title=title,
        raw_text_input=content,
        preview_markdown=f'# {title}\n\n{content[:180]}',
        parse_status='queued',
        chunk_status='not_started',
        index_status='not_started',
    )
    session.add(article)
    await session.flush()

    result = await ingest(
        session,
        ingest_input=IngestInput(
            input_type=InputType.TEXT,
            notebook_id=notebook_id,
            user_id=EVAL_USER.id,
            notebook_title=notebook_title,
            title=title,
            raw_text=content,
        ),
        article_id=article.id,
        user=EVAL_USER,
    )

    if not result.clean_markdown:
        raise RuntimeError('ingest did not produce readable markdown')

    fields = build_article_fields(result)
    for key, value in fields.items():
        if hasattr(article, key):
            setattr(article, key, value)

    await session.execute(delete(ArticleChunk).where(ArticleChunk.article_id == article.id))
    for row in build_article_chunk_rows(result):
        session.add(ArticleChunk(article_id=article.id, **row))
    article.chunk_status = 'completed' if result.chunks else 'failed'
    article.index_status = 'completed' if result.chunks else 'failed'
    await session.commit()
    await session.refresh(article)
    return article, result


async def _poll_search_until_done(session, *, notebook_id: str, search_session_id: str):
    latest = None
    for attempt in range(90):
        latest = await get_search_session(
            session,
            user_id=EVAL_USER.id,
            notebook_id=notebook_id,
            search_session_id=search_session_id,
        )
        if latest.run.status in {'completed', 'failed'}:
            return latest
        await asyncio.sleep(2 if attempt > 0 else 1)
    raise TimeoutError('search session did not finish within 180s')


async def _run_search_case(session, case: dict) -> dict:
    notebook = await _create_eval_notebook(session, pipeline='search', case_id=case['case_id'])
    exa_api_key, _ = resolve_search_api_key(EVAL_USER)
    tavily_api_key, _ = resolve_tavily_api_key()
    try:
        response = await start_agent_search(
            session,
            user=EVAL_USER,
            notebook_id=notebook['id'],
            query=case['query'],
            mode=case.get('mode', 'auto'),
            max_results=3,
            exa_api_key=exa_api_key,
            tavily_api_key=tavily_api_key,
            notebook_title=notebook['title'],
            existing_article_urls=[],
            notebook_article_summaries=[],
            preferred_sites=[],
        )
        latest = response
        if response.run.id and response.run.status not in {'completed', 'failed'}:
            latest = await _poll_search_until_done(
                session,
                notebook_id=notebook['id'],
                search_session_id=response.run.id,
            )
        judge = judge_search(len(latest.items), case['expected']['min_results'])
        return {
            'case_id': case['case_id'],
            'judge': {
                'score': judge.score,
                'subscores': judge.subscores,
                'pass': judge.passed,
                'reason': judge.reason,
            },
            'meta': {
                'searchSessionId': latest.run.id,
                'status': latest.run.status,
                'resultCount': len(latest.items),
            },
        }
    finally:
        await session.rollback()
        await _delete_eval_notebook(session, notebook_id=notebook['id'])


async def _run_ingest_case(session, case: dict) -> dict:
    notebook = await _create_eval_notebook(session, pipeline='ingest', case_id=case['case_id'])
    try:
        article, result = await _create_ingested_article(
            session,
            notebook_id=notebook['id'],
            notebook_title=notebook['title'],
            title=case['title'],
            content=case['content'],
        )
        judge = judge_ingest(len(result.chunks), case['expected']['min_chunks'])
        return {
            'case_id': case['case_id'],
            'judge': {
                'score': judge.score,
                'subscores': judge.subscores,
                'pass': judge.passed,
                'reason': judge.reason,
            },
            'meta': {
                'articleId': article.id,
                'chunkCount': len(result.chunks),
                'parser': result.parser_name,
            },
        }
    finally:
        await session.rollback()
        await _delete_eval_notebook(session, notebook_id=notebook['id'])


async def _run_summary_case(session, case: dict) -> dict:
    notebook = await _create_eval_notebook(session, pipeline='summary', case_id=case['case_id'])
    try:
        article, _ = await _create_ingested_article(
            session,
            notebook_id=notebook['id'],
            notebook_title=notebook['title'],
            title=case['title'],
            content=case['content'],
        )
        result = await generate_summary(
            session,
            article_id=article.id,
            title=article.title,
            clean_markdown=article.clean_markdown or case['content'],
            language=case.get('language', '中文'),
            user=EVAL_USER,
        )
        judge = judge_text_length(result.get('summary_text', ''), case['expected']['min_chars'], '摘要')
        return {
            'case_id': case['case_id'],
            'judge': {
                'score': judge.score,
                'subscores': judge.subscores,
                'pass': judge.passed,
                'reason': judge.reason,
            },
            'meta': {
                'articleId': article.id,
                'cached': bool(result.get('cached')),
            },
        }
    finally:
        await session.rollback()
        await _delete_eval_notebook(session, notebook_id=notebook['id'])


async def _run_chat_case(session, case: dict) -> dict:
    notebook = await _create_eval_notebook(session, pipeline='chat', case_id=case['case_id'])
    try:
        article, _ = await _create_ingested_article(
            session,
            notebook_id=notebook['id'],
            notebook_title=notebook['title'],
            title='Chat smoke grounding article',
            content=(
                '# 引用能力\n\n'
                '研究笔记本系统需要引用能力，因为回答必须能回到原始证据，'
                '让用户核验结论来自哪一篇文章、哪一段内容，并区分本地资料与网络补充。'
            ),
        )
        result = await send_message(
            session,
            user_id=EVAL_USER.id,
            notebook_id=notebook['id'],
            question=case['question'],
            article_id=article.id,
            conversation_id=None,
            user=EVAL_USER,
        )
        judge = judge_text_length(result.get('answer', ''), case['expected']['min_chars'], '回答')
        return {
            'case_id': case['case_id'],
            'judge': {
                'score': judge.score,
                'subscores': judge.subscores,
                'pass': judge.passed,
                'reason': judge.reason,
            },
            'meta': {
                'conversationId': result.get('conversationId'),
                'route': result.get('route'),
                'citationCount': len(result.get('evidence') or []),
            },
        }
    finally:
        await session.rollback()
        await _delete_eval_notebook(session, notebook_id=notebook['id'])


async def run_pipeline_case(pipeline: str, case: dict) -> dict:
    async for session in get_session_manager().session():
        if pipeline == 'search':
            return await _run_search_case(session, case)
        if pipeline == 'ingest':
            return await _run_ingest_case(session, case)
        if pipeline == 'summary':
            return await _run_summary_case(session, case)
        if pipeline == 'chat':
            return await _run_chat_case(session, case)
    raise RuntimeError('session unavailable')


async def main_async(pipeline: str, profile: str) -> None:
    configure_langsmith()
    bench_run_id = f'{pipeline}-{profile}-{datetime.now(UTC).strftime("%Y%m%d%H%M%S")}'
    cases = load_cases(pipeline, profile)
    results = []
    for case in cases:
        results.append(await run_pipeline_case(pipeline, case))
    report = {
        'bench_run_id': bench_run_id,
        'pipeline': pipeline,
        'profile': profile,
        'generated_at': datetime.now(UTC).isoformat(),
        'cases': results,
    }
    write_report_bundle(RUNS_DIR / bench_run_id, report)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('pipeline', choices=['search', 'ingest', 'summary', 'chat', 'all'])
    parser.add_argument('profile', default='smoke')
    args = parser.parse_args()

    if args.pipeline == 'all':
        async def run_all():
            for pipeline in ['search', 'ingest', 'summary', 'chat']:
                await main_async(pipeline, args.profile)

        asyncio.run(run_all())
        return
    asyncio.run(main_async(args.pipeline, args.profile))


if __name__ == '__main__':
    main()
