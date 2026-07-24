from datetime import datetime

import streamlit as st

from config import load_settings
from knowledge_base import KnowledgeBase, KnowledgeUpdater


@st.cache_data(ttl=900, show_spinner=False)
def load_official_headlines(before: str = "", limit: int = 6) -> dict:
    items = []
    mode = "官方实时"
    try:
        items = KnowledgeUpdater(load_settings()).latest_official_headlines(
            before=before,
            limit=limit,
        )
    except Exception:
        mode = "本地归档"

    if not items:
        mode = "本地归档"
        items = KnowledgeBase().latest_documents(before=before, limit=limit)

    return {
        "items": items,
        "mode": mode if items else "暂无数据",
        "retrieved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
