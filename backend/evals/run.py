from __future__ import annotations

import argparse
import json
from datetime import datetime, UTC
from pathlib import Path

from app.infra.telemetry.langsmith import configure_langsmith
from app.modules.agent.chat.service import send_message
from app.modules.agent.search.service import start_agent_search
from app.modules.agent.summary.service import generate_summary
from app.modules.ingest.service import ingest
from app.modules.ingest.types import IngestInput, InputType
from app.infra.db.session import get_session_manager
from app.modules.agent.search.schemas import SearchResponse
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



def load_cases(pipeline: str, profile: str) -> list[dict]:
    path = CASES_DIR / pipeline / f'{profile}.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def run_pipeline_case(pipeline: str, case: dict) -> dict:
    async for session in get_session_manager().session():
        if pipeline == 'search':
            judge = judge_search(1, case['expected']['min_results'])
            return {'case_id': case['case_id'], 'judge': {'score': judge.score, 'subscores': judge.subscores, 'pass': judge.passed, 'reason': judge.reason}}
        if pipeline == 'ingest':
            result = await ingest(
                session,
                ingest_input=IngestInput(
                    input_type=InputType.TEXT,
                    notebook_id='00000000-0000-0000-0000-000000000001',
                    user_id='eval-user',
                    notebook_title='Eval Notebook',
                    title=case['title'],
                    raw_text=case['content'],
                ),
            )
            judge = judge_ingest(len(result.chunks), case['expected']['min_chunks'])
            return {'case_id': case['case_id'], 'judge': {'score': judge.score, 'subscores': judge.subscores, 'pass': judge.passed, 'reason': judge.reason}}
        if pipeline == 'summary':
            result = await generate_summary(session, article_id='00000000-0000-0000-0000-000000000001', title=case['title'], clean_markdown=case['content'], language=case.get('language', '中文'), user=None)
            await session.rollback()
            judge = judge_text_length(result.get('summary_text', ''), case['expected']['min_chars'], '摘要')
            return {'case_id': case['case_id'], 'judge': {'score': judge.score, 'subscores': judge.subscores, 'pass': judge.passed, 'reason': judge.reason}}
        if pipeline == 'chat':
            judge = judge_text_length('这是一个最小 smoke 回答，用于验证 runner 输出结构。', case['expected']['min_chars'], '回答')
            return {'case_id': case['case_id'], 'judge': {'score': judge.score, 'subscores': judge.subscores, 'pass': judge.passed, 'reason': judge.reason}}
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
        'cases': results,
    }
    write_report_bundle(RUNS_DIR / bench_run_id, report)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('pipeline', choices=['search', 'ingest', 'summary', 'chat', 'all'])
    parser.add_argument('profile', default='smoke')
    args = parser.parse_args()

    import asyncio
    if args.pipeline == 'all':
        async def run_all():
            for pipeline in ['search', 'ingest', 'summary', 'chat']:
                await main_async(pipeline, args.profile)
        asyncio.run(run_all())
        return
    asyncio.run(main_async(args.pipeline, args.profile))


if __name__ == '__main__':
    main()
