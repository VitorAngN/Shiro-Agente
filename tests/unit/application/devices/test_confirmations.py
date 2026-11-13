

async def test_listener_hears_each_question() -> None:
    import asyncio

    from shiro.application.devices.confirmations import Pending, RemoteConfirmations
    from shiro.domain.models import DecisionKind

    confirmations = RemoteConfirmations(timeout_s=5)
    asked: list[Pending] = []
    confirmations.listener = asked.append
    task = asyncio.create_task(confirmations.ask("Abrir o YouTube?", DecisionKind.CONFIRM_VOICE))
    await asyncio.sleep(0)
    assert [p.prompt for p in asked] == ["Abrir o YouTube?"]
    assert confirmations.is_waiting(asked[0].id)
    assert confirmations.answer(asked[0].id, True)
    assert await task is True
    assert not confirmations.is_waiting(asked[0].id)
