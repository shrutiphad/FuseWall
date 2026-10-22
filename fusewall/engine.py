"""Deterministic upstream simulator. This module never opens a network socket."""

import asyncio
import json
import time

from .store import Fault

ANSWER = (
    "This is a simulated completion from Fusewall's local provider. "
    "Your request was authenticated, checked against organization and session policies, "
    "and reserved before generation. No paid API was contacted. "
    "Review the decision receipt to inspect the simulated usage and released allowance."
)


def words(max_tokens):
    return ANSWER.split()[:max_tokens]


async def wait_owned(task):
    """Do not abandon a DB thread when its caller is canceled, even repeatedly."""
    canceled = False
    while True:
        try:
            return await asyncio.shield(task), canceled
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            canceled = True


async def database_call(function, *args, **kwargs):
    result, canceled = await wait_owned(asyncio.create_task(asyncio.to_thread(function, *args, **kwargs)))
    if canceled:
        raise asyncio.CancelledError
    return result


async def execute(store, key_id, session_id, body, scenario="normal", idempotency=None):
    ticket = await reserve_ticket(store, key_id, session_id, body, scenario, idempotency)
    count = 0
    try:
        await database_call(store.dispatch, ticket["id"])
        if scenario == "provider_error":
            await database_call(store.finish, ticket["id"], 0, "failed", 0)
            raise Fault(502, "simulated_provider_error", "The synthetic provider failed before generating any billable output.", {"request_id": ticket["id"]})
        parts = words(body["max_tokens"])
        for _ in parts:
            await asyncio.sleep(0.035 if scenario == "slow" else 0.001)
            count += 1
            if scenario == "interrupted" and count >= max(1, len(parts)//2):
                receipt = await database_call(store.finish, ticket["id"], count, "failed")
                raise Fault(502, "simulated_interruption", "The synthetic stream stopped after partial usage; the observed usage was settled.", {"request_id": ticket["id"], "receipt": receipt})
        receipt = await database_call(store.finish, ticket["id"], count)
        return {"id": ticket["id"], "object": "chat.completion", "created": int(ticket["created"]),
                "model": body["model"], "choices": [{"index": 0, "message": {"role": "assistant", "content": " ".join(parts)}, "finish_reason": "stop" if count < body["max_tokens"] else "length"}],
                "usage": {"prompt_tokens": ticket["input_tokens"], "completion_tokens": count, "total_tokens": ticket["input_tokens"]+count},
                "fusewall": {"mode": "simulation", "receipt": receipt, "session_id": ticket["session_id"]}}
    except asyncio.CancelledError:
        await database_call(store.finish, ticket["id"], count, "canceled")
        raise


async def reserve_ticket(store, key_id, session_id, body, scenario="normal", idempotency=None):
    task = asyncio.create_task(asyncio.to_thread(store.reserve, key_id, session_id, body, scenario, idempotency))
    ticket, canceled = await wait_owned(task)
    if canceled:
        await database_call(store.finish, ticket["id"], 0, "canceled", 0)
        raise asyncio.CancelledError
    return ticket


async def stream(store, ticket, body, is_disconnected):
    count, completed = 0, False
    try:
        parts = words(body["max_tokens"])
        for word in parts:
            if await is_disconnected():
                return
            await asyncio.sleep(0.025)
            count += 1
            chunk = {"id": ticket["id"], "object": "chat.completion.chunk", "created": int(ticket["created"]), "model": body["model"],
                     "choices": [{"index": 0, "delta": {"content": word + " "}, "finish_reason": None}]}
            yield "data: " + json.dumps(chunk) + "\n\n"
        receipt = await database_call(store.finish, ticket["id"], count)
        completed = True
        yield "data: " + json.dumps({"id": ticket["id"], "object": "chat.completion.chunk", "created": int(time.time()), "model": body["model"],
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop" if count < body["max_tokens"] else "length"}],
            "usage": {"prompt_tokens": ticket["input_tokens"], "completion_tokens": count, "total_tokens": ticket["input_tokens"]+count}, "fusewall": {"mode": "simulation", "receipt": receipt}}) + "\n\n"
        yield "data: [DONE]\n\n"
    finally:
        if not completed:
            # Simulation knows exactly which synthetic output units were emitted.
            # A future real provider must treat unknown final usage conservatively.
            await database_call(store.finish, ticket["id"], count, "canceled")


async def run_lab(store, specification):
    """Own every child until completion/cleanup, including an unexpected storage failure."""
    semaphore = asyncio.Semaphore(specification.parallel)

    async def one(index):
        async with semaphore:
            data = {"model": specification.model, "messages": [{"role": "user", "content": specification.prompt}],
                    "max_tokens": specification.max_tokens, "stream": False}
            try:
                result = await execute(store, specification.key_id, specification.session_id, data, specification.scenario)
                return {"index": index, "status": "settled", "request_id": result["id"], "actual_micro": result["fusewall"]["receipt"]["actual"]}
            except Fault as exc:
                return {"index": index, "status": "blocked" if exc.status in (402, 403, 429) else "failed", "code": exc.code, "details": exc.details}

    tasks = [asyncio.create_task(one(i)) for i in range(specification.calls)]
    try:
        results = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return {"mode": "simulation", "results": results,
            "summary": {s: sum(r["status"] == s for r in results) for s in ("settled", "blocked", "failed")}}
