"""固定流程：照片收齊 → ② 擷取 → ③ 核對 → ④ 分派。任何一步失敗就轉人工，不重試。"""
from __future__ import annotations

import logging

from . import actions, store
from .agents import check, extract, triage
from .models import Stage

log = logging.getLogger(__name__)


def after_photos(case_id: str) -> None:
    case = store.load(case_id)
    if case.stage != Stage.collecting or not actions.pages_ok(case):
        return
    actions.set_stage(case, "system", Stage.extracting)
    store.save(case)
    try:
        photos = [store.case_dir(case.id) / "photos" / p.file for p in case.photos if p.ok]
        actions.add_extraction(case, "agent:extract", extract.run(case, photos))
        flags = check.run(case)
        triage.after_extraction(case, flags)
        actions.set_stage(case, "system", Stage.reviewing)
    except Exception as e:  # agent 失敗：標記並交給人
        log.exception("pipeline failed")
        actions.set_stage(case, "system", Stage.needs_human, str(e))
        actions.add_task(case, "system", f"自動處理失敗，請人工處理：{e}")
    store.save(case)
